from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable, Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar

from pydantic import ValidationError
from src.v16.models import Market, RuntimeIdentity

from .errors import FaultInjected, V17Error
from .database import connect
from .canonical import JsonValue, canonical_hash
from .models import (
    AccountNamespace,
    AmountPayload,
    Command,
    Currency,
    OpenedPayload,
    PositionPayload,
    ReleasePayload,
    ReservationPayload,
)
from .schema import GENESIS_HASH
from .schema import TABLES
from .store import Store

EFFECTIVE_AT = "2026-01-05T21:00:00Z"
EVENT_UPDATE_TRIGGER_SQL = (
    "CREATE TRIGGER events_immutable_update BEFORE UPDATE ON events\n"
    "BEGIN SELECT RAISE(ABORT, 'events are immutable'); END"
)
EVENT_DELETE_TRIGGER_SQL = (
    "CREATE TRIGGER events_immutable_delete BEFORE DELETE ON events\n"
    "BEGIN SELECT RAISE(ABORT, 'events are immutable'); END"
)


@contextmanager
def database() -> Iterator[Path]:
    with TemporaryDirectory(prefix="trading-oracle-v17-") as directory:
        yield Path(directory) / "paper.sqlite3"


def namespace(identity: RuntimeIdentity, market: Market = Market.KR) -> AccountNamespace:
    currency = Currency.KRW if market is Market.KR else Currency.USD
    return AccountNamespace(account_id=identity.account_selector, market=market,
                            currency=currency, arm_id=identity.arm_selector)


def command(
    identity: RuntimeIdentity,
    command_type: str,
    command_id: str,
    payload: OpenedPayload | AmountPayload | PositionPayload | ReservationPayload | ReleasePayload,
    previous: str,
    market: Market = Market.KR,
) -> Command:
    event_type = _event_type(command_type)
    return Command(event_type, command_id, namespace(identity, market), identity,
                   "v17.config.1", identity.policy_version, EFFECTIVE_AT, payload, previous)


def _event_type(value: str):
    match value:  # noqa: MATCH_OK - fixture boundary rejects unknown types.
        case "account.opened": return "account.opened"
        case "cash.credited": return "cash.credited"
        case "cash.debited": return "cash.debited"
        case "position.adjusted": return "position.adjusted"
        case "reservation.placed": return "reservation.placed"
        case "reservation.released": return "reservation.released"
        case _: raise V17Error("UNKNOWN_EVENT_TYPE", value)


def open_account(store: Store, identity: RuntimeIdentity, market: Market = Market.KR) -> str:
    result = store.execute(command(identity, "account.opened", f"open-{market.value.lower()}",
                                   OpenedPayload(opening_cash_minor=100_000), GENESIS_HASH, market))
    return result.event_id


Result = TypeVar("Result")


def expect_failure(action: Callable[[], Result], codes: set[str]) -> str:
    try:
        _ = action()
    except V17Error as error:
        if error.code not in codes:
            raise
        return error.code
    except FaultInjected as error:
        if "FAULT_INJECTED" not in codes:
            raise
        return "FAULT_INJECTED"
    except ValidationError:
        if "VALIDATION_ERROR" not in codes:
            raise
        return "VALIDATION_ERROR"
    raise V17Error("ACCEPTANCE_UNEXPECTED_SUCCESS", ",".join(sorted(codes)))


def tamper(path: Path, statements: tuple[str, ...]) -> None:
    with connect(path) as connection:
        _ = connection.execute("PRAGMA foreign_keys=OFF")
        for statement in statements:
            _ = connection.execute(statement)


def durable_state(path: Path) -> str:
    value: list[JsonValue] = []
    with connect(path) as connection:
        for table in TABLES:
            columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            order = ",".join(str(index) for index in range(1, len(columns) + 1))
            rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}').fetchall()
            encoded: list[JsonValue] = []
            for row in rows:
                encoded.append([_json_scalar(item) for item in row])
            value.append({"table": table, "rows": encoded})
    return canonical_hash(value)


def _json_scalar(value: str | int | float | bytes | None) -> JsonValue:
    match value:  # noqa: MATCH_OK - durable schema stores no blobs.
        case str() | int() | float() | None:
            return value
        case bytes():
            raise V17Error("DATABASE_ROW_INVALID", "blob durable value")
