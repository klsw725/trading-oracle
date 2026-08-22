from __future__ import annotations

from .canonical import JsonValue, canonical_hash
from .database import Connection
from .models import AccountNamespace
from .reducers import AccountState


def state_value(namespace: AccountNamespace, state: AccountState) -> JsonValue:
    return {
        "namespace": namespace.model_dump(mode="json"),
        "available_cash_minor": state.available_cash_minor,
        "reserved_cash_minor": state.reserved_cash_minor,
        "positions": [
            {"symbol": item.symbol, "quantity": item.quantity,
             "average_cost_minor": item.average_cost_minor}
            for item in state.positions
        ],
        "reservations": [
            {"reservation_id": item.reservation_id, "amount_minor": item.amount_minor,
             "status": item.status, "created_event_sequence": item.created_event_sequence,
             "created_event_hash": item.created_event_hash,
             "created_event_id": item.created_event_id,
             "released_event_sequence": item.released_event_sequence,
             "released_event_hash": item.released_event_hash,
             "released_event_id": item.released_event_id}
            for item in state.reservations
        ],
        "sequence": state.sequence,
        "event_hash": state.event_hash,
    }


def projection_hash(namespace: AccountNamespace, state: AccountState) -> str:
    return canonical_hash(state_value(namespace, state))


def write_projection(
    connection: Connection, namespace: AccountNamespace, state: AccountState
) -> None:
    key = (namespace.account_id, namespace.market.value, namespace.currency.value, namespace.arm_id)
    _ = connection.execute(
        "INSERT INTO account_balances VALUES(?,?,?,?,?,?) " +
        "ON CONFLICT(account_id,market,currency,arm_id) DO UPDATE SET " +
        "available_cash_minor=excluded.available_cash_minor,reserved_cash_minor=excluded.reserved_cash_minor",
        (*key, state.available_cash_minor, state.reserved_cash_minor),
    )
    _ = connection.execute(
        "DELETE FROM account_positions WHERE account_id=? AND market=? AND currency=? AND arm_id=?", key
    )
    _ = connection.executemany(
        "INSERT INTO account_positions VALUES(?,?,?,?,?,?,?)",
        ((*key, item.symbol, item.quantity, item.average_cost_minor) for item in state.positions),
    )
    _ = connection.execute(
        "DELETE FROM account_reservations WHERE account_id=? AND market=? AND currency=? AND arm_id=?", key
    )
    _ = connection.executemany(
        "INSERT INTO account_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ((*key, item.reservation_id, item.amount_minor, item.status,
          item.created_event_sequence, item.created_event_hash, item.created_event_id,
          item.released_event_sequence, item.released_event_hash, item.released_event_id)
         for item in state.reservations),
    )
    _ = connection.execute(
        "UPDATE accounts SET head_sequence=?,head_event_hash=? WHERE " +
        "account_id=? AND market=? AND currency=? AND arm_id=?",
        (state.sequence, state.event_hash, *key),
    )


def checkpoint(
    connection: Connection, namespace: AccountNamespace, state: AccountState
) -> None:
    key = (namespace.account_id, namespace.market.value, namespace.currency.value, namespace.arm_id)
    _ = connection.execute(
        "INSERT INTO projection_checkpoints VALUES(?,?,?,?,?,?) " +
        "ON CONFLICT(account_id,market,currency,arm_id) DO UPDATE SET " +
        "sequence=excluded.sequence,event_hash=excluded.event_hash",
        (*key, state.sequence, state.event_hash),
    )
