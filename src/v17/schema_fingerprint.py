from __future__ import annotations

import sqlite3

from .canonical import JsonValue, canonical_hash
from .database import Connection, SqlValue, connect
from .errors import V17Error
from .schema import TABLES

TRIGGERS = ("events_immutable_delete", "events_immutable_update")


def _json_row(row: tuple[SqlValue, ...]) -> JsonValue:
    result: list[JsonValue] = []
    for value in row:
        match value:  # noqa: MATCH_OK - schema catalog cannot contain blobs.
            case str() | int() | float() | None:
                result.append(value)
            case bytes():
                raise V17Error("SCHEMA_FINGERPRINT_INVALID", "blob catalog value")
    return result


def schema_fingerprint(connection: Connection) -> str:
    catalog_rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema " +
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    catalog: list[JsonValue] = [_json_row(row) for row in catalog_rows]
    tables: dict[str, JsonValue] = {}
    indexes: dict[str, JsonValue] = {}
    for table in TABLES:
        table_value: JsonValue = {
            "columns": [_json_row(row) for row in connection.execute(
                f'PRAGMA table_xinfo("{table}")').fetchall()],
            "foreign_keys": [_json_row(row) for row in connection.execute(
                f'PRAGMA foreign_key_list("{table}")').fetchall()],
        }
        tables[table] = table_value
        index_rows = connection.execute(f'PRAGMA index_list("{table}")').fetchall()
        indexes[table] = [
            {"index": _json_row(row), "columns": _index_columns(connection, row)}
            for row in index_rows
        ]
    value: dict[str, JsonValue] = {"catalog": catalog, "tables": tables,
                                   "indexes": indexes}
    return canonical_hash(value)


def verify_schema_inventory(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT type,name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    tables = tuple(sorted(str(row[1]) for row in rows if row[0] == "table"))
    triggers = tuple(sorted(str(row[1]) for row in rows if row[0] == "trigger"))
    other = tuple(row for row in rows if row[0] not in {"table", "trigger"})
    if tables != tuple(sorted(TABLES)) or triggers != TRIGGERS or other:
        raise V17Error("SCHEMA_OBJECT_INVENTORY_MISMATCH", canonical_hash(
            [[str(value) for value in row] for row in rows]))


def _index_columns(connection: Connection, row: tuple[SqlValue, ...]) -> JsonValue:
    if len(row) < 2 or not isinstance(row[1], str):
        raise V17Error("SCHEMA_FINGERPRINT_INVALID", "index row")
    name = row[1].replace('"', '""')
    return [_json_row(item) for item in connection.execute(
        f'PRAGMA index_xinfo("{name}")').fetchall()]


def expected_fingerprint(sql_assets: tuple[str, ...]) -> str:
    connection = connect(":memory:")
    try:
        for sql in sql_assets:
            for statement in statements(sql):
                _ = connection.execute(statement)
        return schema_fingerprint(connection)
    finally:
        connection.close()


def statements(sql: str) -> tuple[str, ...]:
    result: list[str] = []
    pending = ""
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            result.append(pending.strip())
            pending = ""
    if pending.strip():
        raise V17Error("MIGRATION_SQL_INVALID", "incomplete statement")
    return tuple(result)
