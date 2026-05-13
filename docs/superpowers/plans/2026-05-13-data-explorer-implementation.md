# Data Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, read-only Vue SPA launched by `workscribe explore` for inspecting Workscribe SQLite data.

**Architecture:** Add a focused Python explorer package that validates table/column access and exposes read-only HTTP JSON endpoints. Add a Vue/Vite frontend that builds into package static assets served by the local Python server. Wire the command through the existing CLI and keep the database opened through a read-only SQLite URI.

**Tech Stack:** Python 3.12 standard library (`sqlite3`, `http.server`, `unittest`), Vue 3, Vite, existing `argparse` CLI.

---

## File Structure

- Create `src/workscribe/explorer/__init__.py`: package marker for explorer modules.
- Create `src/workscribe/explorer/data.py`: table allowlist, metadata introspection, safe row queries, JSON parsing, relationship descriptors.
- Create `src/workscribe/explorer/server.py`: local HTTP server, API routing, static asset serving, browser URL printing.
- Modify `src/workscribe/cli.py`: add `explore` parser and command handler.
- Modify `pyproject.toml`: include package static assets in builds.
- Create `frontend/package.json`: Vue/Vite scripts and dependencies.
- Create `frontend/index.html`: frontend mount point.
- Create `frontend/src/main.js`: Vue app bootstrap.
- Create `frontend/src/App.vue`: Workbench layout and state orchestration.
- Create `frontend/src/api.js`: API client helpers.
- Create `frontend/src/style.css`: dense operational UI styling.
- Create `frontend/vite.config.js`: build output to `src/workscribe/explorer/static`.
- Create `tests/test_explorer_data.py`: backend data contract tests.
- Create `tests/test_explorer_server.py`: HTTP API tests.
- Create `tests/test_cli_explore.py`: CLI parser and launch tests.
- Modify `README.md`: document `workscribe explore`.

## Task 1: Read-Only Data Access Contract

**Files:**
- Create: `src/workscribe/explorer/__init__.py`
- Create: `src/workscribe/explorer/data.py`
- Test: `tests/test_explorer_data.py`

- [ ] **Step 1: Write failing tests for table metadata and validation**

Create `tests/test_explorer_data.py` with this initial content:

```python
import sqlite3
import unittest

from workscribe.db import initialize_database
from workscribe.explorer.data import ExplorerQueryError, get_table_metadata


class ExplorerDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        initialize_database(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_table_metadata_lists_known_tables_and_columns(self) -> None:
        metadata = get_table_metadata(self.conn)

        table_names = [table["name"] for table in metadata]
        self.assertIn("sessions", table_names)
        sessions = next(table for table in metadata if table["name"] == "sessions")
        self.assertIn("session_key", [column["name"] for column in sessions["columns"]])
        self.assertEqual(["id"], sessions["primary_key"])

    def test_table_metadata_rejects_missing_workscribe_schema(self) -> None:
        empty = sqlite3.connect(":memory:")
        empty.row_factory = sqlite3.Row
        try:
            with self.assertRaisesRegex(ExplorerQueryError, "not a Workscribe database"):
                get_table_metadata(empty)
        finally:
            empty.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.test_explorer_data -v
```

Expected: FAIL or ERROR because `workscribe.explorer.data` does not exist.

- [ ] **Step 3: Implement metadata module**

Create `src/workscribe/explorer/__init__.py`:

```python
"""Local data explorer support."""
```

Create `src/workscribe/explorer/data.py` with:

```python
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


WORKSCRIBE_TABLES = [
    "clients",
    "projects",
    "config_snapshots",
    "sessions",
    "prompts",
    "tool_events",
    "notes",
    "commits",
    "reports",
    "installations",
]

JSON_COLUMNS = {
    "tags_json",
    "config_json",
    "tool_input_json",
    "tool_response_json",
    "metadata_json",
    "changed_files_json",
    "input_session_ids_json",
    "input_commit_ids_json",
    "report_json",
    "notes_json",
}


class ExplorerQueryError(ValueError):
    """Raised when an explorer query requests unsupported data."""


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    type: str
    primary_key: bool


def get_table_metadata(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    existing = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing = [table for table in WORKSCRIBE_TABLES if table not in existing]
    if missing:
        raise ExplorerQueryError("Database is not a Workscribe database; missing table: " + missing[0])

    metadata: list[dict[str, Any]] = []
    for table in WORKSCRIBE_TABLES:
        column_rows = conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
        columns = [
            {"name": row["name"], "type": row["type"], "primary_key": bool(row["pk"])}
            for row in column_rows
        ]
        count = conn.execute(f"SELECT COUNT(*) AS count FROM {quote_identifier(table)}").fetchone()["count"]
        metadata.append(
            {
                "name": table,
                "columns": columns,
                "primary_key": [column["name"] for column in columns if column["primary_key"]],
                "count": int(count),
                "foreign_keys": get_foreign_keys(conn, table),
            }
        )
    return metadata


def get_foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict[str, str]]:
    rows = conn.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})").fetchall()
    return [
        {"column": row["from"], "references_table": row["table"], "references_column": row["to"]}
        for row in rows
    ]


def quote_identifier(value: str) -> str:
    if value not in WORKSCRIBE_TABLES:
        raise ExplorerQueryError(f"Unknown table: {value}")
    return '"' + value.replace('"', '""') + '"'
```

