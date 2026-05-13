from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    client_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    billing_mode TEXT,
    default_hourly_rate REAL,
    currency TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    project_key TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    name TEXT NOT NULL,
    repo_root TEXT,
    program_root TEXT,
    repo_config_path TEXT,
    timezone TEXT,
    tags_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_snapshots (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    program_root TEXT,
    source_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    config_json TEXT NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    session_key TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    source TEXT,
    cwd TEXT,
    repo_root TEXT,
    git_branch TEXT,
    started_at TEXT,
    ended_at TEXT,
    elapsed_seconds INTEGER,
    model TEXT,
    transcript_path TEXT,
    tmux_session TEXT,
    tmux_pane TEXT,
    cmux_workspace TEXT,
    cmux_surface TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    prompt_index INTEGER NOT NULL,
    submitted_at TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    prompt_summary TEXT
);

CREATE TABLE IF NOT EXISTS tool_events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    turn_id TEXT,
    sequence_no INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    tool_name TEXT,
    tool_input_json TEXT,
    tool_response_json TEXT,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    session_id INTEGER REFERENCES sessions(id),
    note_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    content TEXT NOT NULL,
    content_summary TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS commits (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    session_id INTEGER REFERENCES sessions(id),
    commit_sha TEXT NOT NULL UNIQUE,
    git_branch TEXT,
    author_name TEXT,
    author_email TEXT,
    committed_at TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    changed_files_json TEXT,
    insertions INTEGER,
    deletions INTEGER
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    range_start TEXT NOT NULL,
    range_end TEXT NOT NULL,
    report_type TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    input_session_ids_json TEXT,
    input_commit_ids_json TEXT,
    report_markdown TEXT,
    report_json TEXT
);

CREATE TABLE IF NOT EXISTS installations (
    id INTEGER PRIMARY KEY,
    program_root TEXT NOT NULL,
    repo_root TEXT,
    install_scope TEXT NOT NULL,
    codex_hooks_enabled INTEGER NOT NULL,
    git_hooks_enabled INTEGER NOT NULL,
    installed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes_json TEXT
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect_database(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def upsert_project_metadata(
    conn: sqlite3.Connection,
    *,
    client_key: str,
    client_name: str,
    billing_mode: str | None,
    default_hourly_rate: float | None,
    currency: str | None,
    project_key: str,
    project_name: str,
    repo_root: str | None,
    program_root: str,
    repo_config_path: str | None,
    timezone_name: str | None,
    tags: list[str],
) -> int:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO clients (client_key, name, billing_mode, default_hourly_rate, currency, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_key) DO UPDATE SET
            name=excluded.name,
            billing_mode=excluded.billing_mode,
            default_hourly_rate=excluded.default_hourly_rate,
            currency=excluded.currency,
            updated_at=excluded.updated_at
        """,
        (client_key, client_name, billing_mode, default_hourly_rate, currency, now, now),
    )
    client_id = conn.execute(
        "SELECT id FROM clients WHERE client_key = ?",
        (client_key,),
    ).fetchone()["id"]

    conn.execute(
        """
        INSERT INTO projects (
            project_key, client_id, name, repo_root, program_root, repo_config_path, timezone, tags_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_key) DO UPDATE SET
            client_id=excluded.client_id,
            name=excluded.name,
            repo_root=excluded.repo_root,
            program_root=excluded.program_root,
            repo_config_path=excluded.repo_config_path,
            timezone=excluded.timezone,
            tags_json=excluded.tags_json,
            updated_at=excluded.updated_at
        """,
        (
            project_key,
            client_id,
            project_name,
            repo_root,
            program_root,
            repo_config_path,
            timezone_name,
            json.dumps(tags),
            now,
            now,
        ),
    )
    project_id = conn.execute(
        "SELECT id FROM projects WHERE project_key = ?",
        (project_key,),
    ).fetchone()["id"]
    return int(project_id)


def insert_config_snapshot(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    program_root: str,
    source_path: str,
    source_type: str,
    config: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO config_snapshots (project_id, program_root, source_path, source_type, config_json, captured_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, program_root, source_path, source_type, json.dumps(config, sort_keys=True), utc_now()),
    )


def ensure_session(
    conn: sqlite3.Connection,
    *,
    session_key: str,
    project_id: int,
    source: str | None,
    cwd: str | None,
    repo_root: str | None,
    git_branch: str | None,
    model: str | None,
    transcript_path: str | None,
    tmux_session: str | None,
    tmux_pane: str | None,
    cmux_workspace: str | None,
    cmux_surface: str | None,
    started_at: str | None = None,
    status: str = "active",
) -> int:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO sessions (
            session_key, project_id, source, cwd, repo_root, git_branch, started_at, model, transcript_path,
            tmux_session, tmux_pane, cmux_workspace, cmux_surface, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_key) DO UPDATE SET
            project_id=excluded.project_id,
            source=COALESCE(excluded.source, sessions.source),
            cwd=COALESCE(excluded.cwd, sessions.cwd),
            repo_root=COALESCE(excluded.repo_root, sessions.repo_root),
            git_branch=COALESCE(excluded.git_branch, sessions.git_branch),
            started_at=COALESCE(sessions.started_at, excluded.started_at),
            model=COALESCE(excluded.model, sessions.model),
            transcript_path=COALESCE(excluded.transcript_path, sessions.transcript_path),
            tmux_session=COALESCE(excluded.tmux_session, sessions.tmux_session),
            tmux_pane=COALESCE(excluded.tmux_pane, sessions.tmux_pane),
            cmux_workspace=COALESCE(excluded.cmux_workspace, sessions.cmux_workspace),
            cmux_surface=COALESCE(excluded.cmux_surface, sessions.cmux_surface),
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (
            session_key,
            project_id,
            source,
            cwd,
            repo_root,
            git_branch,
            started_at,
            model,
            transcript_path,
            tmux_session,
            tmux_pane,
            cmux_workspace,
            cmux_surface,
            status,
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM sessions WHERE session_key = ?",
        (session_key,),
    ).fetchone()
    return int(row["id"])


def finalize_session(conn: sqlite3.Connection, *, session_key: str, ended_at: str) -> None:
    row = conn.execute(
        "SELECT started_at FROM sessions WHERE session_key = ?",
        (session_key,),
    ).fetchone()
    elapsed_seconds = None
    if row and row["started_at"]:
        start_dt = datetime.fromisoformat(row["started_at"])
        end_dt = datetime.fromisoformat(ended_at)
        elapsed_seconds = max(0, int((end_dt - start_dt).total_seconds()))
    conn.execute(
        """
        UPDATE sessions
        SET ended_at = ?, elapsed_seconds = ?, status = ?, updated_at = ?
        WHERE session_key = ?
        """,
        (ended_at, elapsed_seconds, "stopped", utc_now(), session_key),
    )


def next_prompt_index(conn: sqlite3.Connection, session_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(prompt_index), 0) + 1 AS next_index FROM prompts WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["next_index"])


def insert_prompt(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    submitted_at: str,
    prompt_text: str,
) -> None:
    conn.execute(
        """
        INSERT INTO prompts (session_id, prompt_index, submitted_at, prompt_text, prompt_summary)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, next_prompt_index(conn, session_id), submitted_at, prompt_text, summarize_text(prompt_text)),
    )


