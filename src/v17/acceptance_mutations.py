from __future__ import annotations

from pathlib import Path

from src.v16.models import Market

from .acceptance_support import (
    EVENT_DELETE_TRIGGER_SQL,
    EVENT_UPDATE_TRIGGER_SQL,
    command,
    database,
    durable_state,
    expect_failure,
    open_account,
    tamper,
)
from .acceptance_boundaries import FileState
from .boundaries import counts
from .canonical import content_hash
from .database import connect
from .faults import FaultPlan
from .fixtures import ROOT, identities
from .models import AccountNamespace, AmountPayload, Currency, OpenedPayload, PositionPayload
from .identity import identity_hash
from .schema import GENESIS_HASH
from .store import Store, reject_recovery_source
from .migrations import migrate_database


def run_mutations(portfolio: FileState) -> tuple[tuple[str, str], ...]:
    mutations = {
        "migration_hash_drift": _migration_hash_drift(),
        "migration_partial_failure": _migration_partial(),
        "database_version_ahead": _database_ahead(),
        "duplicate_retry": _duplicate_retry(),
        "idempotency_payload_conflict": _payload_conflict(),
        "event_hash_forgery": _event_forgery(),
        "event_sequence_gap": _sequence_gap(),
        "unknown_event_policy": _unknown_policy(),
        "stale_runtime_identity": _stale_identity(),
        "crash_after_event_insert": _crash(),
        "projection_cash_drift": _cash_drift(),
        "projection_position_drift": _position_drift(),
        "cross_namespace_reference": _cross_namespace(),
        "market_currency_swap": _market_currency_swap(),
        "json_recovery_attempt": expect_failure(
            lambda: reject_recovery_source(b"{}"), {"UNSUPPORTED_RECOVERY_SOURCE"}),
        "portfolio_mutation": "UNCHANGED" if portfolio == _file_state(
            ROOT / "data/portfolio.json") else "CHANGED",
        "network_attempt": str(counts().network),
        "later_version_import": str(counts().later_import),
    }
    if mutations["portfolio_mutation"] != "UNCHANGED":
        raise AssertionError("portfolio changed")
    if mutations["network_attempt"] != "0" or mutations["later_version_import"] != "0":
        raise AssertionError("boundary crossed")
    return tuple(sorted(mutations.items()))


def _migration_hash_drift() -> str:
    with database() as path:
        with Store.open(path, migrate=True):
            pass
        tamper(path, ("UPDATE schema_migrations SET sha256='sha256:bad'",))
        return expect_failure(lambda: Store.open(path), {"MIGRATION_HASH_MISMATCH"})


