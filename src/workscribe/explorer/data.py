from __future__ import annotations

import json
import sqlite3
from typing import Any


WORKSCRIBE_TABLES = (
    "clients",
    "projects",
    "config_snapshots",
    "sessions",
    "prompts",
    "tool_events",
    "notes",
    "commits",
    "reports",
    "installations",
)

JSON_COLUMNS = {
    "tags_json",
    "config_json",
    "tool_input_json",
    "tool_response_json",
    "metadata_json",
    "changed_files_json",
    "input_session_ids_json",
    "input_commit_ids_json",
    "report_json",
    "notes_json",
}

DEFAULT_SORT_COLUMNS = (
    "updated_at",
    "created_at",
    "captured_at",
    "submitted_at",
    "committed_at",
    "id",
)


class ExplorerQueryError(Exception):
    """Raised when an explorer query cannot be safely executed."""


def get_table_metadata(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    _ensure_workscribe_database(conn)
    metadata = []
    for table in WORKSCRIBE_TABLES:
        columns = _get_columns(conn, table)
        primary_key = [column["name"] for column in columns if column["pk"]]
        metadata.append(
            {
                "name": table,
                "columns": [
                    {
                        "name": column["name"],
                        "type": column["type"],
                        "primary_key": bool(column["pk"]),
                    }
                    for column in columns
                ],
                "primary_key": primary_key,
                "count": _count_rows(conn, table),
                "foreign_keys": _get_foreign_keys(conn, table),
            }
        )
    return metadata


def list_rows(
    conn: sqlite3.Connection,
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
    sort: str | None = None,
    direction: str = "desc",
    search: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_known_table(table)
    _ensure_workscribe_database(conn)
    columns = _get_columns(conn, table)
    column_names = [column["name"] for column in columns]
    column_set = set(column_names)
    sort_column = sort or _default_sort_column(column_names)
    if sort_column not in column_set:
        raise ExplorerQueryError(f"Unknown column: {sort_column}")

    normalized_limit = max(1, min(200, int(limit)))
    normalized_offset = max(0, int(offset))
    normalized_direction = "asc" if direction == "asc" else "desc"
    where_sql, params = _build_where(column_names, search=search, filters=filters)

    total = _fetch_one_value(
        conn,
        f'SELECT COUNT(*) FROM "{table}"{where_sql}',
        params,
    )
    cursor = conn.execute(
        f'SELECT * FROM "{table}"{where_sql} '
        f'ORDER BY "{sort_column}" {normalized_direction.upper()} '
        "LIMIT ? OFFSET ?",
        (*params, normalized_limit, normalized_offset),
    )

    return {
        "table": table,
        "rows": _cursor_dicts(cursor),
        "total": int(total),
        "limit": normalized_limit,
        "offset": normalized_offset,
        "sort": sort_column,
        "direction": normalized_direction,
    }


def get_row_detail(conn: sqlite3.Connection, table: str, row_id: Any) -> dict[str, Any]:
    _ensure_known_table(table)
    _ensure_workscribe_database(conn)
    column_names = [column["name"] for column in _get_columns(conn, table)]
    if "id" not in column_names:
        raise ExplorerQueryError(f"Table has no id column: {table}")

    cursor = conn.execute(f'SELECT * FROM "{table}" WHERE "id" = ?', (row_id,))
    rows = _cursor_dicts(cursor)
    if not rows:
        raise ExplorerQueryError(f"Row not found in {table}: {row_id}")

    row = rows[0]
    parsed_json = {}
    for column in JSON_COLUMNS.intersection(row.keys()):
        value = row[column]
        if value is None:
            continue
        try:
            parsed_json[column] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue

    return {
        "table": table,
        "row": row,
        "parsed_json": parsed_json,
        "related": _get_related(conn, table, row_id),
    }


def _ensure_known_table(table: str) -> None:
    if table not in WORKSCRIBE_TABLES:
        raise ExplorerQueryError(f"Unknown table: {table}")


def _ensure_workscribe_database(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in _pragma_dicts(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        )
    }
    if not set(WORKSCRIBE_TABLES).issubset(existing):
        raise ExplorerQueryError("not a Workscribe database")


def _get_columns(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [
        {
            "name": row["name"],
            "type": row["type"],
            "pk": int(row["pk"]),
        }
        for row in _pragma_dicts(conn.execute(f'PRAGMA table_info("{table}")'))
    ]


def _get_foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [
        {
            "column": row["from"],
            "references_table": row["table"],
            "references_column": row["to"],
        }
        for row in _pragma_dicts(conn.execute(f'PRAGMA foreign_key_list("{table}")'))
    ]


def _get_related(conn: sqlite3.Connection, table: str, row_id: Any) -> list[dict[str, Any]]:
    related = []
    for candidate in WORKSCRIBE_TABLES:
        for foreign_key in _get_foreign_keys(conn, candidate):
            if (
                foreign_key["references_table"] == table
                and foreign_key["references_column"] == "id"
            ):
                count = _fetch_one_value(
                    conn,
                    f'SELECT COUNT(*) FROM "{candidate}" WHERE "{foreign_key["column"]}" = ?',
                    (row_id,),
                )
                related.append(
                    {
                        "table": candidate,
                        "column": foreign_key["column"],
                        "value": row_id,
                        "count": int(count),
                    }
                )
    return related


def _build_where(
    column_names: list[str],
    *,
    search: str | None,
    filters: dict[str, Any] | None,
) -> tuple[str, tuple[Any, ...]]:
    conditions = []
    params = []
    if search:
        searchable_columns = [column for column in column_names if column != "id"]
        if searchable_columns:
            conditions.append(
                "("
                + " OR ".join(f'CAST("{column}" AS TEXT) LIKE ?' for column in searchable_columns)
                + ")"
            )
            params.extend([f"%{search}%"] * len(searchable_columns))

    for column, value in (filters or {}).items():
        if column not in column_names:
            raise ExplorerQueryError(f"Unknown column: {column}")
        conditions.append(f'CAST("{column}" AS TEXT) LIKE ?')
        params.append(f"%{value}%")

    if not conditions:
        return "", ()
    return " WHERE " + " AND ".join(conditions), tuple(params)


def _default_sort_column(column_names: list[str]) -> str:
    for column in DEFAULT_SORT_COLUMNS:
        if column in column_names:
            return column
    return column_names[0]


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    return int(_fetch_one_value(conn, f'SELECT COUNT(*) FROM "{table}"', ()))


def _fetch_one_value(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def _pragma_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _cursor_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]