def next_tool_sequence(conn: sqlite3.Connection, session_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence FROM tool_events WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["next_sequence"])


def insert_tool_event(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    turn_id: str | None,
    event_name: str,
    tool_name: str | None,
    tool_input: Any,
    tool_response: Any,
    captured_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO tool_events (
            session_id, turn_id, sequence_no, event_name, tool_name, tool_input_json, tool_response_json, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            turn_id,
            next_tool_sequence(conn, session_id),
            event_name,
            tool_name,
            json.dumps(tool_input, sort_keys=True) if tool_input is not None else None,
            json.dumps(tool_response, sort_keys=True) if tool_response is not None else None,
            captured_at,
        ),
    )


def find_active_session_id(conn: sqlite3.Connection, project_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM sessions
        WHERE project_id = ? AND status = 'active'
        ORDER BY COALESCE(started_at, created_at) DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def find_active_session(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM sessions
        WHERE project_id = ? AND status = 'active'
        ORDER BY COALESCE(started_at, created_at) DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()


def find_session_by_key(conn: sqlite3.Connection, session_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sessions WHERE session_key = ?",
        (session_key,),
    ).fetchone()


def find_latest_session(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM sessions
        WHERE project_id = ?
        ORDER BY COALESCE(started_at, created_at) DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()


def insert_commit(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    session_id: int | None,
    commit_sha: str,
    git_branch: str | None,
    author_name: str | None,
    author_email: str | None,
    committed_at: str,
    subject: str,
    body: str,
    changed_files: list[str],
    insertions: int,
    deletions: int,
) -> None:
    conn.execute(
        """
        INSERT INTO commits (
            project_id, session_id, commit_sha, git_branch, author_name, author_email, committed_at, subject, body,
            changed_files_json, insertions, deletions
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(commit_sha) DO UPDATE SET
            session_id=COALESCE(excluded.session_id, commits.session_id),
            git_branch=excluded.git_branch,
            author_name=excluded.author_name,
            author_email=excluded.author_email,
            committed_at=excluded.committed_at,
            subject=excluded.subject,
            body=excluded.body,
            changed_files_json=excluded.changed_files_json,
            insertions=excluded.insertions,
            deletions=excluded.deletions
        """,
        (
            project_id,
            session_id,
            commit_sha,
            git_branch,
            author_name,
            author_email,
            committed_at,
            subject,
            body,
            json.dumps(changed_files),
            insertions,
            deletions,
        ),
    )


def insert_note(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    session_id: int | None,
    note_type: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO notes (project_id, session_id, note_type, created_at, content, content_summary, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            session_id,
            note_type,
            utc_now(),
            content,
            summarize_text(content),
            json.dumps(metadata or {}, sort_keys=True),
        ),
    )


def record_installation(
    conn: sqlite3.Connection,
    *,
    program_root: str,
    repo_root: str | None,
    install_scope: str,
    codex_hooks_enabled: bool,
    git_hooks_enabled: bool,
    notes: dict[str, Any] | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO installations (
            program_root, repo_root, install_scope, codex_hooks_enabled, git_hooks_enabled, installed_at, updated_at, notes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            program_root,
            repo_root,
            install_scope,
            int(codex_hooks_enabled),
            int(git_hooks_enabled),
            now,
            now,
            json.dumps(notes or {}, sort_keys=True),
        ),
    )


def summarize_text(value: str, limit: int = 140) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
