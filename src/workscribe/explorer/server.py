from __future__ import annotations

import json
import mimetypes
import sqlite3
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from workscribe.config import WorkscribeError, WorkspaceContext
from workscribe.explorer.data import (
    ExplorerQueryError,
    get_row_detail,
    get_table_metadata,
    list_rows,
)


class ExplorerHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        database_path: Path,
        program_root: Path,
        static_dir: Path,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.database_path = Path(database_path).resolve()
        self.program_root = Path(program_root).resolve()
        self.static_dir = Path(static_dir).resolve()


class ExplorerRequestHandler(BaseHTTPRequestHandler):
    server: ExplorerHTTPServer

    def do_GET(self) -> None:
        status, headers, body = self._dispatch(self.server, self.path)
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return

    @classmethod
    def dispatch_for_test(
        cls,
        server: ExplorerHTTPServer,
        path: str,
    ) -> tuple[int, dict[str, str], bytes]:
        return cls._dispatch(server, path)

    @classmethod
    def _dispatch(
        cls,
        server: ExplorerHTTPServer,
        path: str,
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            parsed = urlparse(path)
            if parsed.path.startswith("/api/"):
                return cls._dispatch_api(server, parsed.path, parse_qs(parsed.query))
            return cls._dispatch_static(server, parsed.path)
        except ExplorerQueryError as exc:
            return _json_response(400, {"error": str(exc)})

    @classmethod
    def _dispatch_api(
        cls,
        server: ExplorerHTTPServer,
        path: str,
        query: dict[str, list[str]],
    ) -> tuple[int, dict[str, str], bytes]:
        with _open_readonly_database(server.database_path) as conn:
            if path == "/api/meta":
                metadata = get_table_metadata(conn)
                return _json_response(
                    200,
                    {
                        "database_path": str(server.database_path),
                        "program_root": str(server.program_root),
                        "tables": [table["name"] for table in metadata],
                        "counts": {
                            table["name"]: table["count"]
                            for table in metadata
                        },
                    },
                )
            if path == "/api/tables":
                return _json_response(200, {"tables": get_table_metadata(conn)})

            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "tables"] and parts[3] == "rows":
                return _json_response(
                    200,
                    list_rows(
                        conn,
                        parts[2],
                        limit=_int_query(query, "limit", 50),
                        offset=_int_query(query, "offset", 0),
                        sort=_str_query(query, "sort"),
                        direction=_str_query(query, "direction") or "desc",
                        search=_str_query(query, "search"),
                        filters=_filters_from_query(query),
                    ),
                )
            if len(parts) == 5 and parts[:2] == ["api", "tables"] and parts[3] == "rows":
                return _json_response(200, get_row_detail(conn, parts[2], parts[4]))

        return _json_response(404, {"error": "Not found"})

    @classmethod
    def _dispatch_static(
        cls,
        server: ExplorerHTTPServer,
        path: str,
    ) -> tuple[int, dict[str, str], bytes]:
        relative = unquote(path.lstrip("/"))
        candidate = (server.static_dir / relative).resolve() if relative else server.static_dir / "index.html"
        try:
            candidate.relative_to(server.static_dir)
        except ValueError:
            return _json_response(500, {"error": "Missing static asset"})

        if candidate.is_file():
            return _file_response(candidate)
        if Path(relative).suffix:
            return _json_response(500, {"error": "Missing static asset"})

        index_path = server.static_dir / "index.html"
        if not index_path.is_file():
            return _json_response(500, {"error": "Missing static asset"})
        return _file_response(index_path)


def run_explorer(
    workspace: WorkspaceContext,
    *,
    host: str,
    port: int,
    open_browser: bool,
) -> None:
    static_dir = Path(__file__).with_name("static")
    index_path = static_dir / "index.html"
    if not index_path.is_file():
        raise WorkscribeError(
            "Explorer frontend is not built. Run `npm --prefix frontend run build` first."
        )

    with _open_readonly_database(workspace.database_path) as conn:
        get_table_metadata(conn)

    server = ExplorerHTTPServer(
        (host, port),
        ExplorerRequestHandler,
        database_path=workspace.database_path,
        program_root=workspace.program_root,
        static_dir=static_dir,
    )
    url = f"http://{host}:{server.server_port}"
    print(f"Workscribe explorer: {url}")
    print(f"Database: {server.database_path}")
    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Workscribe explorer stopped.")
    finally:
        server.server_close()


def _open_readonly_database(database_path: Path) -> sqlite3.Connection:
    resolved = Path(database_path).resolve()
    uri = f"file:{quote(str(resolved), safe='/:')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _json_response(status: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload).encode("utf-8")
    return status, {"Content-Type": "application/json"}, body


def _file_response(path: Path) -> tuple[int, dict[str, str], bytes]:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if content_type == "text/html":
        content_type = "text/html; charset=utf-8"
    return 200, {"Content-Type": content_type}, path.read_bytes()


def _str_query(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    return values[0]


def _int_query(query: dict[str, list[str]], name: str, default: int) -> int:
    value = _str_query(query, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ExplorerQueryError(f"Invalid integer for {name}: {value}") from exc


def _filters_from_query(query: dict[str, list[str]]) -> dict[str, str]:
    return {
        key.removeprefix("filter_"): values[0]
        for key, values in query.items()
        if key.startswith("filter_") and values
    }
