from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import final

from .accounts import verify_identity_membership
from .canonical import canonical_hash, canonical_json, parse_json
from .canonical import JsonValue
from .database import Connection, SqlValue, configure, connect
from .errors import V17Error
from .event_log import append, namespace_key
from .events import build_event
from .faults import FaultInjector, hit
from .idempotency import request_hash, semantic_key
from .identity import verify_runtime_identity
from .migrations import migrate_database, validate_schema
from .models import (
    AmountPayload,
    Command,
    CommandResult,
    OpenedPayload,
    PositionPayload,
    ReservationPayload,
)
from .projections import checkpoint, projection_hash, write_projection
from .reconciliation import reconcile
from .reducers import apply_event
from .replay import replay_namespace
from .schema import GENESIS_HASH, require_int64


def _validate_command(command: Command) -> None:
    verify_runtime_identity(command.identity)
    if not command.command_id or command.command_id != command.command_id.strip():
        raise V17Error("INVALID_COMMAND_ID", command.command_id)
    if command.policy_version != command.identity.policy_version:
        raise V17Error("UNKNOWN_EVENT_POLICY", command.policy_version)
    match command.payload:  # noqa: MATCH_OK - release payload carries no integer to validate.
        case OpenedPayload(opening_cash_minor=value):
            _ = require_int64(value, "opening_cash_minor")
        case AmountPayload(amount_minor=value):
            _ = require_int64(value, "amount_minor")
        case PositionPayload(quantity_delta=quantity, average_cost_minor=cost):
            _ = require_int64(quantity, "quantity_delta")
            _ = require_int64(cost, "average_cost_minor")
        case ReservationPayload(amount_minor=value):
            _ = require_int64(value, "amount_minor")
        case _:
            return


@final
class Store:
    def __init__(self, path: Path, connection: Connection) -> None:
        self._path = path
        self._connection = connection
        self._closed = False

    @classmethod
    def open(cls, path: Path, *, migrate: bool = False) -> Store:
        if migrate:
            _ = migrate_database(path)
        if not path.is_file():
            raise V17Error("DATABASE_NOT_FOUND", str(path))
        connection = connect(path)
        try:
            configure(connection, writable=True)
            if validate_schema(connection) != 1:
                raise V17Error("MIGRATION_REQUIRED", str(path))
            _ = reconcile(connection)
        except BaseException:  # noqa: BROAD_EXCEPT_OK - resource cleanup then unchanged re-raise.
            connection.close()
            raise
        return cls(path, connection)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, _type: type[BaseException] | None,
                 _value: BaseException | None, _traceback: TracebackType | None) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def execute(self, command: Command, fault: FaultInjector | None = None) -> CommandResult:
        if self._closed:
            raise V17Error("STORE_CLOSED", str(self._path))
        _validate_command(command)
        connection = self._connection
        _ = connection.execute("BEGIN IMMEDIATE")
        try:
            _ = reconcile(connection)
            result = self._execute_transaction(command, fault)
            _ = reconcile(connection)
            connection.commit()
            return result
        except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then unchanged re-raise.
            connection.rollback()
            raise

    def _execute_transaction(self, command: Command, fault: FaultInjector | None) -> CommandResult:
        connection = self._connection
        key = namespace_key(command.namespace)
        semantic = semantic_key(command)
        request = request_hash(command)
        prior = connection.execute(
            "SELECT market,currency,semantic_key,request_hash,event_id,result_json,result_hash " +
            "FROM idempotency_keys WHERE account_id=? AND arm_id=? AND command_type=? AND " +
            "command_id=? AND config_version=? AND policy_version=?",
            (command.namespace.account_id, command.namespace.arm_id, command.command_type,
             command.command_id, command.config_version, command.policy_version),
        ).fetchone()
        if prior is not None:
            return _duplicate_result(prior, command, semantic, request)
        account = connection.execute(
            "SELECT runtime_identity,config_version,policy_version,head_sequence,head_event_hash " +
            "FROM accounts WHERE account_id=? AND market=? AND currency=? AND arm_id=?", key
        ).fetchone()
        verify_identity_membership(command.namespace, command.identity)
        if account is None:
            if command.command_type != "account.opened":
                raise V17Error("ACCOUNT_NOT_OPEN", command.namespace.selector())
            match command.payload:  # noqa: MATCH_OK - opening command requires opening payload.
                case OpenedPayload(opening_cash_minor=opening_cash):
                    pass
                case _:
                    raise V17Error("INVALID_EVENT_PAYLOAD", command.command_type)
            _ = connection.execute(
                "INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (*key, "paper", opening_cash,
                 command.identity.runtime_identity, command.config_version,
                 command.policy_version, None, None),
            )
            sequence, previous, state = 1, GENESIS_HASH, None
        else:
            runtime, config, policy, head_sequence, previous = _account_values(account)
            if (runtime, config, policy) != (command.identity.runtime_identity,
                                             command.config_version, command.policy_version):
                raise V17Error("STALE_RUNTIME_IDENTITY", command.namespace.selector())
            sequence = head_sequence + 1
            state = replay_namespace(connection, command.namespace)
        if command.expected_previous_event_hash != previous:
            raise V17Error("STALE_EVENT_HEAD", command.expected_previous_event_hash)
        event = build_event(command, sequence, semantic, previous)
        updated = apply_event(state, event)
        append(connection, command.namespace, event)
        hit(fault, "after_event_insert")
        result_body: JsonValue = {"event_id": event.event_id, "sequence": event.sequence,
                                  "projection_hash": projection_hash(command.namespace, updated)}
        result_json = canonical_json(result_body).decode("utf-8")
        result_hash = canonical_hash(result_body)
        _ = connection.execute(
            "INSERT INTO idempotency_keys VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*key, command.command_type, command.command_id, command.config_version,
             command.policy_version, semantic, request, event.sequence, event.event_hash,
             event.event_id, result_json, result_hash),
        )
        hit(fault, "after_idempotency_insert")
        write_projection(connection, command.namespace, updated)
        hit(fault, "after_projection_write")
        checkpoint(connection, command.namespace, updated)
        hit(fault, "after_checkpoint")
        return CommandResult(event.event_id, event.sequence, result_hash, False)


