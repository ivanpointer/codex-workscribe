from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workscribe.config import WorkscribeError, discover_workspace, find_git_root
from workscribe.db import (
    connect_database,
    ensure_session,
    find_active_session_id,
    initialize_database,
    insert_commit,
    insert_config_snapshot,
    insert_prompt,
    insert_tool_event,
    record_session_activity,
    upsert_project_metadata,
    utc_now,
)


@dataclass(slots=True)
class MetadataContext:
    project_id: int
    repo_root: Path | None


def handle_codex_hook(stdin_text: str) -> int:
    payload = parse_json(stdin_text)
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    try:
        workspace = discover_workspace(cwd)
    except WorkscribeError as exc:
        if "No workscribe root found" in str(exc):
            return 0
        raise

    with connect_database(workspace.database_path) as conn:
        initialize_database(conn)
        metadata = sync_metadata(conn, workspace, cwd)
        event_name = payload.get("hook_event_name")
        if event_name == "SessionStart":
            record_session_start(conn, metadata, workspace, payload)
            return 0
        if event_name == "UserPromptSubmit":
            record_user_prompt(conn, metadata, workspace, payload)
            return 0
        if event_name == "PostToolUse":
            record_post_tool_use(conn, metadata, workspace, payload)
            return 0
        if event_name == "Stop":
            record_stop(conn, metadata, payload)
            sys.stdout.write("{}")
            return 0
        return 0


def handle_git_hook(hook_name: str) -> int:
    cwd = Path.cwd().resolve()
    try:
        workspace = discover_workspace(cwd)
    except WorkscribeError as exc:
        if "No workscribe root found" in str(exc):
            return 0
        raise
    git_root = find_git_root(cwd)
    if git_root is None:
        return 0

    with connect_database(workspace.database_path) as conn:
        initialize_database(conn)
        metadata = sync_metadata(conn, workspace, git_root)
        if hook_name == "post-commit":
            record_post_commit(conn, metadata, git_root)
        elif hook_name == "post-merge":
            # Reserved for future merge evidence; no-op for now.
            pass
    return 0


