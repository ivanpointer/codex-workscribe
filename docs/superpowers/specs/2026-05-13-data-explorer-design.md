# Workscribe Local Data Explorer Design

## Purpose

Add a local, read-only Vue SPA for exploring Workscribe's collected SQLite data without manually launching SQLite or writing ad hoc queries.

The first release is an inspection workbench for refining capture behavior and understanding what is being stored. It is not a reporting surface and does not need export/download actions because report generation already exists elsewhere in the CLI.

## Scope

### In Scope

- A new `workscribe explore` command.
- Local-only server bound to localhost by default.
- Read-only access to the discovered `.codex-workscribe.sqlite` database.
- Vue SPA served by the Python command.
- Workbench workflow:
  - table navigation
  - paginated row browsing
  - search and filtering
  - column sorting
  - selected-row detail panel
  - readable display for JSON and long text fields
  - relationship shortcuts for known foreign keys
- A reserved disabled Timeline navigation item for a future timeline workflow.

### Out of Scope

- Editing database rows.
- Exporting filtered rows to JSON/CSV.
- Client-facing report generation.
- Authentication for the first local-only release.
- Timeline implementation in the first pass.

## Architecture

The CLI grows a new `explore` subcommand:

```text
workscribe explore --path . --host 127.0.0.1 --port 0
```

The command resolves the Workscribe workspace using the existing `discover_workspace` function, verifies that the discovered SQLite database has the expected Workscribe tables, opens it in read-only mode for API requests, and serves both API endpoints and the built Vue assets from a small Python HTTP server.

Binding to `127.0.0.1` is the default. A future option can allow another host explicitly, but the default should not expose telemetry outside the local machine.

## Backend API

The backend exposes narrowly scoped read endpoints:

- `GET /api/meta`
  - database path
  - program root
  - project/client summary counts
  - table list
- `GET /api/tables`
  - table names
  - columns
  - primary keys
  - known foreign keys
- `GET /api/tables/{table}/rows`
  - pagination parameters: `limit`, `offset`
  - sorting parameters: `sort`, `direction`
  - optional search text
  - optional column filters
- `GET /api/tables/{table}/rows/{id}`
  - complete selected row
  - parsed JSON fields where possible
  - related-record links for known relationships

The API uses an allowlist of known Workscribe tables from the schema rather than accepting arbitrary SQL. Sort columns and filter columns are validated against table metadata before query construction. Values are always bound with SQLite parameters.

## Frontend

The Vue SPA uses a Workbench-first layout:

- left sidebar: table list and counts
- main pane: searchable, sortable, paginated grid
- right pane: selected row details

The UI is dense and utilitarian because the target user is inspecting operational telemetry repeatedly, not consuming a marketing dashboard.

JSON text columns such as `tags_json`, `config_json`, `tool_input_json`, `tool_response_json`, `metadata_json`, `changed_files_json`, `input_session_ids_json`, `input_commit_ids_json`, and `report_json` are formatted as expandable structured values when valid. Long text fields such as prompts, notes, commit bodies, and report Markdown are shown in readable blocks in the detail panel.

The app includes a disabled or clearly marked Timeline navigation item so the long-term workflow has a place in the product shape without implementing it prematurely.

## Data Flow

1. User runs `workscribe explore`.
2. CLI discovers the program root and SQLite database.
3. Local server starts and prints the URL.
4. Vue app loads `/api/meta` and `/api/tables`.
5. Selecting a table loads paginated rows.
6. Selecting a row loads its full details and relationship shortcuts.

No endpoint mutates the database.

## Error Handling

- If no Workscribe root is found, reuse the existing clear `WorkscribeError` guidance.
- If the database cannot be opened read-only, show a terminal error and do not start the server.
- API errors return JSON with a concise `error` string.
- Unknown tables, columns, sort fields, and filter fields return `400` instead of falling back to unsafe query behavior.
- The SPA shows empty states for tables with no rows and error states for failed API calls.

## Testing

Backend tests should cover:

- command parser registration for `explore`
- workspace discovery path handling
- table metadata endpoint behavior
- paginated row listing
- search/filter/sort validation
- row detail JSON parsing
- rejection of unknown tables and columns

Frontend tests can stay light for the first pass:

- component-level tests for API state rendering if a test stack is added
- otherwise, verify the production build and exercise the app manually against a temporary SQLite database

The implementation should follow red-green-refactor for backend behavior. Frontend behavior can be added after the API contract is covered, with build verification before completion.

## Future Timeline Workflow

The timeline workflow is intentionally deferred. It should reuse the same read-only backend and add session-centered endpoints that return prompts, tool events, notes, commits, and reports in chronological order.

This later view is useful once the capture process matures and the goal shifts from raw table inspection to understanding work narratives over time.