def _migration_partial() -> str:
    with database() as path:
        _ = expect_failure(lambda: migrate_database(path, fault_after_statement=2),
                           {"FAULT_INJECTED"})
        objects: list[tuple[str | int | float | bytes | None, ...]] = []
        version: tuple[str | int | float | bytes | None, ...] | None = None
        with connect(path) as connection:
            objects = connection.execute(
                "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchall()
            version = connection.execute("PRAGMA user_version").fetchone()
        if objects or version != (0,):
            raise AssertionError("partial migration survived")
        return "ROLLED_BACK"


def _database_ahead() -> str:
    with database() as path:
        with Store.open(path, migrate=True):
            pass
        tamper(path, ("PRAGMA user_version=2",))
        return expect_failure(lambda: Store.open(path), {"DATABASE_VERSION_AHEAD"})


def _duplicate_retry() -> str:
    identity = identities()[0]
    with database() as path:
        store = Store.open(path, migrate=True)
        operation = command(identity, "account.opened", "open-kr",
                            OpenedPayload(opening_cash_minor=100_000), GENESIS_HASH)
        first = store.execute(operation)
        store.close()
        before = durable_state(path)
        if first.duplicate:
            raise AssertionError("first command marked duplicate")
        for _ in range(10):
            with Store.open(path) as reopened:
                second = reopened.execute(operation)
            if not second.duplicate or (second.event_id, second.sequence, second.result_hash) != (
                first.event_id, first.sequence, first.result_hash):
                raise AssertionError("duplicate result changed")
            if durable_state(path) != before:
                raise AssertionError("duplicate wrote durable state")
        return first.result_hash


def _payload_conflict() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        first = command(identity, "cash.credited", "credit", AmountPayload(amount_minor=1), head)
        _ = store.execute(first)
        conflict = command(identity, "cash.credited", "credit", AmountPayload(amount_minor=2), head)
        return expect_failure(lambda: store.execute(conflict), {"IDEMPOTENCY_CONFLICT"})


def _event_forgery() -> str:
    return _event_tamper("UPDATE events SET payload_json='{\"amount_minor\":2}' WHERE sequence=2",
                         {"EVENT_HASH_MISMATCH"})


def _sequence_gap() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            _ = store.execute(command(identity, "cash.credited", "credit",
                                      AmountPayload(amount_minor=1), head))
        tamper(path, ("DROP TRIGGER events_immutable_delete",
                      "DELETE FROM events WHERE sequence=1", EVENT_DELETE_TRIGGER_SQL))
        return expect_failure(lambda: Store.open(path), {"FOREIGN_KEY_VIOLATION"})


def _unknown_policy() -> str:
    return _event_tamper("UPDATE events SET policy_version='unknown' WHERE sequence=1",
                         {"UNKNOWN_EVENT_POLICY"})


def _event_tamper(statement: str, codes: set[str]) -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            _ = store.execute(command(identity, "cash.credited", "credit",
                                      AmountPayload(amount_minor=1), head))
        tamper(path, ("DROP TRIGGER events_immutable_update", statement,
                      EVENT_UPDATE_TRIGGER_SQL))
        return expect_failure(lambda: Store.open(path), codes)


def _stale_identity() -> str:
    identity = identities()[0]
    changed = identity.model_copy(update={"config_hash": "sha256:" + "f" * 64})
    stale = changed.model_copy(update={"runtime_identity": identity_hash(changed)})
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        operation = command(stale, "cash.credited", "stale", AmountPayload(amount_minor=1), head)
        return expect_failure(lambda: store.execute(operation), {"STALE_RUNTIME_IDENTITY"})


def _crash() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            operation = command(identity, "cash.credited", "crash",
                                AmountPayload(amount_minor=1), head)
            _ = expect_failure(lambda: store.execute(operation, FaultPlan("after_event_insert")),
                               {"FAULT_INJECTED"})
        with Store.open(path):
            return "ROLLED_BACK"


def _cash_drift() -> str:
    return _projection_drift("UPDATE account_balances SET available_cash_minor=1",
                             {"RECONCILIATION_FAILED"})


def _position_drift() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            _ = store.execute(command(identity, "position.adjusted", "position",
                PositionPayload(symbol="AAPL", quantity_delta=1, average_cost_minor=10), head))
        tamper(path, ("UPDATE account_positions SET quantity=2",))
        return expect_failure(lambda: Store.open(path), {"RECONCILIATION_FAILED"})


def _projection_drift(statement: str, codes: set[str]) -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            _ = open_account(store, identity)
        tamper(path, (statement,))
        return expect_failure(lambda: Store.open(path), codes)


def _cross_namespace() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        kr_head = open_account(store, identity, Market.KR)
        us_head = open_account(store, identity, Market.US)
        _ = store.execute(command(identity, "cash.credited", "shared",
            AmountPayload(amount_minor=1), kr_head, Market.KR))
        operation = command(identity, "cash.credited", "shared",
                            AmountPayload(amount_minor=1), us_head, Market.US)
        return expect_failure(lambda: store.execute(operation), {"IDEMPOTENCY_CONFLICT"})


def _market_currency_swap() -> str:
    identity = identities()[0]
    action = lambda: AccountNamespace(account_id=identity.account_selector, market=Market.KR,
        currency=Currency.USD, arm_id=identity.arm_selector)
    return expect_failure(action, {"INVALID_MARKET_CURRENCY"})


def _snapshot(path: Path) -> tuple[bool, str]:
    return (path.exists(), content_hash(path.read_bytes()) if path.exists() else "ABSENT")


def _file_state(path: Path) -> FileState:
    exists, digest = _snapshot(path)
    return FileState(exists, digest)