def _account_values(row: tuple[SqlValue, ...]) -> tuple[str, str, str, int, str]:
    match row:  # noqa: MATCH_OK - malformed database rows require explicit rejection.
        case (str(runtime), str(config), str(policy), int(sequence), str(previous)):
            return runtime, config, policy, sequence, previous
        case _:
            raise V17Error("DATABASE_ROW_INVALID", "account")


def _duplicate_result(
    row: tuple[SqlValue, ...], command: Command, semantic: str, request: str
) -> CommandResult:
    match row:  # noqa: MATCH_OK - malformed database rows require explicit rejection.
        case (str(market), str(currency), str(stored_semantic), str(stored_request),
              str(event_id), str(result_json), str(result_hash)):
            if (market, currency, stored_semantic, stored_request) != (
                command.namespace.market.value, command.namespace.currency.value, semantic, request
            ):
                raise V17Error("IDEMPOTENCY_CONFLICT", stored_semantic)
            value = parse_json(result_json)
            if canonical_hash(value) != result_hash or not isinstance(value, dict):
                raise V17Error("IDEMPOTENCY_DRIFT", stored_semantic)
            sequence = value.get("sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool):
                raise V17Error("IDEMPOTENCY_RESULT_INVALID", stored_semantic)
            return CommandResult(event_id, sequence, result_hash, True)
        case _:
            raise V17Error("DATABASE_ROW_INVALID", "idempotency")


def verify_database(path: Path) -> str:
    if not path.is_file():
        raise V17Error("DATABASE_NOT_FOUND", str(path))
    connection = connect(f"file:{path}?mode=ro", uri=True)
    try:
        configure(connection, writable=False)
        if validate_schema(connection) != 1:
            raise V17Error("MIGRATION_REQUIRED", str(path))
        return reconcile(connection)
    finally:
        connection.close()


def reject_recovery_source(_payload: bytes) -> None:
    raise V17Error("UNSUPPORTED_RECOVERY_SOURCE", "SQLite events are the only truth")
