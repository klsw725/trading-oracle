from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final
from pydantic import TypeAdapter

from .canonical import canonical_hash, content_hash
from .database import Connection, configure, connect
from .errors import FaultInjected, V17Error
from .models import MigrationResult
from .schema import SCHEMA_HEAD
from .schema_fingerprint import (
    expected_fingerprint,
    schema_fingerprint,
    statements,
    verify_schema_inventory,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    resource: str
    sha256: str


MIGRATIONS: Final = (
    Migration(1, "initial", "001_initial.sql", "sha256:e92b00efa8b55b0607a9b46ed009830b44782d013601d96e155ca0d8303fc0ff"),
)
SCHEMA_HASH: Final = canonical_hash(
    [{"version": item.version, "name": item.name, "sha256": item.sha256} for item in MIGRATIONS]
)


def _validate_inventory() -> None:
    versions = tuple(item.version for item in MIGRATIONS)
    if versions != tuple(range(1, len(MIGRATIONS) + 1)) or len(set(versions)) != len(versions):
        raise V17Error("MIGRATION_INVENTORY_INVALID", str(versions))
    for item in MIGRATIONS:
        payload = (Path(__file__).with_name("migrations") / item.resource).read_bytes()
        if content_hash(payload) != item.sha256:
            raise V17Error("MIGRATION_CODE_HASH_MISMATCH", item.resource)


_MIGRATION_ROW = TypeAdapter(tuple[int, str, str])


def _applied(connection: Connection) -> tuple[tuple[int, str, str], ...]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if exists is None:
        return ()
    rows = connection.execute(
        "SELECT version,name,sha256 FROM schema_migrations ORDER BY version"
    ).fetchall()
    return tuple(_MIGRATION_ROW.validate_python(row) for row in rows)


def validate_schema(connection: Connection) -> int:
    _validate_inventory()
    match connection.execute("PRAGMA user_version").fetchone():  # noqa: MATCH_OK - database boundary.
        case (int(user_version),):
            pass
        case _:
            raise V17Error("DATABASE_ROW_INVALID", "user_version")
    if user_version > SCHEMA_HEAD:
        raise V17Error("DATABASE_VERSION_AHEAD", str(user_version))
    applied = _applied(connection)
    if tuple(row[0] for row in applied) != tuple(range(1, len(applied) + 1)):
        raise V17Error("MIGRATION_SEQUENCE_INVALID", str(applied))
    for row, expected in zip(applied, MIGRATIONS, strict=False):
        if row != (expected.version, expected.name, expected.sha256):
            raise V17Error("MIGRATION_HASH_MISMATCH", str(expected.version))
    if user_version != len(applied):
        raise V17Error("MIGRATION_VERSION_MISMATCH", f"{user_version}/{len(applied)}")
    assets = tuple(
        (Path(__file__).with_name("migrations") / item.resource).read_text()
        for item in MIGRATIONS[:user_version]
    )
    if schema_fingerprint(connection) != expected_fingerprint(assets):
        raise V17Error("SCHEMA_FINGERPRINT_MISMATCH", str(user_version))
    if user_version == SCHEMA_HEAD:
        verify_schema_inventory(connection)
    return user_version


def migrate_database(path: Path, *, fault_after_statement: int | None = None) -> MigrationResult:
    _validate_inventory()
    path.parent.mkdir(parents=True, exist_ok=True)
    applied: list[int] = []
    statement_count = 0
    with connect(path) as connection:
        configure(connection, writable=True)
        version = validate_schema(connection)
        for migration in MIGRATIONS[version:]:
            sql = (Path(__file__).with_name("migrations") / migration.resource).read_text()
            _ = connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in statements(sql):
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
            except BaseException:  # noqa: BROAD_EXCEPT_OK - atomic rollback then unchanged re-raise.
                connection.rollback()
                raise
            applied.append(migration.version)
        _ = validate_schema(connection)
    return MigrationResult(path, tuple(applied), SCHEMA_HEAD, SCHEMA_HASH)
