from __future__ import annotations

from pydantic import TypeAdapter
from src.v16.models import Market

from .canonical import JsonValue, canonical_hash, parse_json
from .database import Connection
from .errors import V17Error
from .event_log import namespace_key
from .models import AccountNamespace, Currency
from .projections import projection_hash, state_value
from .reducers import AccountState, Position, Reservation
from .replay import replay_namespace

_ACCOUNT = TypeAdapter(tuple[str, str, str, str, str, int, str, str, str, int, str])
_BALANCE = TypeAdapter(tuple[int, int])
_POSITION = TypeAdapter(tuple[str, int, int])
_RESERVATION = TypeAdapter(
    tuple[str, int, str, int, str, str, int | None, str | None, str | None]
)
_CHECKPOINT = TypeAdapter(tuple[int, str])
_IDEMPOTENCY = TypeAdapter(
    tuple[str, str, str, str, str, str, str, str, str, str, int, str, str, str, str]
)
_EVENT_REF = TypeAdapter(tuple[str, str, str, str, str, str])


def _namespace(row: tuple[str, str, str, str, str, int, str, str, str, int, str]) -> AccountNamespace:
    return AccountNamespace(account_id=row[0], market=Market(row[1]),
                            currency=Currency(row[2]), arm_id=row[3])


def _stored_state(connection: Connection, namespace: AccountNamespace) -> AccountState:
    key = namespace_key(namespace)
    balance_raw = connection.execute(
        "SELECT available_cash_minor,reserved_cash_minor FROM account_balances WHERE " +
        "account_id=? AND market=? AND currency=? AND arm_id=?", key).fetchone()
    checkpoint_raw = connection.execute(
        "SELECT sequence,event_hash FROM projection_checkpoints WHERE " +
        "account_id=? AND market=? AND currency=? AND arm_id=?", key).fetchone()
    if balance_raw is None or checkpoint_raw is None:
        raise V17Error("RECONCILIATION_FAILED", "missing projection")
    balance = _BALANCE.validate_python(balance_raw)
    checkpoint = _CHECKPOINT.validate_python(checkpoint_raw)
    positions = tuple(Position(*_POSITION.validate_python(row)) for row in connection.execute(
        "SELECT symbol,quantity,average_cost_minor FROM account_positions WHERE " +
        "account_id=? AND market=? AND currency=? AND arm_id=? ORDER BY symbol", key))
    reservations = tuple(Reservation(*_RESERVATION.validate_python(row)) for row in connection.execute(
        "SELECT reservation_id,amount_minor,status,created_event_sequence,created_event_hash," +
        "created_event_id,released_event_sequence,released_event_hash,released_event_id " +
        "FROM account_reservations WHERE account_id=? AND market=? AND currency=? AND arm_id=? " +
        "ORDER BY reservation_id", key))
    return AccountState(balance[0], balance[1], positions, reservations,
                        checkpoint[0], checkpoint[1])


def _result(value: JsonValue) -> tuple[str, int, str]:
    match value:  # noqa: MATCH_OK - persisted result boundary.
        case {"event_id": str(event_id), "sequence": int(sequence),
              "projection_hash": str(projected)} if not isinstance(sequence, bool):
            return event_id, sequence, projected
        case _:
            raise V17Error("IDEMPOTENCY_RESULT_INVALID", "result_json")