- [ ] **Step 4: Run tests to verify metadata passes**

Run:

```bash
python -m unittest tests.test_explorer_data -v
```

Expected: PASS.

- [ ] **Step 5: Add failing tests for rows, search, sorting, and details**

Append these tests to `ExplorerDataTests`:

```python
    def seed_project_and_session(self) -> None:
        self.conn.execute(
            """
            INSERT INTO clients (id, client_key, name, created_at, updated_at)
            VALUES (1, 'acme', 'Acme', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        self.conn.execute(
            """
            INSERT INTO projects (id, project_key, client_id, name, tags_json, created_at, updated_at)
            VALUES (1, 'workscribe', 1, 'Workscribe', '["billing","telemetry"]',
                    '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        self.conn.execute(
            """
            INSERT INTO sessions (
                id, session_key, project_id, source, cwd, status, created_at, updated_at
            ) VALUES
                (1, 'session-b', 1, 'codex', '/tmp/b', 'active',
                 '2026-01-02T00:00:00+00:00', '2026-01-02T00:00:00+00:00'),
                (2, 'session-a', 1, 'codex', '/tmp/a', 'stopped',
                 '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        self.conn.commit()

    def test_list_rows_supports_pagination_search_and_sort(self) -> None:
        from workscribe.explorer.data import list_rows

        self.seed_project_and_session()

        result = list_rows(
            self.conn,
            "sessions",
            limit=1,
            offset=0,
            sort="session_key",
            direction="asc",
            search="session",
            filters={"status": "active"},
        )

        self.assertEqual(1, result["total"])
        self.assertEqual("session-b", result["rows"][0]["session_key"])
        self.assertEqual(1, result["limit"])
        self.assertEqual(0, result["offset"])

    def test_list_rows_rejects_unknown_table_and_sort_column(self) -> None:
        from workscribe.explorer.data import list_rows

        with self.assertRaisesRegex(ExplorerQueryError, "Unknown table"):
            list_rows(self.conn, "sqlite_master")

        with self.assertRaisesRegex(ExplorerQueryError, "Unknown column"):
            list_rows(self.conn, "sessions", sort="not_a_column")

    def test_row_detail_parses_json_and_related_links(self) -> None:
        from workscribe.explorer.data import get_row_detail

        self.seed_project_and_session()

        detail = get_row_detail(self.conn, "projects", 1)

        self.assertEqual("workscribe", detail["row"]["project_key"])
        self.assertEqual(["billing", "telemetry"], detail["parsed_json"]["tags_json"])
        relation = detail["related"][0]
        self.assertEqual("sessions", relation["table"])
        self.assertEqual("project_id", relation["column"])
        self.assertEqual(2, relation["count"])
```

- [ ] **Step 6: Run tests to verify row behavior fails**

Run:

```bash
python -m unittest tests.test_explorer_data -v
```

Expected: FAIL because `list_rows` and `get_row_detail` are not implemented.

- [ ] **Step 7: Implement safe row queries and row detail**

Add these functions to `src/workscribe/explorer/data.py`:

