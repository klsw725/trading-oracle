from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import TracebackType
from typing import Protocol, final

from .errors import V17Error

type SqlValue = str | int | float | bytes | None


class Cursor(Protocol):
    def fetchone(self) -> tuple[SqlValue, ...] | None: ...
    def fetchall(self) -> list[tuple[SqlValue, ...]]: ...
    def __iter__(self) -> Iterator[tuple[SqlValue, ...]]: ...


class Connection(Protocol):
    def execute(self, sql: str, parameters: tuple[SqlValue, ...] = (), /) -> Cursor: ...
    def executemany(self, sql: str, parameters: Iterable[tuple[SqlValue, ...]], /) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> Connection: ...
    def __exit__(self, kind: type[BaseException] | None, value: BaseException | None,
                 traceback: TracebackType | None, /) -> bool: ...


@final
class ManagedConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def execute(self, sql: str, parameters: tuple[SqlValue, ...] = (), /) -> Cursor:
        return self._connection.execute(sql, parameters)

    def executemany(self, sql: str, parameters: Iterable[tuple[SqlValue, ...]], /) -> Cursor:
        return self._connection.executemany(sql, parameters)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> ManagedConnection:
        return self

    def __exit__(self, kind: type[BaseException] | None, value: BaseException | None,
                 traceback: TracebackType | None, /) -> bool:
        try:
            if kind is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def connect(path: Path | str, *, uri: bool = False) -> Connection:
    return ManagedConnection(sqlite3.connect(path, isolation_level=None, uri=uri))


def configure(connection: Connection, *, writable: bool) -> None:
    _ = connection.execute("PRAGMA foreign_keys=ON")
    _ = connection.execute("PRAGMA synchronous=FULL")
    _ = connection.execute("PRAGMA busy_timeout=5000")
    if writable:
        _ = connection.execute("PRAGMA journal_mode=WAL")
    observed = (_pragma_int(connection, "foreign_keys"),
                _pragma_text(connection, "journal_mode"),
                _pragma_int(connection, "synchronous"),
                _pragma_int(connection, "busy_timeout"))
    if observed != (1, "wal", 2, 5000):
        raise V17Error("STORE_PRAGMA_MISMATCH", str(observed))


def _pragma_int(connection: Connection, name: str) -> int:
    match connection.execute(f"PRAGMA {name}").fetchone():  # noqa: MATCH_OK - database boundary.
        case (int(value),): return value
        case _: raise V17Error("STORE_PRAGMA_MISMATCH", name)


def _pragma_text(connection: Connection, name: str) -> str:
    match connection.execute(f"PRAGMA {name}").fetchone():  # noqa: MATCH_OK - database boundary.
        case (str(value),): return value.lower()
        case _: raise V17Error("STORE_PRAGMA_MISMATCH", name)


def execute(
    connection: Connection,
    sql: str,
    parameters: tuple[SqlValue, ...] = (),
) -> None:
    _ = connection.execute(sql, parameters)


def row_json(
    connection: Connection,
    sql: str,
    parameters: tuple[SqlValue, ...] = (),
) -> str | None:
    match connection.execute(sql, parameters).fetchone():  # noqa: MATCH_OK - SQLite boundary.
        case None:
            return None
        case (str(payload),):
            return payload
        case tuple():
            raise V17Error("DATABASE_ROW_INVALID", "JSON query")