def parse_json(stdin_text: str) -> dict[str, Any]:
    if not stdin_text.strip():
        return {}
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        raise WorkscribeError(f"Failed to parse hook JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkscribeError("Hook payload must be a JSON object.")
    return payload


def sync_metadata(conn, workspace, repo_anchor: Path) -> MetadataContext:
    config = workspace.effective_config
    client_key = str(config.get("client_key") or workspace.program_root.name)
    client_name = str(config.get("client_name") or client_key)
    billing_mode = as_optional_str(config.get("billing_mode"))
    default_hourly_rate = as_optional_float(config.get("default_hourly_rate"))
    currency = as_optional_str(config.get("currency"))
    project_key = str(config.get("project_key") or repo_anchor.name)
    project_name = str(config.get("project_name") or project_key)
    timezone_name = as_optional_str((config.get("reporting") or {}).get("timezone"))
    tags = ensure_str_list(config.get("tags") or [])
    repo_root = find_git_root(repo_anchor) or repo_anchor

    project_id = upsert_project_metadata(
        conn,
        client_key=client_key,
        client_name=client_name,
        billing_mode=billing_mode,
        default_hourly_rate=default_hourly_rate,
        currency=currency,
        project_key=project_key,
        project_name=project_name,
        repo_root=str(repo_root),
        program_root=str(workspace.program_root),
        repo_config_path=str(workspace.repo_override_path) if workspace.repo_override_path else None,
        timezone_name=timezone_name,
        tags=tags,
    )
    insert_config_snapshot(
        conn,
        project_id=project_id,
        program_root=str(workspace.program_root),
        source_path=str(workspace.program_config_path),
        source_type="program-root",
        config=load_snapshot_config(workspace, include_repo=False),
    )
    if workspace.repo_override_path is not None:
        insert_config_snapshot(
            conn,
            project_id=project_id,
            program_root=str(workspace.program_root),
            source_path=str(workspace.repo_override_path),
            source_type="repo-override",
            config=load_snapshot_config(workspace, include_repo=True),
        )
    return MetadataContext(project_id=project_id, repo_root=repo_root)


def load_snapshot_config(workspace, *, include_repo: bool) -> dict[str, Any]:
    return workspace.effective_config


def record_session_start(conn, metadata: MetadataContext, workspace, payload: dict[str, Any]) -> None:
    observed_at = utc_now()
    ensure_session(
        conn,
        session_key=payload["session_id"],
        project_id=metadata.project_id,
        source=payload.get("source"),
        cwd=payload.get("cwd"),
        repo_root=str(metadata.repo_root) if metadata.repo_root else None,
        git_branch=current_git_branch(metadata.repo_root),
        model=payload.get("model"),
        transcript_path=payload.get("transcript_path"),
        tmux_session=os.environ.get("TMUX_WORKSCRIBE_SESSION") or os.environ.get("TMUX_SESSION"),
        tmux_pane=os.environ.get("TMUX_PANE"),
        cmux_workspace=os.environ.get("CMUX_WORKSPACE_ID"),
        cmux_surface=os.environ.get("CMUX_SURFACE_ID"),
        started_at=observed_at,
        status="active",
    )
    record_session_activity(conn, session_key=payload["session_id"], observed_at=observed_at)


def record_user_prompt(conn, metadata: MetadataContext, workspace, payload: dict[str, Any]) -> None:
    session_id = ensure_session(
        conn,
        session_key=payload["session_id"],
        project_id=metadata.project_id,
        source=None,
        cwd=payload.get("cwd"),
        repo_root=str(metadata.repo_root) if metadata.repo_root else None,
        git_branch=current_git_branch(metadata.repo_root),
        model=payload.get("model"),
        transcript_path=payload.get("transcript_path"),
        tmux_session=os.environ.get("TMUX_WORKSCRIBE_SESSION") or os.environ.get("TMUX_SESSION"),
        tmux_pane=os.environ.get("TMUX_PANE"),
        cmux_workspace=os.environ.get("CMUX_WORKSPACE_ID"),
        cmux_surface=os.environ.get("CMUX_SURFACE_ID"),
        status="active",
    )
    observed_at = utc_now()
    insert_prompt(
        conn,
        session_id=session_id,
        submitted_at=observed_at,
        prompt_text=str(payload.get("prompt") or ""),
    )
    record_session_activity(conn, session_key=payload["session_id"], observed_at=observed_at)


def record_post_tool_use(conn, metadata: MetadataContext, workspace, payload: dict[str, Any]) -> None:
    session_id = ensure_session(
        conn,
        session_key=payload["session_id"],
        project_id=metadata.project_id,
        source=None,
        cwd=payload.get("cwd"),
        repo_root=str(metadata.repo_root) if metadata.repo_root else None,
        git_branch=current_git_branch(metadata.repo_root),
        model=payload.get("model"),
        transcript_path=payload.get("transcript_path"),
        tmux_session=os.environ.get("TMUX_WORKSCRIBE_SESSION") or os.environ.get("TMUX_SESSION"),
        tmux_pane=os.environ.get("TMUX_PANE"),
        cmux_workspace=os.environ.get("CMUX_WORKSPACE_ID"),
        cmux_surface=os.environ.get("CMUX_SURFACE_ID"),
        status="active",
    )
    observed_at = utc_now()
    insert_tool_event(
        conn,
        session_id=session_id,
        turn_id=as_optional_str(payload.get("turn_id")),
        event_name="PostToolUse",
        tool_name=as_optional_str(payload.get("tool_name")),
        tool_input=payload.get("tool_input"),
        tool_response=payload.get("tool_response"),
        captured_at=observed_at,
    )
    record_session_activity(conn, session_key=payload["session_id"], observed_at=observed_at)


def record_stop(conn, metadata: MetadataContext, payload: dict[str, Any]) -> None:
    # Codex emits Stop after each completed turn, so treating it as a terminal
    # session boundary corrupts session state. Treat it as observed activity
    # only for older hook installations that still emit Workscribe Stop hooks.
    _ = metadata
    session_key = payload.get("session_id")
    if session_key:
        record_session_activity(conn, session_key=session_key, observed_at=utc_now())


def record_post_commit(conn, metadata: MetadataContext, git_root: Path) -> None:
    commit_sha = git_capture(git_root, ["rev-parse", "HEAD"])
    branch = git_capture(git_root, ["branch", "--show-current"])
    show_output = git_capture(
        git_root,
        ["show", "--quiet", "--format=%aN%x00%aE%x00%cI%x00%s%x00%b", commit_sha],
    )
    author_name, author_email, committed_at, subject, body = split_nul_fields(show_output, 5)

    numstat_output = git_capture(git_root, ["show", "--numstat", "--format=", "--no-renames", commit_sha])
    changed_files: list[str] = []
    insertions = 0
    deletions = 0
    for line in numstat_output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        changed_files.append(path)
        if added.isdigit():
            insertions += int(added)
        if removed.isdigit():
            deletions += int(removed)

    session_id = find_active_session_id(conn, metadata.project_id)
    insert_commit(
        conn,
        project_id=metadata.project_id,
        session_id=session_id,
        commit_sha=commit_sha,
        git_branch=branch or None,
        author_name=author_name or None,
        author_email=author_email or None,
        committed_at=committed_at or utc_now(),
        subject=subject,
        body=body,
        changed_files=changed_files,
        insertions=insertions,
        deletions=deletions,
    )


def git_capture(repo_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.rstrip("\n")


def current_git_branch(repo_root: Path | None) -> str | None:
    if repo_root is None:
        return None
    try:
        value = git_capture(repo_root, ["branch", "--show-current"])
    except Exception:
        return None
    return value or None


def split_nul_fields(value: str, expected: int) -> list[str]:
    parts = value.split("\x00")
    if len(parts) < expected:
        parts.extend([""] * (expected - len(parts)))
    return parts[:expected]


def ensure_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