```python
def list_rows(
    conn: sqlite3.Connection,
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
    sort: str | None = None,
    direction: str = "desc",
    search: str | None = None,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    table_sql = quote_identifier(table)
    columns = get_column_names(conn, table)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    sort_column = sort or default_sort_column(columns)
    validate_column(columns, sort_column)
    direction_sql = "ASC" if direction.lower() == "asc" else "DESC"

    where_sql, params = build_where_clause(columns, search, filters or {})
    count_row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_sql}{where_sql}", params).fetchone()
    rows = conn.execute(
        f"SELECT * FROM {table_sql}{where_sql} ORDER BY {quote_column(sort_column)} {direction_sql} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return {
        "table": table,
        "rows": [dict(row) for row in rows],
        "total": int(count_row["count"]),
        "limit": limit,
        "offset": offset,
        "sort": sort_column,
        "direction": direction_sql.lower(),
    }


def get_row_detail(conn: sqlite3.Connection, table: str, row_id: int) -> dict[str, Any]:
    table_sql = quote_identifier(table)
    columns = get_column_names(conn, table)
    if "id" not in columns:
        raise ExplorerQueryError(f"Table has no id column: {table}")
    row = conn.execute(f"SELECT * FROM {table_sql} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise ExplorerQueryError(f"Row not found: {table}/{row_id}")
    row_dict = dict(row)
    return {
        "table": table,
        "row": row_dict,
        "parsed_json": parse_json_fields(row_dict),
        "related": find_related_records(conn, table, row_id),
    }


def get_column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    quote_identifier(table)
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})")]


def validate_column(columns: list[str], column: str) -> None:
    if column not in columns:
        raise ExplorerQueryError(f"Unknown column: {column}")


def quote_column(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def default_sort_column(columns: list[str]) -> str:
    for candidate in ("updated_at", "created_at", "captured_at", "submitted_at", "committed_at", "id"):
        if candidate in columns:
            return candidate
    return columns[0]


def build_where_clause(
    columns: list[str],
    search: str | None,
    filters: dict[str, str],
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if search:
        text_columns = [column for column in columns if column != "id"]
        clauses.append("(" + " OR ".join(f"CAST({quote_column(column)} AS TEXT) LIKE ?" for column in text_columns) + ")")
        params.extend([f"%{search}%"] * len(text_columns))
    for column, value in filters.items():
        validate_column(columns, column)
        clauses.append(f"CAST({quote_column(column)} AS TEXT) LIKE ?")
        params.append(f"%{value}%")
    if not clauses:
        return "", []
    return " WHERE " + " AND ".join(clauses), params


def parse_json_fields(row: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for column, value in row.items():
        if column in JSON_COLUMNS and isinstance(value, str) and value:
            try:
                parsed[column] = json.loads(value)
            except json.JSONDecodeError:
                continue
    return parsed


def find_related_records(conn: sqlite3.Connection, table: str, row_id: int) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for candidate in WORKSCRIBE_TABLES:
        for foreign_key in get_foreign_keys(conn, candidate):
            if foreign_key["references_table"] == table and foreign_key["references_column"] == "id":
                count = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {quote_identifier(candidate)} WHERE {quote_column(foreign_key['column'])} = ?",
                    (row_id,),
                ).fetchone()["count"]
                related.append(
                    {
                        "table": candidate,
                        "column": foreign_key["column"],
                        "value": row_id,
                        "count": int(count),
                    }
                )
    return related
```

- [ ] **Step 8: Run tests to verify data access passes**

Run:

```bash
python -m unittest tests.test_explorer_data -v
```

Expected: PASS.

- [ ] **Step 9: Commit data access contract**

Run:

```bash
git add src/workscribe/explorer tests/test_explorer_data.py
git commit -m "Add read-only explorer data access"
```

## Task 2: Local HTTP API and Static Server

**Files:**
- Create: `src/workscribe/explorer/server.py`
- Test: `tests/test_explorer_server.py`

- [ ] **Step 1: Write failing HTTP API tests**

Create `tests/test_explorer_server.py`:

```python
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workscribe.db import initialize_database
from workscribe.explorer.server import ExplorerRequestHandler


class FakeServer:
    def __init__(self, database_path: Path, static_dir: Path) -> None:
        self.database_path = database_path
        self.static_dir = static_dir
        self.program_root = database_path.parent


class ExplorerServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / ".codex-workscribe.sqlite"
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            initialize_database(conn)
            conn.execute(
                """
                INSERT INTO clients (id, client_key, name, created_at, updated_at)
                VALUES (1, 'acme', 'Acme', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
        self.static_dir = self.root / "static"
        self.static_dir.mkdir()
        (self.static_dir / "index.html").write_text("<div id=\"app\"></div>")
        self.server = FakeServer(self.database_path, self.static_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_api_meta_returns_json(self) -> None:
        status, headers, body = ExplorerRequestHandler.dispatch_for_test(self.server, "/api/meta")

        self.assertEqual(200, status)
        self.assertEqual("application/json", headers["Content-Type"])
        payload = json.loads(body.decode())
        self.assertEqual(str(self.database_path), payload["database_path"])
        self.assertIn("clients", payload["tables"])

    def test_api_rows_returns_paginated_rows(self) -> None:
        status, headers, body = ExplorerRequestHandler.dispatch_for_test(
            self.server,
            "/api/tables/clients/rows?limit=10&offset=0&sort=name&direction=asc",
        )

        self.assertEqual(200, status)
        payload = json.loads(body.decode())
        self.assertEqual("Acme", payload["rows"][0]["name"])

    def test_unknown_table_returns_400(self) -> None:
        status, headers, body = ExplorerRequestHandler.dispatch_for_test(
            self.server,
            "/api/tables/not_real/rows",
        )

        self.assertEqual(400, status)
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertIn("Unknown table", json.loads(body.decode())["error"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.test_explorer_server -v
```

