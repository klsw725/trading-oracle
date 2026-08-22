from __future__ import annotations

from .acceptance_support import command, database, durable_state, expect_failure, open_account
from .database import connect
from .faults import FaultPlan
from .faults import FaultPoint
from .fixtures import identities
from .models import AmountPayload, PositionPayload, ReleasePayload, ReservationPayload
from .store import Store, verify_database
from .acceptance_integrity import integrity_checks
from .acceptance_invariants import invariant_checks


def run_checks() -> tuple[tuple[str, str], ...]:
    checks = [
        ("all_event_types_commit", _happy_path()),
        ("deterministic_replay", _replay()),
        ("namespace_isolation", _namespace_isolation()),
        ("persisted_checkpoint_drift", _checkpoint_drift()),
        ("persisted_idempotency_drift", _idempotency_drift()),
        ("mutation_reconciles_open_store", _open_store_drift()),
    ]
    points: tuple[FaultPoint, ...] = (
        "after_event_insert", "after_idempotency_insert",
        "after_projection_write", "after_checkpoint",
    )
    for point in points:
        checks.append((f"fault_{point}", _fault_rollback(point)))
    return tuple(sorted((*checks, *integrity_checks(), *invariant_checks())))


def _happy_path() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            operations = (
                ("cash.credited", "credit", AmountPayload(amount_minor=10_000)),
                ("cash.debited", "debit", AmountPayload(amount_minor=5_000)),
                ("position.adjusted", "position", PositionPayload(
                    symbol="AAPL", quantity_delta=2, average_cost_minor=20_000)),
                ("reservation.placed", "reserve", ReservationPayload(
                    reservation_id="reservation-1", amount_minor=1_000)),
                ("reservation.released", "release", ReleasePayload(
                    reservation_id="reservation-1")),
            )
            for event_type, command_id, payload in operations:
                head = store.execute(command(identity, event_type, command_id, payload, head)).event_id
        return verify_database(path)


def _replay() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            _ = store.execute(command(identity, "cash.credited", "credit",
                                      AmountPayload(amount_minor=1), head))
        first = verify_database(path)
        second = verify_database(path)
        if first != second:
            raise AssertionError("replay differs")
        return first


def _namespace_isolation() -> str:
    primary, secondary = identities()
    with database() as path:
        with Store.open(path, migrate=True) as store:
            _ = open_account(store, primary)
            _ = open_account(store, secondary)
        return verify_database(path)


def _fault_rollback(point: FaultPoint) -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            before = durable_state(path)
            action = lambda: store.execute(command(identity, "cash.credited", f"fault-{point}",
                AmountPayload(amount_minor=1), head), FaultPlan(point))
            _ = expect_failure(action, {"FAULT_INJECTED"})
        with Store.open(path):
            after = durable_state(path)
        if before != after:
            raise AssertionError(point)
        return after


def _checkpoint_drift() -> str:
    return _drift_check("UPDATE projection_checkpoints SET sequence=sequence+1",
                        {"FOREIGN_KEY_VIOLATION"})


def _idempotency_drift() -> str:
    return _drift_check("UPDATE idempotency_keys SET result_hash='sha256:bad'",
                        {"IDEMPOTENCY_DRIFT"})


def _drift_check(statement: str, codes: set[str]) -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            _ = open_account(store, identity)
        with connect(path) as connection:
            _ = connection.execute(statement)
        return expect_failure(lambda: Store.open(path), codes)


def _open_store_drift() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        with connect(path) as connection:
            _ = connection.execute("UPDATE account_balances SET available_cash_minor=1")
        action = lambda: store.execute(command(identity, "cash.credited", "blocked",
            AmountPayload(amount_minor=1), head))
        return expect_failure(action, {"RECONCILIATION_FAILED"})
