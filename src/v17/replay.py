from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter
from src.v16.models import Market

from .canonical import JsonValue, canonical_hash
from .database import Connection, configure, connect
from .event_log import event_from_row, namespace_key, verify_hash
from .errors import V17Error
from .migrations import validate_schema
from .models import AccountNamespace, Currency
from .projections import state_value
from .reducers import AccountState, apply_event
from .schema import GENESIS_HASH

_EVENT_ROW = TypeAdapter(tuple[int, str, str, str, str, str, str, str, str, str, str, str])
_NAMESPACE_ROW = TypeAdapter(tuple[str, str, str, str])
_LINEAGE_ROW = TypeAdapter(tuple[str, str, str])


def replay_namespace(
    connection: Connection, namespace: AccountNamespace, through_sequence: int | None = None
) -> AccountState:
    suffix = "" if through_sequence is None else " AND sequence<=?"
    parameters = namespace_key(namespace) if through_sequence is None else (
        *namespace_key(namespace), through_sequence)
    rows = connection.execute(
        "SELECT sequence,event_schema_version,event_id,event_type,semantic_key,runtime_identity," +
        "config_version,policy_version,effective_at,payload_json,previous_event_hash,event_hash " +
        "FROM events WHERE account_id=? AND market=? AND currency=? AND arm_id=?" + suffix +
        " ORDER BY sequence",
        parameters,
    ).fetchall()
    state: AccountState | None = None
    previous = GENESIS_HASH
    for expected_sequence, raw in enumerate(rows, start=1):
        row = _EVENT_ROW.validate_python(raw)
        event = event_from_row(row)
        if event.sequence != expected_sequence:
            raise V17Error("EVENT_SEQUENCE_GAP", str(event.sequence))
        if event.previous_event_hash != previous:
            raise V17Error("EVENT_CHAIN_MISMATCH", event.event_id)
        verify_hash(namespace, event)
        state = apply_event(state, event)
        previous = event.event_hash
    if state is None:
        raise V17Error("ACCOUNT_EVENT_MISSING", namespace.selector())
    return state


def replay_projection(connection: Connection) -> str:
    rows = connection.execute(
        "SELECT DISTINCT account_id,market,currency,arm_id FROM events " +
        "ORDER BY account_id,market,currency,arm_id"
    ).fetchall()
    values: list[JsonValue] = []
    for raw in rows:
        row = _NAMESPACE_ROW.validate_python(raw)
        namespace = AccountNamespace(account_id=row[0], market=Market(row[1]),
                                     currency=Currency(row[2]), arm_id=row[3])
        lineage = connection.execute(
            "SELECT DISTINCT runtime_identity,config_version,policy_version FROM events WHERE " +
            "account_id=? AND market=? AND currency=? AND arm_id=?",
            namespace_key(namespace),
        ).fetchall()
        observed = {_LINEAGE_ROW.validate_python(item) for item in lineage}
        if len(observed) != 1:
            raise V17Error("ACCOUNT_IDENTITY_MISMATCH", namespace.selector())
        values.append(state_value(namespace, replay_namespace(connection, namespace)))
    return canonical_hash(values)


def replay_database(path: Path) -> str:
    if not path.is_file():
        raise V17Error("DATABASE_NOT_FOUND", str(path))
    connection = connect(f"file:{path}?mode=ro", uri=True)
    try:
        configure(connection, writable=False)
        if validate_schema(connection) != 1:
            raise V17Error("MIGRATION_REQUIRED", str(path))
        return replay_projection(connection)
    finally:
        connection.close()
