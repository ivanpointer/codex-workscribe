# codex-workscribe

`codex-workscribe` captures agent-assisted coding work into a durable local ledger for billing, reporting, and client summaries.

It is designed around four constraints:

1. Codex local session history is not currently exposed as a clean billing API.
2. Billing needs evidence, not just "time active in terminal".
3. Client/project metadata should stay human-editable.
4. Reports should be generated later from raw telemetry, not improvised at session end.

## First-Version Scope

Version one will:

- capture Codex hook events such as session start, prompt submission, tool use, and stop
- capture Git evidence such as commits, branches, diff stats, and changed files
- persist telemetry into a local SQLite database
- load client and project metadata from TOML config files
- install and uninstall global Codex and Git hook wiring
- initialize program roots and repo workspaces with an `init` flow
- allow manual `note` and `end-session` entries for notable events and remembered summaries
- generate report bundles with Markdown, JSON, CSV, and lightweight SVG charts
- generate weekly or custom-range reports later, including client-facing summaries

Version one will not try to:

- decide billable time perfectly
- replace accounting software
- sync directly to cloud spreadsheets on day one
- infer work done outside tracked shells or repositories with high confidence

## Core Model

The system separates:

- `metadata`: client, engagement, project, billing defaults
- `telemetry`: sessions, prompts, tool events, git activity
- `reports`: generated summaries for invoice periods or status updates

Authoritative metadata lives in TOML. Telemetry lives in SQLite. Metadata is mirrored into SQLite for reporting joins.

## Planned Layout

```text
codex-workscribe/
├── README.md
├── .gitignore
├── docs/
│   ├── architecture.md
│   ├── schema.md
│   └── roadmap.md
├── examples/
│   ├── root.codex-workscribe.toml
│   └── repo.codex-workscribe.toml
└── src/
    └── workscribe/
```

## Initial Workflow

1. User configures a program root and repo-level metadata.
2. `workscribe install-global` sets up one-time global Codex and Git hooks.
3. `workscribe init program` creates a client/program root with one shared SQLite DB.
4. `workscribe init project` or `workscribe init repo` adds project metadata for a repo under that root.
5. Global hooks resolve the nearest configured root by walking the current directory upward.
6. Codex hooks write raw session activity into the root SQLite DB.
7. Git hooks append commit and diff evidence into that same root SQLite DB.
8. Manual `workscribe note` and `workscribe end-session` commands can add notable context at any point.
9. A later command generates:
   - an internal ledger
   - a client-facing summary
   - CSV/JSON exports for invoice support
   - simple SVG charts for client-facing context

## Design Docs

- [Architecture](docs/architecture.md)
- [Schema](docs/schema.md)
- [Roadmap](docs/roadmap.md)
