import sqlite3
import unittest

from workscribe.db import initialize_database
from workscribe.explorer.data import (
    ExplorerQueryError,
    get_row_detail,
    get_table_metadata,
    list_rows,
)


class ExplorerDataTests(unittest.TestCase):
    def make_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize_database(conn)
        return conn

    def seed_client_project_session_rows(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        conn.execute(
            """
            INSERT INTO clients (id, client_key, name, created_at, updated_at)
            VALUES (1, 'acme', 'Acme', '2026-01-01T00:00:00Z', '2026-01-03T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO clients (id, client_key, name, created_at, updated_at)
            VALUES (2, 'beta', 'Beta', '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO projects (
                id, project_key, client_id, name, program_root, tags_json, created_at, updated_at
            )
            VALUES (
                1, 'alpha', 1, 'Alpha Project', '/tmp/alpha', '["alpha", "billable"]',
                '2026-01-01T00:00:00Z', '2026-01-05T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO projects (
                id, project_key, client_id, name, program_root, tags_json, created_at, updated_at
            )
            VALUES (
                2, 'beta', 2, 'Beta Project', '/tmp/beta', 'not-json',
                '2026-01-02T00:00:00Z', '2026-01-04T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (
                id, session_key, project_id, source, cwd, status, created_at, updated_at
            )
            VALUES (
                1, 'sess-alpha-1', 1, 'codex', '/tmp/alpha', 'complete',
                '2026-01-06T00:00:00Z', '2026-01-06T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (
                id, session_key, project_id, source, cwd, status, created_at, updated_at
            )
            VALUES (
                2, 'sess-alpha-2', 1, 'codex', '/tmp/alpha/docs', 'active',
                '2026-01-07T00:00:00Z', '2026-01-08T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (
                id, session_key, project_id, source, cwd, status, created_at, updated_at
            )
            VALUES (
                3, 'sess-beta-1', 2, 'cli', '/tmp/beta', 'complete',
                '2026-01-09T00:00:00Z', '2026-01-09T00:00:00Z'
            )
            """
        )
        conn.commit()
        return 1, 1, 1

    def test_metadata_lists_sessions_and_session_key_and_primary_key_id(self) -> None:
        with self.make_db() as conn:
            metadata = get_table_metadata(conn)

        sessions = next(table for table in metadata if table["name"] == "sessions")

        self.assertIn("sessions", [table["name"] for table in metadata])
        self.assertIn("session_key", [column["name"] for column in sessions["columns"]])
        self.assertEqual(["id"], sessions["primary_key"])
        self.assertIn(
            {"column": "project_id", "references_table": "projects", "references_column": "id"},
            sessions["foreign_keys"],
        )

    def test_metadata_rejects_empty_sqlite_db(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            with self.assertRaisesRegex(ExplorerQueryError, "not a Workscribe database"):
                get_table_metadata(conn)

    def test_list_rows_supports_pagination_search_sort_and_filter(self) -> None:
        with self.make_db() as conn:
            self.seed_client_project_session_rows(conn)

            first_page = list_rows(conn, "sessions", limit=2, offset=0)
            second_page = list_rows(conn, "sessions", limit=2, offset=2)
            searched = list_rows(conn, "sessions", search="docs", sort="created_at", direction="asc")
            filtered = list_rows(
                conn,
                "sessions",
                sort="created_at",
                direction="asc",
                filters={"status": "complete", "source": "codex"},
            )

        self.assertEqual(["sess-beta-1", "sess-alpha-2"], [row["session_key"] for row in first_page["rows"]])
        self.assertEqual(["sess-alpha-1"], [row["session_key"] for row in second_page["rows"]])
        self.assertEqual(3, first_page["total"])
        self.assertEqual(2, first_page["limit"])
        self.assertEqual(0, first_page["offset"])
        self.assertEqual("updated_at", first_page["sort"])
        self.assertEqual("desc", first_page["direction"])
        self.assertEqual(["sess-alpha-2"], [row["session_key"] for row in searched["rows"]])
        self.assertEqual(["sess-alpha-1"], [row["session_key"] for row in filtered["rows"]])

    def test_list_rows_rejects_unknown_table_and_unknown_sort_column(self) -> None:
        with self.make_db() as conn:
            with self.assertRaises(ExplorerQueryError):
                list_rows(conn, "sqlite_master")

            with self.assertRaisesRegex(ExplorerQueryError, "Unknown column"):
                list_rows(conn, "sessions", sort="missing")

    def test_get_row_detail_parses_projects_tags_json_and_finds_sessions_related_by_project_id(self) -> None:
        with self.make_db() as conn:
            self.seed_client_project_session_rows(conn)

            detail = get_row_detail(conn, "projects", 1)

        self.assertEqual("projects", detail["table"])
        self.assertEqual("Alpha Project", detail["row"]["name"])
        self.assertEqual({"tags_json": ["alpha", "billable"]}, detail["parsed_json"])
        self.assertIn(
            {"table": "sessions", "column": "project_id", "value": 1, "count": 2},
            detail["related"],
        )


if __name__ == "__main__":
    unittest.main()