def _verify_idempotency(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT account_id,market,currency,arm_id,command_type,command_id,config_version," +
        "policy_version,semantic_key,request_hash,event_sequence,event_hash,event_id," +
        "result_json,result_hash FROM idempotency_keys " +
        "ORDER BY account_id,market,currency,arm_id,command_type,command_id"
    )
    for raw in rows:
        row = _IDEMPOTENCY.validate_python(raw)
        namespace = AccountNamespace(account_id=row[0], market=Market(row[1]),
                                     currency=Currency(row[2]), arm_id=row[3])
        namespace_value: JsonValue = {"account_id": row[0], "market": row[1],
                                      "currency": row[2], "arm_id": row[3]}
        expected_semantic = canonical_hash({"command_type": row[4],
            "namespace": namespace_value, "command_id": row[5],
            "config_version": row[6], "policy_version": row[7]})
        result_value = parse_json(row[13])
        result_event_id, result_sequence, result_projection = _result(result_value)
        if row[8] != expected_semantic or row[14] != canonical_hash(result_value):
            raise V17Error("IDEMPOTENCY_DRIFT", row[8])
        if (row[10], row[12]) != (result_sequence, result_event_id):
            raise V17Error("IDEMPOTENCY_EVENT_MISMATCH", row[8])
        event_raw = connection.execute(
            "SELECT runtime_identity,effective_at,payload_json,previous_event_hash,event_type," +
            "semantic_key FROM events WHERE account_id=? AND market=? AND currency=? AND arm_id=? " +
            "AND sequence=? AND event_hash=? AND event_id=?",
            (*namespace_key(namespace), row[10], row[11], row[12]),
        ).fetchone()
        if event_raw is None:
            raise V17Error("IDEMPOTENCY_EVENT_MISSING", row[8])
        event = _EVENT_REF.validate_python(event_raw)
        expected_request = canonical_hash({"runtime_identity": event[0],
            "effective_at": event[1], "payload": parse_json(event[2]), "precondition": event[3]})
        expected_projection = projection_hash(
            namespace, replay_namespace(connection, namespace, row[10]))
        if event[4] != row[4] or event[5] != row[8] or row[9] != expected_request:
            raise V17Error("IDEMPOTENCY_REQUEST_DRIFT", row[8])
        if result_projection != expected_projection:
            raise V17Error("IDEMPOTENCY_PROJECTION_DRIFT", row[8])


def _verify_foreign_keys(connection: Connection) -> None:
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise V17Error("FOREIGN_KEY_VIOLATION", canonical_hash(
            [[str(value) for value in row] for row in violations]))


def reconcile(connection: Connection) -> str:
    _verify_foreign_keys(connection)
    accounts = tuple(_ACCOUNT.validate_python(row) for row in connection.execute(
        "SELECT account_id,market,currency,arm_id,mode,opening_cash_minor,runtime_identity," +
        "config_version,policy_version,head_sequence,head_event_hash FROM accounts " +
        "ORDER BY account_id,market,currency,arm_id"))
    values: list[JsonValue] = []
    for account in accounts:
        namespace = _namespace(account)
        replayed = replay_namespace(connection, namespace)
        if replayed != _stored_state(connection, namespace):
            raise V17Error("RECONCILIATION_FAILED", namespace.selector())
        if (account[9], account[10]) != (replayed.sequence, replayed.event_hash):
            raise V17Error("RECONCILIATION_FAILED", "account head")
        opening = connection.execute(
            "SELECT payload_json FROM events WHERE account_id=? AND market=? AND currency=? " +
            "AND arm_id=? AND sequence=1", namespace_key(namespace)).fetchone()
        if opening != (f'{{"opening_cash_minor":{account[5]}}}',) or account[4] != "paper":
            raise V17Error("ACCOUNT_OPENING_MISMATCH", namespace.selector())
        identities = connection.execute(
            "SELECT DISTINCT runtime_identity,config_version,policy_version FROM events WHERE " +
            "account_id=? AND market=? AND currency=? AND arm_id=?", namespace_key(namespace)
        ).fetchall()
        expected_identity = {(account[6], account[7], account[8])}
        observed = {TypeAdapter(tuple[str, str, str]).validate_python(row) for row in identities}
        if observed != expected_identity:
            raise V17Error("ACCOUNT_IDENTITY_MISMATCH", namespace.selector())
        values.append(state_value(namespace, replayed))
    _verify_idempotency(connection)
    return canonical_hash(values)
