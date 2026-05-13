import sqlite3
import unittest

from workscribe.db import initialize_database
from workscribe.explorer import data as explorer_data
from workscribe.explorer.data import (
    ExplorerQueryError,
    WORKSCRIBE_TABLES,
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
            self.seed_client_project_session_rows(conn)

            metadata = get_table_metadata(conn)

        sessions = next(table for table in metadata if table["name"] == "sessions")
        projects = next(table for table in metadata if table["name"] == "projects")

        self.assertEqual(list(WORKSCRIBE_TABLES), [table["name"] for table in metadata])
        self.assertEqual(3, sessions["count"])
        self.assertEqual(2, projects["count"])
        self.assertEqual({"name", "type", "primary_key"}, set(sessions["columns"][0].keys()))
        self.assertIn("session_key", [column["name"] for column in sessions["columns"]])
        self.assertEqual(["id"], sessions["primary_key"])
        session_key_column = next(column for column in sessions["columns"] if column["name"] == "session_key")
        self.assertEqual({"name": "session_key", "type": "TEXT", "primary_key": False}, session_key_column)
        self.assertEqual({"column", "references_table", "references_column"}, set(sessions["foreign_keys"][0].keys()))
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

    def test_list_rows_clamps_limit_offset_and_normalizes_non_asc_direction(self) -> None:
        with self.make_db() as conn:
            self.seed_client_project_session_rows(conn)

            low_limit = list_rows(conn, "sessions", limit=0)
            high_limit = list_rows(conn, "sessions", limit=999)
            negative_offset = list_rows(conn, "sessions", offset=-20)
            weird_direction = list_rows(conn, "sessions", sort="created_at", direction="sideways")

        self.assertEqual(1, low_limit["limit"])
        self.assertEqual(1, len(low_limit["rows"]))
        self.assertEqual(200, high_limit["limit"])
        self.assertEqual(0, negative_offset["offset"])
        self.assertEqual("desc", weird_direction["direction"])
        self.assertEqual(["sess-beta-1", "sess-alpha-2", "sess-alpha-1"], [row["session_key"] for row in weird_direction["rows"]])

    def test_list_rows_rejects_unknown_table_sort_column_and_filter_column(self) -> None:
        with self.make_db() as conn:
            with self.assertRaises(ExplorerQueryError):
                list_rows(conn, "sqlite_master")

            with self.assertRaisesRegex(ExplorerQueryError, "Unknown column"):
                list_rows(conn, "sessions", sort="missing")

            with self.assertRaisesRegex(ExplorerQueryError, "Unknown column"):
                list_rows(conn, "sessions", filters={"missing": "value"})

    def test_list_rows_quotes_schema_derived_column_names_with_embedded_double_quotes(self) -> None:
        with self.make_db() as conn:
            conn.execute('CREATE TABLE odd_columns (id INTEGER PRIMARY KEY, "strange""name" TEXT NOT NULL)')
            conn.execute('INSERT INTO odd_columns (id, "strange""name") VALUES (1, ?)', ("needle",))

            original_tables = explorer_data.WORKSCRIBE_TABLES
            explorer_data.WORKSCRIBE_TABLES = (*original_tables, "odd_columns")
            try:
                result = list_rows(
                    conn,
                    "odd_columns",
                    sort='strange"name',
                    search="needle",
                    filters={'strange"name': "need"},
                )
            finally:
                explorer_data.WORKSCRIBE_TABLES = original_tables

        self.assertEqual(1, result["total"])
        self.assertEqual("needle", result["rows"][0]['strange"name'])

    def test_get_row_detail_parses_projects_tags_json_and_finds_sessions_related_by_project_id(self) -> None:
        with self.make_db() as conn:
            self.seed_client_project_session_rows(conn)
            conn.execute(
                """
                INSERT INTO installations (
                    id, program_root, install_scope, codex_hooks_enabled, git_hooks_enabled,
                    installed_at, updated_at, notes_json
                )
                VALUES (
                    1, '/tmp/alpha', 'repo', 1, 0,
                    '2026-01-10T00:00:00Z', '2026-01-10T00:00:00Z',
                    '{"installed_by": "test"}'
                )
                """
            )

            detail = get_row_detail(conn, "projects", 1)
            invalid_json_detail = get_row_detail(conn, "projects", 2)
            notes_detail = get_row_detail(conn, "installations", 1)

        self.assertEqual("projects", detail["table"])
        self.assertEqual("Alpha Project", detail["row"]["name"])
        self.assertEqual({"tags_json": ["alpha", "billable"]}, detail["parsed_json"])
        self.assertEqual({}, invalid_json_detail["parsed_json"])
        self.assertEqual({"notes_json": {"installed_by": "test"}}, notes_detail["parsed_json"])
        self.assertIn(
            {"table": "sessions", "column": "project_id", "value": 1, "count": 2},
            detail["related"],
        )

    def test_get_row_detail_rejects_unknown_table_missing_row_and_tables_without_id(self) -> None:
        with self.make_db() as conn:
            self.seed_client_project_session_rows(conn)
            conn.execute("CREATE TABLE no_id (name TEXT NOT NULL)")

            with self.assertRaises(ExplorerQueryError):
                get_row_detail(conn, "sqlite_master", 1)

            with self.assertRaises(ExplorerQueryError):
                get_row_detail(conn, "projects", 999)

            original_tables = explorer_data.WORKSCRIBE_TABLES
            explorer_data.WORKSCRIBE_TABLES = (*original_tables, "no_id")
            try:
                with self.assertRaises(ExplorerQueryError):
                    get_row_detail(conn, "no_id", 1)
            finally:
                explorer_data.WORKSCRIBE_TABLES = original_tables


if __name__ == "__main__":
    unittest.main()
