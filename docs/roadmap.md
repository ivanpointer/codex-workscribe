# Roadmap

## Phase 0: Design Baseline

- define config format
- define SQLite schema
- define hook event handling contract
- define first report outputs

## Phase 1: Local Ledger

- implement config loader
- implement root discovery by walking parent directories
- initialize SQLite database
- implement `init` command for program-root and repo-local setup
- implement `init project` alias for repo-local project metadata
- implement `install-global` and `uninstall-global`
- implement `install` and `uninstall` commands for hook wiring
- implement Codex hook handlers
- implement Git hook recorder
- support manual report generation from stored data
- generate Markdown, JSON, CSV, and SVG report artifacts

## Phase 2: Report Quality

- generate internal weekly ledger summaries
- generate client-facing status summaries
- add traditional-effort estimation rubric
- add confidence and evidence scoring

## Phase 3: Ergonomics

- optional tmux/cmux context capture
- idle-gap heuristics for active-time estimation

## Phase 4: Integrations

- CSV export
- JSON export
- optional Google Sheets or Excel export
- optional invoice system adapters