Expected: FAIL or ERROR because `workscribe.explorer.server` does not exist.

- [ ] **Step 3: Implement the HTTP server**

Create `src/workscribe/explorer/server.py`:

```python
from __future__ import annotations

import json
import mimetypes
import sqlite3
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from workscribe.config import WorkscribeError, WorkspaceContext
from workscribe.explorer.data import ExplorerQueryError, get_row_detail, get_table_metadata, list_rows


class ExplorerHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], database_path: Path, program_root: Path, static_dir: Path) -> None:
        super().__init__(address, ExplorerRequestHandler)
        self.database_path = database_path
        self.program_root = program_root
        self.static_dir = static_dir


class ExplorerRequestHandler(BaseHTTPRequestHandler):
    server: ExplorerHTTPServer

    def do_GET(self) -> None:
        status, headers, body = self.dispatch(self.server, self.path)
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return

    @classmethod
    def dispatch_for_test(cls, server: object, path: str) -> tuple[int, dict[str, str], bytes]:
        return cls.dispatch(server, path)

    @staticmethod
    def dispatch(server: object, path: str) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(path)
        try:
            if parsed.path == "/api/meta":
                return json_response(build_meta(server))
            if parsed.path == "/api/tables":
                with open_readonly_database(server.database_path) as conn:
                    return json_response({"tables": get_table_metadata(conn)})
            if parsed.path.startswith("/api/tables/"):
                return handle_table_api(server, parsed.path, parse_qs(parsed.query))
            return static_response(server.static_dir, parsed.path)
        except ExplorerQueryError as exc:
            return json_response({"error": str(exc)}, status=400)
        except FileNotFoundError:
            return json_response({"error": "Static explorer assets are not built."}, status=500)


def handle_table_api(server: object, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, str], bytes]:
    parts = [unquote(part) for part in path.strip("/").split("/")]
    if len(parts) == 4 and parts[0] == "api" and parts[1] == "tables" and parts[3] == "rows":
        filters = {
            key.removeprefix("filter_"): values[0]
            for key, values in query.items()
            if key.startswith("filter_") and values
        }
        with open_readonly_database(server.database_path) as conn:
            return json_response(
                list_rows(
                    conn,
                    parts[2],
                    limit=int(first(query, "limit", "50")),
                    offset=int(first(query, "offset", "0")),
                    sort=optional_first(query, "sort"),
                    direction=first(query, "direction", "desc"),
                    search=optional_first(query, "search"),
                    filters=filters,
                )
            )
    if len(parts) == 5 and parts[0] == "api" and parts[1] == "tables" and parts[3] == "rows":
        with open_readonly_database(server.database_path) as conn:
            return json_response(get_row_detail(conn, parts[2], int(parts[4])))
    raise ExplorerQueryError("Unsupported explorer API path")


def build_meta(server: object) -> dict[str, object]:
    with open_readonly_database(server.database_path) as conn:
        tables = get_table_metadata(conn)
    return {
        "database_path": str(server.database_path),
        "program_root": str(server.program_root),
        "tables": [table["name"] for table in tables],
        "counts": {table["name"]: table["count"] for table in tables},
    }


def open_readonly_database(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def json_response(payload: object, *, status: int = 200) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json"}, json.dumps(payload, sort_keys=True).encode()


def static_response(static_dir: Path, request_path: str) -> tuple[int, dict[str, str], bytes]:
    target = static_dir / "index.html" if request_path in {"", "/"} else static_dir / request_path.lstrip("/")
    if not target.is_file():
        target = static_dir / "index.html"
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return 200, {"Content-Type": content_type}, target.read_bytes()


def first(query: dict[str, list[str]], key: str, default: str) -> str:
    values = query.get(key)
    return values[0] if values else default


def optional_first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values and values[0] else None


def run_explorer(workspace: WorkspaceContext, *, host: str, port: int, open_browser: bool) -> None:
    static_dir = Path(__file__).with_name("static")
    if not (static_dir / "index.html").is_file():
        raise WorkscribeError("Explorer frontend is not built. Run `npm --prefix frontend run build`.")
    with open_readonly_database(workspace.database_path) as conn:
        get_table_metadata(conn)
    server = ExplorerHTTPServer((host, port), workspace.database_path, workspace.program_root, static_dir)
    url = f"http://{host}:{server.server_address[1]}"
    print(f"Serving Workscribe explorer at {url}")
    print(f"  database: {workspace.database_path}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped Workscribe explorer")
```

