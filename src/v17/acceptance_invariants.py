from __future__ import annotations

from src.v16.models import Market

from .acceptance_support import command, database, durable_state, expect_failure, open_account
from .database import connect
from .fixtures import identities
from .identity import identity_hash
from .models import (
    AmountPayload,
    OpenedPayload,
    PositionPayload,
    ReleasePayload,
    ReservationPayload,
)
from .schema import GENESIS_HASH, INT64_MAX
from .store import Store


def invariant_checks() -> tuple[tuple[str, str], ...]:
    return tuple(sorted((
        ("stale_event_head_rejected", _stale_head()),
        ("idempotency_identity_conflict", _identity_conflict()),
        ("negative_cash_rejected", _negative_cash()),
        ("duplicate_release_rejected", _duplicate_release()),
        ("int64_overflow_rejected", _overflow()),
        ("second_opening_rejected", _second_opening()),
        ("unknown_command_policy_rejected", _unknown_policy()),
        ("kr_us_two_account_two_arm_state", _full_namespace_state()),
    )))


def _stale_head() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        _ = open_account(store, identity)
        before = durable_state(path)
        operation = command(identity, "cash.credited", "stale-head",
                            AmountPayload(amount_minor=1), GENESIS_HASH)
        code = expect_failure(lambda: store.execute(operation), {"STALE_EVENT_HEAD"})
        if durable_state(path) != before:
            raise AssertionError("stale head mutated state")
        return code


def _identity_conflict() -> str:
    identity = identities()[0]
    changed = identity.model_copy(update={"config_hash": "sha256:" + "e" * 64})
    conflicting = changed.model_copy(update={"runtime_identity": identity_hash(changed)})
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        first = command(identity, "cash.credited", "identity-conflict",
                        AmountPayload(amount_minor=1), head)
        _ = store.execute(first)
        before = durable_state(path)
        conflict = command(conflicting, "cash.credited", "identity-conflict",
                           AmountPayload(amount_minor=1), head)
        code = expect_failure(lambda: store.execute(conflict), {"IDEMPOTENCY_CONFLICT"})
        if durable_state(path) != before:
            raise AssertionError("identity conflict mutated state")
        return code


def _negative_cash() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        operation = command(identity, "cash.debited", "negative",
                            AmountPayload(amount_minor=100_001), head)
        return expect_failure(lambda: store.execute(operation), {"INSUFFICIENT_CASH"})


def _duplicate_release() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        placed = store.execute(command(identity, "reservation.placed", "place",
            ReservationPayload(reservation_id="r1", amount_minor=1), head))
        released = store.execute(command(identity, "reservation.released", "release",
            ReleasePayload(reservation_id="r1"), placed.event_id))
        again = command(identity, "reservation.released", "release-again",
                        ReleasePayload(reservation_id="r1"), released.event_id)
        return expect_failure(lambda: store.execute(again), {"RESERVATION_NOT_ACTIVE"})


def _overflow() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        opened = store.execute(command(identity, "account.opened", "open-max",
            OpenedPayload(opening_cash_minor=INT64_MAX), GENESIS_HASH))
        operation = command(identity, "cash.credited", "overflow",
                            AmountPayload(amount_minor=1), opened.event_id)
        return expect_failure(lambda: store.execute(operation), {"INTEGER_OUT_OF_RANGE"})


def _second_opening() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        operation = command(identity, "account.opened", "open-again",
                            OpenedPayload(opening_cash_minor=1), head)
        return expect_failure(lambda: store.execute(operation), {"ACCOUNT_ALREADY_OPEN"})


def _unknown_policy() -> str:
    identity = identities()[0]
    changed = identity.model_copy(update={"policy_version": "unknown"})
    unknown = changed.model_copy(update={"runtime_identity": identity_hash(changed)})
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        operation = command(unknown, "cash.credited", "unknown-policy",
                            AmountPayload(amount_minor=1), head)
        return expect_failure(lambda: store.execute(operation), {"UNKNOWN_EVENT_POLICY"})


def _full_namespace_state() -> str:
    primary, secondary = identities()
    balances: list[tuple[str | int | float | bytes | None, ...]] = []
    positions: tuple[str | int | float | bytes | None, ...] | None = None
    reservations: tuple[str | int | float | bytes | None, ...] | None = None
    with database() as path:
        with Store.open(path, migrate=True) as store:
            index = 0
            for identity in (primary, secondary):
                for market in (Market.KR, Market.US):
                    index += 1
                    head = open_account(store, identity, market)
                    credited = store.execute(command(identity, "cash.credited", f"credit-{index}",
                        AmountPayload(amount_minor=index), head, market))
                    positioned = store.execute(command(identity, "position.adjusted", f"position-{index}",
                        PositionPayload(symbol=f"SYM{index}", quantity_delta=index,
                                        average_cost_minor=index), credited.event_id, market))
                    _ = store.execute(command(identity, "reservation.placed", f"reserve-{index}",
                        ReservationPayload(reservation_id=f"r{index}", amount_minor=index),
                        positioned.event_id, market))
        with connect(path) as connection:
            balances = connection.execute(
                "SELECT available_cash_minor,reserved_cash_minor FROM account_balances " +
                "ORDER BY account_id,market,arm_id").fetchall()
            positions = connection.execute("SELECT COUNT(*) FROM account_positions").fetchone()
            reservations = connection.execute("SELECT COUNT(*) FROM account_reservations").fetchone()
        if balances != [(100_000, 1), (100_000, 2), (100_000, 3), (100_000, 4)]:
            raise AssertionError(str(balances))
        if positions != (4,) or reservations != (4,):
            raise AssertionError("namespace projections missing")
        return durable_state(path)
