from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from src.v17 import migrations as v17_migrations
from src.v17.canonical import JsonValue, canonical_hash, content_hash
from src.v17.database import Connection, SqlValue, configure, connect
from src.v17.errors import V17Error
from src.v17.schema_fingerprint import statements

from .errors import FaultInjected, V18Error
from .schema import SCHEMA_HEAD, TABLES, TRIGGERS


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    resource: str
    sha256: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    path: Path
    applied: tuple[int, ...]
    head: int
    schema_hash: str


MIGRATIONS: Final = (
    Migration(
        1,
        "initial",
        "../v17/migrations/001_initial.sql",
        "sha256:e92b00efa8b55b0607a9b46ed009830b44782d013601d96e155ca0d8303fc0ff",
    ),
    Migration(
        2,
        "measurement",
        "migrations/002_measurement.sql",
        "sha256:22366ccf329008b7df5690d0db9e5e62bfda734a6bbd42e26ae30849ab6903c0",
    ),
)
SCHEMA_HASH: Final = canonical_hash(
    [
        {"name": item.name, "sha256": item.sha256, "version": item.version}
        for item in MIGRATIONS
    ]
)


def _resource(item: Migration) -> Path:
    if item.version == 1:
        return Path(v17_migrations.__file__).with_name("migrations") / "001_initial.sql"
    return Path(__file__).parent / item.resource


def _validate_inventory() -> None:
    observed_v17 = v17_migrations.MIGRATIONS[0]
    expected_v17 = MIGRATIONS[0]
    if (observed_v17.version, observed_v17.name, observed_v17.sha256) != (
        expected_v17.version,
        expected_v17.name,
        expected_v17.sha256,
    ):
        raise V18Error("MIGRATION_HASH_MISMATCH", "v17 migration 001")
    for item in MIGRATIONS:
        if content_hash(_resource(item).read_bytes()) != item.sha256:
            raise V18Error("MIGRATION_CODE_HASH_MISMATCH", item.resource)


def _json_row(row: tuple[SqlValue, ...]) -> JsonValue:
    result: list[JsonValue] = []
    for value in row:
        match value:  # noqa: MATCH_OK - SqlValue union is fully handled.
            case str() | int() | float() | None:
                result.append(value)
            case bytes():
                raise V18Error("SCHEMA_FINGERPRINT_INVALID", "blob catalog value")
    return result


def _schema_fingerprint(connection: Connection) -> str:
    catalog = [
        _json_row(row)
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            + "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
    ]
    tables: dict[str, JsonValue] = {}
    indexes: dict[str, JsonValue] = {}
    for table in TABLES:
        tables[table] = {
            "columns": [
                _json_row(row)
                for row in connection.execute(f'PRAGMA table_xinfo("{table}")').fetchall()
            ],
            "foreign_keys": [
                _json_row(row)
                for row in connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
            ],
        }
        index_rows = connection.execute(f'PRAGMA index_list("{table}")').fetchall()
        index_values: list[JsonValue] = []
        for row in index_rows:
            match row:  # noqa: MATCH_OK - SQLite index rows are runtime-shaped.
                case (_, str(name), *_):
                    escaped = name.replace('"', '""')
                case _:
                    raise V18Error("SCHEMA_FINGERPRINT_INVALID", "index row")
            index_values.append(
                {
                    "columns": [
                        _json_row(item)
                        for item in connection.execute(
                            f'PRAGMA index_xinfo("{escaped}")'
                        ).fetchall()
                    ],
                    "index": _json_row(row),
                }
            )
        indexes[table] = index_values
    return canonical_hash({"catalog": catalog, "indexes": indexes, "tables": tables})


def _expected_fingerprint() -> str:
    connection = connect(":memory:")
    try:
        for migration in MIGRATIONS:
            for statement in statements(_resource(migration).read_text()):
                _ = connection.execute(statement)
        return _schema_fingerprint(connection)
    finally:
        connection.close()


def _user_version(connection: Connection) -> int:
    match connection.execute("PRAGMA user_version").fetchone():  # noqa: MATCH_OK - SQLite boundary.
        case (int(version),):
            return version
        case _:
            raise V18Error("DATABASE_ROW_INVALID", "user_version")


def _applied(connection: Connection) -> tuple[tuple[int, str, str], ...]:
    rows = connection.execute(
        "SELECT version,name,sha256 FROM schema_migrations ORDER BY version"
    ).fetchall()
    result: list[tuple[int, str, str]] = []
    for row in rows:
        match row:  # noqa: MATCH_OK - SQLite migration rows are runtime-shaped.
            case (int(version), str(name), str(digest)):
                result.append((version, name, digest))
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "schema_migrations")
    return tuple(result)


def validate_schema(connection: Connection) -> int:
    _validate_inventory()
    version = _user_version(connection)
    if version > SCHEMA_HEAD:
        raise V18Error("DATABASE_VERSION_AHEAD", str(version))
    if version < SCHEMA_HEAD:
        raise V18Error("MIGRATION_REQUIRED", str(version))
    expected_rows = tuple((item.version, item.name, item.sha256) for item in MIGRATIONS)
    if _applied(connection) != expected_rows:
        raise V18Error("MIGRATION_HASH_MISMATCH", "combined inventory")
    rows = connection.execute(
        "SELECT type,name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    tables = tuple(sorted(str(row[1]) for row in rows if row[0] == "table"))
    triggers = tuple(sorted(str(row[1]) for row in rows if row[0] == "trigger"))
    other = tuple(row for row in rows if row[0] not in {"table", "trigger"})
    if tables != tuple(sorted(TABLES)) or triggers != TRIGGERS or other:
        raise V18Error(
            "SCHEMA_OBJECT_INVENTORY_MISMATCH",
            canonical_hash([_json_row(row) for row in rows]),
        )
    if _schema_fingerprint(connection) != _expected_fingerprint():
        raise V18Error("SCHEMA_FINGERPRINT_MISMATCH", str(version))
    return version


def migrate_database(
    path: Path, *, fault_after_statement: int | None = None
) -> MigrationResult:
    _validate_inventory()
    if not path.is_file():
        _ = v17_migrations.migrate_database(path)
    applied: list[int] = []
    with connect(path) as connection:
        configure(connection, writable=True)
        version = _user_version(connection)
        if version == 1:
            try:
                _ = v17_migrations.validate_schema(connection)
            except V17Error as error:
                raise V18Error("SCHEMA_FINGERPRINT_MISMATCH", "v17 head 001") from error
        if version > SCHEMA_HEAD:
            raise V18Error("DATABASE_VERSION_AHEAD", str(version))
        statement_count = 0
        for migration in MIGRATIONS[version:]:
            _ = connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in statements(_resource(migration).read_text()):
                    _ = connection.execute(statement)
                    statement_count += 1
                    if fault_after_statement == statement_count:
                        raise FaultInjected(f"migration_statement_{statement_count}")
                _ = connection.execute(
                    "INSERT INTO schema_migrations(version,name,sha256) VALUES(?,?,?)",
                    (migration.version, migration.name, migration.sha256),
                )
                _ = connection.execute(f"PRAGMA user_version={migration.version}")
                connection.commit()
            except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then re-raise.
                connection.rollback()
                raise
            applied.append(migration.version)
        _ = validate_schema(connection)
    return MigrationResult(path, tuple(applied), SCHEMA_HEAD, SCHEMA_HASH)
