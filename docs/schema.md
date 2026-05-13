# Schema

## Overview

The schema should preserve raw evidence and support later summarization.

## Proposed Tables

### `clients`

- `id`
- `client_key`
- `name`
- `billing_mode`
- `default_hourly_rate`
- `currency`
- `created_at`
- `updated_at`

### `projects`

- `id`
- `project_key`
- `client_id`
- `name`
- `repo_root`
- `program_root`
- `repo_config_path`
- `timezone`
- `tags_json`
- `created_at`
- `updated_at`

### `config_snapshots`

- `id`
- `project_id`
- `program_root`
- `source_path`
- `source_type`
- `config_json`
- `captured_at`

### `installations`

- `id`
- `program_root`
- `repo_root`
- `install_scope`
- `codex_hooks_enabled`
- `git_hooks_enabled`
- `installed_at`
- `updated_at`
- `notes_json`

### `sessions`

- `id`
- `session_key`
- `project_id`
- `source`
- `cwd`
- `repo_root`
- `git_branch`
- `started_at`
- `ended_at`
- `elapsed_seconds`
- `model`
- `transcript_path`
- `tmux_session`
- `tmux_pane`
- `cmux_workspace`
- `cmux_surface`
- `status`
- `created_at`
- `updated_at`

### `prompts`

- `id`
- `session_id`
- `prompt_index`
- `submitted_at`
- `prompt_text`
- `prompt_summary`

### `tool_events`

- `id`
- `session_id`
- `turn_id`
- `sequence_no`
- `event_name`
- `tool_name`
- `tool_input_json`
- `tool_response_json`
- `captured_at`

### `notes`

- `id`
- `project_id`
- `session_id`
- `note_type`
- `created_at`
- `content`
- `content_summary`
- `metadata_json`

### `commits`

- `id`
- `project_id`
- `session_id`
- `commit_sha`
- `git_branch`
- `author_name`
- `author_email`
- `committed_at`
- `subject`
- `body`
- `changed_files_json`
- `insertions`
- `deletions`

### `reports`

- `id`
- `project_id`
- `range_start`
- `range_end`
- `report_type`
- `generated_at`
- `input_session_ids_json`
- `input_commit_ids_json`
- `report_markdown`
- `report_json`

## Notes

- JSON columns should be serialized as text in SQLite.
- `prompt_text` may need optional redaction or summarization controls later.
- `session_id` on commits is best-effort and may be null when work happened outside a tracked session.
- Derived billing values should be generated in reports first, not stored as immutable facts in raw session rows.
- Install state in SQLite is advisory; on-disk hook files remain the operational source of truth.