- [ ] **Step 4: Run server tests**

Run:

```bash
python -m unittest tests.test_explorer_server -v
```

Expected: PASS.

- [ ] **Step 5: Commit server API**

Run:

```bash
git add src/workscribe/explorer/server.py tests/test_explorer_server.py
git commit -m "Add local explorer API server"
```

## Task 3: CLI Command Wiring

**Files:**
- Modify: `src/workscribe/cli.py`
- Test: `tests/test_cli_explore.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli_explore.py`:

```python
import argparse
import unittest
from pathlib import Path
from unittest.mock import patch

from workscribe.cli import build_parser, cmd_explore


class ExploreCliTests(unittest.TestCase):
    def test_parser_registers_explore_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["explore", "--path", ".", "--port", "8765", "--no-open"])

        self.assertEqual("explore", args.command)
        self.assertEqual(Path("."), args.path)
        self.assertEqual("127.0.0.1", args.host)
        self.assertEqual(8765, args.port)
        self.assertFalse(args.open_browser)

    @patch("workscribe.cli.run_explorer")
    @patch("workscribe.cli.discover_workspace")
    def test_cmd_explore_discovers_workspace_and_runs_server(self, discover_workspace, run_explorer) -> None:
        workspace = object()
        discover_workspace.return_value = workspace
        args = argparse.Namespace(path=Path("."), host="127.0.0.1", port=0, open_browser=False)

        result = cmd_explore(args)

        self.assertEqual(0, result)
        discover_workspace.assert_called_once()
        run_explorer.assert_called_once_with(workspace, host="127.0.0.1", port=0, open_browser=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest tests.test_cli_explore -v
```

Expected: FAIL because `cmd_explore` and parser wiring are missing.

- [ ] **Step 3: Add CLI parser and command handler**

Modify imports in `src/workscribe/cli.py`:

```python
from workscribe.explorer.server import run_explorer
```

Add this parser block after the `report` parser:

```python
    explore_parser = subparsers.add_parser("explore", help="Launch a local read-only SQLite data explorer")
    explore_parser.add_argument("--path", type=Path, default=Path.cwd())
    explore_parser.add_argument("--host", default="127.0.0.1")
    explore_parser.add_argument("--port", type=int, default=0)
    explore_parser.add_argument("--open", dest="open_browser", action="store_true", default=True)
    explore_parser.add_argument("--no-open", dest="open_browser", action="store_false")
    explore_parser.set_defaults(func=cmd_explore)
```

Add this function near `cmd_report`:

```python
def cmd_explore(args: argparse.Namespace) -> int:
    workspace = discover_workspace(args.path.resolve())
    run_explorer(workspace, host=args.host, port=args.port, open_browser=args.open_browser)
    return 0
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
python -m unittest tests.test_cli_explore -v
```

Expected: PASS.

- [ ] **Step 5: Run backend test suite**

Run:

