import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workscribe.db import initialize_database
from workscribe.explorer.server import ExplorerHTTPServer, ExplorerRequestHandler


class ExplorerServerTests(unittest.TestCase):
    def make_server(self, tmpdir: Path, *, include_index: bool = True) -> ExplorerHTTPServer:
        database_path = tmpdir / ".codex-workscribe.sqlite"
        with sqlite3.connect(database_path) as conn:
            conn.row_factory = sqlite3.Row
            initialize_database(conn)
            conn.execute(
                """
                INSERT INTO clients (id, client_key, name, created_at, updated_at)
                VALUES (1, 'acme', 'Acme', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')
                """
            )

        static_dir = tmpdir / "static"
        static_dir.mkdir()
        if include_index:
            (static_dir / "index.html").write_text("<html><body>Explorer</body></html>", encoding="utf-8")

        server = ExplorerHTTPServer.__new__(ExplorerHTTPServer)
        server.database_path = database_path.resolve()
        server.program_root = tmpdir.resolve()
        server.static_dir = static_dir.resolve()
        return server

    def dispatch_json(self, server: ExplorerHTTPServer, path: str) -> tuple[int, dict[str, str], dict]:
        status, headers, body = ExplorerRequestHandler.dispatch_for_test(server, path)
        return status, headers, json.loads(body.decode("utf-8"))

    def test_api_meta_returns_json_database_path_and_clients_table(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            tmpdir = Path(raw_tmpdir)
            server = self.make_server(tmpdir)

            status, headers, payload = self.dispatch_json(server, "/api/meta")

        self.assertEqual(200, status)
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertEqual(str((tmpdir / ".codex-workscribe.sqlite").resolve()), payload["database_path"])
        self.assertEqual(str(tmpdir.resolve()), payload["program_root"])
        self.assertIn("clients", payload["tables"])
        self.assertEqual(1, payload["counts"]["clients"])

    def test_table_rows_returns_seeded_acme_row_with_sort_params(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            server = self.make_server(Path(raw_tmpdir))

            status, headers, payload = self.dispatch_json(
                server,
                "/api/tables/clients/rows?sort=name&direction=asc&limit=5&offset=0",
            )

        self.assertEqual(200, status)
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertEqual("clients", payload["table"])
        self.assertEqual("name", payload["sort"])
        self.assertEqual("asc", payload["direction"])
        self.assertEqual([{"id": 1, "client_key": "acme", "name": "Acme"}], [
            {
                "id": row["id"],
                "client_key": row["client_key"],
                "name": row["name"],
            }
            for row in payload["rows"]
        ])

    def test_unknown_table_returns_400_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            server = self.make_server(Path(raw_tmpdir))

            status, headers, payload = self.dispatch_json(server, "/api/tables/not_real/rows")

        self.assertEqual(400, status)
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertIn("Unknown table", payload["error"])

    def test_static_root_serves_index_html(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            server = self.make_server(Path(raw_tmpdir))

            status, headers, body = ExplorerRequestHandler.dispatch_for_test(server, "/")

        self.assertEqual(200, status)
        self.assertEqual("text/html; charset=utf-8", headers["Content-Type"])
        self.assertEqual(b"<html><body>Explorer</body></html>", body)

    def test_missing_static_index_returns_500_json_for_non_api_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmpdir:
            server = self.make_server(Path(raw_tmpdir), include_index=False)

            status, headers, payload = self.dispatch_json(server, "/anything")

        self.assertEqual(500, status)
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertIn("Missing static asset", payload["error"])


if __name__ == "__main__":
    unittest.main()
