# Architecture

## Goal

Provide a local, defensible work ledger for agent-assisted software delivery that supports:

- 1099 billing
- client work summaries
- later invoice preparation
- internal comparison of elapsed time vs. traditional effort

## Design Principles

1. Capture facts early, summarize later.
2. Prefer append-only telemetry over mutable notes.
3. Keep billing metadata easy to edit by hand.
4. Avoid coupling to undocumented Codex internals when hooks can provide stable event data.
5. Keep generated client-facing language separate from raw evidence.

## Primary Inputs

### 1. Codex hooks

Codex hooks are the main source for session telemetry:

- `SessionStart`
- `UserPromptSubmit`
- `PostToolUse`
- `Stop`

These events provide the backbone for:

- session lifecycle
- user task intent
- tool execution evidence
- transcript linkage

### 2. Git hooks

Git hooks provide work-product evidence:

- `post-commit`
- optional `post-merge`

These events provide:

- commit SHA
- branch
- commit message
- changed files
- diff stats

### 3. Config files

Human-maintained config defines:

- client identity
- engagement/project identity
- billing defaults
- reporting preferences

## Installation Model

The system needs explicit setup commands instead of manual file copying.

### Planned commands

- `workscribe init`
- `workscribe install-global`
- `workscribe uninstall-global`
- `workscribe install`
- `workscribe uninstall`

### `init`

`init` should support two scopes:

- program-root initialization
- repo-local project initialization

Program-root initialization is responsible for creating:

- `ROOT/.codex-workscribe.toml`
- `ROOT/.codex-workscribe.sqlite`

Repo-local project initialization is responsible for creating:

- `REPO/.codex-workscribe.toml`

`init` should be idempotent and should not overwrite existing config without explicit intent.

### `install-global`

`install-global` is the preferred long-term setup model.

It should:

- install global Codex hooks in the user Codex home
- install global Git hooks via global `core.hooksPath`
- make hooks safe to leave enabled by no-oping outside configured workscribe roots

With this model, newly cloned repos under an existing tracked root should begin logging automatically without another per-repo hook install step.

### `install`

`install` should:

- install or update Codex hook configuration
- install or update Git hook shims
- preserve existing non-workscribe hook behavior where practical
- avoid destructive replacement of user-managed hook logic

This is a fallback mode for environments where global hooks are not acceptable.

### `uninstall`

`uninstall` should:

- remove workscribe-managed hook wiring
- leave telemetry data intact by default
- avoid removing unrelated hook logic

## Storage Strategy

### Authoritative metadata

- Program root config: `ROOT/.codex-workscribe.toml`
- Repo override config: `REPO/.codex-workscribe.toml`

These files are the human-editable source of truth.

This supports:

- one database per client or program root
- multiple projects under the same client root
- shared reporting across many repos without scanning the filesystem at report time

### Telemetry store

- Program root database: `ROOT/.codex-workscribe.sqlite`

The database stores:

- normalized metadata snapshots
- sessions
- prompts
- tool events
- git evidence
- generated reports

## Config Resolution

Effective configuration is resolved in this order:

1. built-in defaults
2. program-root TOML
3. repo-local TOML
4. explicit CLI overrides

Resolved metadata is upserted into SQLite before telemetry is written.

## Root Discovery

Hooks and CLI commands must be able to run from nested working directories.

Root discovery should work by starting from the current working directory and walking parent directories upward until finding a configured workscribe root.

A directory qualifies as a configured workscribe root when it contains:

- `.codex-workscribe.toml`
- `.codex-workscribe.sqlite`

This allows:

- running from subdirectories inside a repository
- multiple repositories sharing one program root
- repo-local override files without moving the shared database

If no configured root is found, the command should fail clearly and suggest running `workscribe init`.

Repo-local overrides should be discovered separately while walking upward from the current directory to the repo root.

Global Git and Codex hooks should rely on this discovery behavior so they can run everywhere and only activate inside tracked roots.

## Session Model

A session is the primary unit of work capture.

It should include:

- stable session identifier
- repo and cwd context
- start and stop timestamps
- model and source metadata
- optional workspace identifiers from tmux or cmux if available

Not every session becomes a client-facing line item. Reports can group multiple sessions into one billing entry.

## Reporting Model

Reporting is deferred. Raw telemetry is collected first; reports are generated later for a time range.

Planned outputs:

- internal ledger
- client status summary
- CSV invoice support export
- JSON export for downstream systems

## Why SQLite

SQLite is the best first storage target because it is:

- durable
- queryable
- local-first
- easy to export from
- sufficient for a single-operator workflow

Cloud spreadsheets can be added later as export targets, not as the system of record.
