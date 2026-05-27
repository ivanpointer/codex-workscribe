from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest
from unittest.mock import patch

from workscribe.db import connect_database, initialize_database, utc_now
from workscribe.hooks import handle_codex_hook
from workscribe.reporting import build_report_payload, fetch_report_data, parse_report_window


class SessionActivityTests(unittest.TestCase):
    def test_prompt_and_tool_events_update_active_session_observed_elapsed_time(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".codex-workscribe.toml").write_text(
                'client_key = "acme"\n'
                'client_name = "Acme"\n'
                'currency = "USD"\n'
            )
            with connect_database(root / ".codex-workscribe.sqlite") as conn:
                initialize_database(conn)

            with patch("workscribe.hooks.utc_now", side_effect=[
                "2026-05-27T10:00:00+00:00",
                "2026-05-27T10:05:00+00:00",
                "2026-05-27T10:45:00+00:00",
            ]):
                handle_codex_hook(json.dumps({
                    "hook_event_name": "SessionStart",
                    "session_id": "session-a",
                    "cwd": str(root),
                    "source": "codex",
                }))
                handle_codex_hook(json.dumps({
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-a",
                    "cwd": str(root),
                    "prompt": "do useful work",
                }))
                handle_codex_hook(json.dumps({
                    "hook_event_name": "PostToolUse",
                    "session_id": "session-a",
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"cmd": "true"},
                    "tool_response": {"status": 0},
                }))

            conn = sqlite3.connect(root / ".codex-workscribe.sqlite")
            conn.row_factory = sqlite3.Row
            session = conn.execute("SELECT status, ended_at, elapsed_seconds FROM sessions").fetchone()
            conn.close()

            self.assertEqual("active", session["status"])
            self.assertEqual("2026-05-27T10:45:00+00:00", session["ended_at"])
            self.assertEqual(2700, session["elapsed_seconds"])

    def test_report_uses_observed_prompt_and_tool_span_when_session_elapsed_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / ".codex-workscribe.sqlite"
            with connect_database(db_path) as conn:
                initialize_database(conn)
                conn.execute(
                    """
                    INSERT INTO clients (id, client_key, name, created_at, updated_at)
                    VALUES (1, 'acme', 'Acme', ?, ?)
                    """,
                    (utc_now(), utc_now()),
                )
                conn.execute(
                    """
                    INSERT INTO projects (id, project_key, client_id, name, program_root, created_at, updated_at)
                    VALUES (1, 'app', 1, 'App', ?, ?, ?)
                    """,
                    (str(root), utc_now(), utc_now()),
                )
                conn.execute(
                    """
                    INSERT INTO sessions (
                        id, session_key, project_id, started_at, status, created_at, updated_at
                    ) VALUES (1, 'session-a', 1, '2026-05-27T10:00:00+00:00', 'active', ?, ?)
                    """,
                    (utc_now(), utc_now()),
                )
                conn.execute(
                    """
                    INSERT INTO prompts (session_id, prompt_index, submitted_at, prompt_text)
                    VALUES (1, 1, '2026-05-27T10:10:00+00:00', 'start')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO tool_events (session_id, sequence_no, event_name, tool_name, captured_at)
                    VALUES (1, 1, 'PostToolUse', 'Bash', '2026-05-27T10:40:00+00:00')
                    """
                )

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            window = parse_report_window(start_text="2026-05-27", end_text="2026-05-27", days=None)
            data = fetch_report_data(conn, 1, window)
            payload = build_report_payload(data)
            conn.close()

            self.assertEqual(0.5, payload["summary"]["elapsed_hours"])
            self.assertEqual(30, payload["metrics"]["daily_activity_minutes"][0]["elapsed_minutes"])


if __name__ == "__main__":
    unittest.main()