```bash
python -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 6: Commit CLI wiring**

Run:

```bash
git add src/workscribe/cli.py tests/test_cli_explore.py
git commit -m "Wire explorer command into CLI"
```

## Task 4: Vue Workbench Frontend

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.js`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/api.js`
- Create: `frontend/src/style.css`
- Create: `frontend/vite.config.js`
- Generated by build: `src/workscribe/explorer/static/index.html`
- Generated by build: `src/workscribe/explorer/static/assets/*`

- [ ] **Step 1: Add Vue/Vite project files**

Create `frontend/package.json`:

```json
{
  "scripts": {
    "build": "vite build",
    "dev": "vite --host 127.0.0.1"
  },
  "dependencies": {
    "@vitejs/plugin-vue": "^6.0.0",
    "vite": "^7.0.0",
    "vue": "^3.5.0"
  },
  "devDependencies": {}
}
```

Create `frontend/vite.config.js`:

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: resolve(__dirname, '../src/workscribe/explorer/static'),
    emptyOutDir: true
  }
})
```

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Workscribe Explorer</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

- [ ] **Step 2: Add API helpers**

Create `frontend/src/api.js`:

```javascript
async function requestJson(path) {
  const response = await fetch(path)
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`)
  }
  return payload
}

export function fetchMeta() {
  return requestJson('/api/meta')
}

export function fetchTables() {
  return requestJson('/api/tables')
}

export function fetchRows({ table, limit, offset, sort, direction, search, filters }) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  if (sort) params.set('sort', sort)
  if (direction) params.set('direction', direction)
  if (search) params.set('search', search)
  for (const [key, value] of Object.entries(filters || {})) {
    if (value) params.set(`filter_${key}`, value)
  }
  return requestJson(`/api/tables/${encodeURIComponent(table)}/rows?${params.toString()}`)
}

export function fetchRowDetail(table, id) {
  return requestJson(`/api/tables/${encodeURIComponent(table)}/rows/${encodeURIComponent(id)}`)
}
```

- [ ] **Step 3: Add Vue app bootstrap and Workbench component**

Create `frontend/src/main.js`:

```javascript
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
```

Create `frontend/src/App.vue`:

```vue
<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Workscribe Explorer</div>
      <button
        v-for="table in tables"
        :key="table.name"
        class="nav-item"
        :class="{ active: table.name === selectedTableName }"
        @click="selectTable(table.name)"
      >
        <span>{{ table.name }}</span>
        <span class="count">{{ table.count }}</span>
      </button>
      <button class="nav-item disabled" disabled>
        <span>timeline</span>
        <span class="count">later</span>
      </button>
    </aside>

    <section class="grid-pane">
      <header class="toolbar">
        <div>
          <h1>{{ selectedTableName || 'Tables' }}</h1>
          <p>{{ meta?.database_path || 'Loading database metadata...' }}</p>
        </div>
        <input v-model="searchText" class="search" aria-label="Search current table" @keyup.enter="loadRows(0)" />
      </header>

      <div v-if="error" class="notice error">{{ error }}</div>
      <div v-else-if="loading" class="notice">Loading...</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th v-for="column in visibleColumns" :key="column.name" @click="sortBy(column.name)">
                {{ column.name }}
                <span v-if="sort === column.name">{{ direction === 'asc' ? '↑' : '↓' }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.id"
              :class="{ selected: detail?.row?.id === row.id }"
              @click="selectRow(row)"
            >
              <td v-for="column in visibleColumns" :key="column.name">{{ formatCell(row[column.name]) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="rows.length === 0" class="empty">No rows found.</div>
      </div>

      <footer class="pager">
        <button :disabled="offset === 0" @click="loadRows(Math.max(0, offset - limit))">Previous</button>
        <span>{{ offset + 1 }}-{{ Math.min(offset + limit, total) }} of {{ total }}</span>
        <button :disabled="offset + limit >= total" @click="loadRows(offset + limit)">Next</button>
      </footer>
    </section>

    <aside class="detail-pane">
      <h2>Selected Row</h2>
      <div v-if="!detail" class="empty">Select a row to inspect values, JSON, and relationships.</div>
      <template v-else>
        <section class="detail-section">
          <h3>Values</h3>
          <dl>
            <template v-for="(value, key) in detail.row" :key="key">
              <dt>{{ key }}</dt>
              <dd>{{ formatDetail(value) }}</dd>
            </template>
          </dl>
        </section>
        <section v-if="Object.keys(detail.parsed_json).length" class="detail-section">
          <h3>JSON</h3>
          <pre>{{ JSON.stringify(detail.parsed_json, null, 2) }}</pre>
        </section>
        <section v-if="detail.related.length" class="detail-section">
          <h3>Related</h3>
          <button
            v-for="relation in detail.related"
            :key="`${relation.table}-${relation.column}`"
            class="relation"
            @click="selectTable(relation.table, { [relation.column]: String(relation.value) })"
          >
            {{ relation.table }} via {{ relation.column }} ({{ relation.count }})
          </button>
        </section>
      </template>
    </aside>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fetchMeta, fetchRowDetail, fetchRows, fetchTables } from './api'

const meta = ref(null)
const tables = ref([])
const selectedTableName = ref('')
const rows = ref([])
const detail = ref(null)
const loading = ref(false)
const error = ref('')
const searchText = ref('')
const filters = ref({})
const limit = 50
const offset = ref(0)
const total = ref(0)
const sort = ref('id')
const direction = ref('desc')

const selectedTable = computed(() => tables.value.find((table) => table.name === selectedTableName.value))
const visibleColumns = computed(() => (selectedTable.value?.columns || []).slice(0, 8))

onMounted(async () => {
  meta.value = await fetchMeta()
  const payload = await fetchTables()
  tables.value = payload.tables
  if (tables.value.length) {
    await selectTable(tables.value[0].name)
  }
})

watch(searchText, () => {
  window.clearTimeout(window.__workscribeSearchTimer)
  window.__workscribeSearchTimer = window.setTimeout(() => loadRows(0), 250)
})

async function selectTable(name, nextFilters = {}) {
  selectedTableName.value = name
  filters.value = nextFilters
  detail.value = null
  sort.value = 'id'
  direction.value = 'desc'
  await loadRows(0)
}

async function loadRows(nextOffset) {
  if (!selectedTableName.value) return
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchRows({
      table: selectedTableName.value,
      limit,
      offset: nextOffset,
      sort: sort.value,
      direction: direction.value,
      search: searchText.value,
      filters: filters.value
    })
    rows.value = payload.rows
    offset.value = payload.offset
    total.value = payload.total
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function selectRow(row) {
  detail.value = await fetchRowDetail(selectedTableName.value, row.id)
}

function sortBy(column) {
  if (sort.value === column) {
    direction.value = direction.value === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value = column
    direction.value = 'asc'
  }
  loadRows(0)
}

function formatCell(value) {
  if (value === null || value === undefined) return ''
  const text = String(value)
  return text.length > 90 ? `${text.slice(0, 87)}...` : text
}

function formatDetail(value) {
  if (value === null || value === undefined) return ''
  return String(value)
}
</script>
```

- [ ] **Step 4: Add operational UI styling**

Create `frontend/src/style.css`:

```css
:root {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #202124;
  background: #f4f6f8;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

button,
input {
  font: inherit;
}

.shell {
  display: grid;
  grid-template-columns: 220px minmax(420px, 1fr) 360px;
  min-height: 100vh;
}

.sidebar,
.detail-pane {
  background: #ffffff;
  border-color: #d8dde3;
}

.sidebar {
  border-right: 1px solid #d8dde3;
  padding: 16px 12px;
}

.brand {
  font-weight: 700;
  margin-bottom: 16px;
}

.nav-item {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 6px;
  color: #202124;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  padding: 9px 10px;
  text-align: left;
  width: 100%;
}

.nav-item.active {
  background: #dce9f8;
}

.nav-item.disabled {
  color: #7b8490;
  cursor: default;
}

.count {
  color: #59636f;
  font-size: 12px;
}

.grid-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.toolbar {
  align-items: center;
  background: #ffffff;
  border-bottom: 1px solid #d8dde3;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding: 14px 18px;
}

h1,
h2,
h3,
p {
  margin: 0;
}

h1 {
  font-size: 20px;
}

h2 {
  font-size: 16px;
  margin-bottom: 12px;
}

h3 {
  font-size: 13px;
  margin-bottom: 8px;
  text-transform: uppercase;
}

p {
  color: #59636f;
  font-size: 12px;
}

.search {
  border: 1px solid #c8d0d9;
  border-radius: 6px;
  min-width: 260px;
  padding: 8px 10px;
}

.table-wrap {
  overflow: auto;
  flex: 1;
}

table {
  border-collapse: collapse;
  font-size: 13px;
  width: 100%;
}

th,
td {
  border-bottom: 1px solid #dfe4ea;
  max-width: 280px;
  overflow: hidden;
  padding: 8px 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

th {
  background: #eef2f6;
  cursor: pointer;
  position: sticky;
  text-align: left;
  top: 0;
}

tr.selected,
tbody tr:hover {
  background: #eef6ee;
}

.pager {
  align-items: center;
  background: #ffffff;
  border-top: 1px solid #d8dde3;
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 10px 18px;
}

.pager button,
.relation {
  border: 1px solid #b9c3cf;
  border-radius: 6px;
  background: #ffffff;
  cursor: pointer;
  padding: 7px 10px;
}

.detail-pane {
  border-left: 1px solid #d8dde3;
  overflow: auto;
  padding: 16px;
}

.detail-section {
  border-top: 1px solid #d8dde3;
  padding-top: 12px;
  margin-top: 12px;
}

dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

dt {
  color: #59636f;
  font-size: 12px;
}

dd {
  margin: 0;
  overflow-wrap: anywhere;
}

pre {
  background: #f4f6f8;
  border: 1px solid #d8dde3;
  border-radius: 6px;
  overflow: auto;
  padding: 10px;
}

.notice,
.empty {
  color: #59636f;
  padding: 18px;
}

.error {
  color: #b42318;
}

.relation {
  display: block;
  margin-bottom: 8px;
  text-align: left;
  width: 100%;
}
```

- [ ] **Step 5: Install frontend dependencies**

Run:

```bash
npm --prefix frontend install
```

Expected: dependencies install and `frontend/package-lock.json` is created.

- [ ] **Step 6: Build the Vue app**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS and `src/workscribe/explorer/static/index.html` plus hashed asset files are generated.

- [ ] **Step 7: Commit frontend source and built assets**

Run:

```bash
git add frontend src/workscribe/explorer/static
git commit -m "Add Vue explorer workbench"
```

## Task 5: Packaging and Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Add package-data configuration**

Modify `pyproject.toml` by appending:

```toml
[tool.setuptools.package-data]
"workscribe.explorer" = ["static/index.html", "static/assets/*"]
```

- [ ] **Step 2: Document the command**

Add this section to `README.md` after the Initial Workflow list:

````markdown
## Local Data Explorer

Run a read-only local web explorer for the collected SQLite data:

```text
workscribe explore --path .
```

The command discovers the nearest Workscribe program root, opens `.codex-workscribe.sqlite` in read-only mode, and serves a Vue workbench at a localhost URL. The explorer is for inspecting raw collection data while refining the tooling. It does not edit rows or export reports.
````

- [ ] **Step 3: Verify package data is included**

Run:

```bash
python -m build
```

Expected: PASS and the generated wheel includes files under `workscribe/explorer/static/`.

If `python -m build` fails because the `build` module is absent, run:

```bash
python -m pip install build
python -m build
```

- [ ] **Step 4: Run all backend tests**

Run:

```bash
python -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 5: Commit packaging and docs**

Run:

```bash
git add pyproject.toml README.md
git commit -m "Document and package explorer assets"
```

## Task 6: Local End-to-End Verification

**Files:**
- No required source changes unless verification finds a defect.

- [ ] **Step 1: Create a temporary Workscribe root**

Run:

```bash
tmpdir="$(mktemp -d)"
python -m workscribe init program --path "$tmpdir" --client-key acme --client-name Acme --program-name Acme
```

Expected: command prints paths for `.codex-workscribe.toml` and `.codex-workscribe.sqlite`.

- [ ] **Step 2: Launch explorer without opening a browser**

Run:

```bash
python -m workscribe explore --path "$tmpdir" --port 8765 --no-open
```

Expected: command prints `Serving Workscribe explorer at http://127.0.0.1:8765` and remains running.

- [ ] **Step 3: Verify API from another terminal**

Run:

```bash
curl -fsS http://127.0.0.1:8765/api/meta
```

Expected: JSON includes `"database_path"` and the `clients`, `projects`, and `sessions` table names.

- [ ] **Step 4: Verify the SPA in a browser**

Open:

```text
http://127.0.0.1:8765
```

Expected: the Workscribe Explorer loads, shows table navigation, displays empty or seeded rows, and selecting a row opens the detail panel.

- [ ] **Step 5: Stop the server**

Press `Ctrl-C` in the terminal running `workscribe explore`.

Expected: command exits cleanly after printing `Stopped Workscribe explorer`.

- [ ] **Step 6: Final status check**

Run:

```bash
git status --short
```

Expected: no uncommitted implementation changes except intentional local artifacts such as temporary databases or ignored directories.

## Self-Review

- Spec coverage: The plan implements `workscribe explore`, localhost serving, read-only SQLite access, the Vue Workbench layout, metadata/rows/detail endpoints, JSON formatting, relationship shortcuts, disabled Timeline navigation, no edit operations, and no export actions.
- Scope control: Timeline remains deferred. Authentication remains out of scope for the local-only release.
- Type consistency: Backend API response names used by the Vue app match the planned Python payloads: `tables`, `columns`, `count`, `rows`, `total`, `limit`, `offset`, `parsed_json`, and `related`.
