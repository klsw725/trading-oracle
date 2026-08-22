from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pydantic import ValidationError

from .acceptance_support import (
    EVENT_UPDATE_TRIGGER_SQL,
    command,
    database,
    durable_state,
    expect_failure,
    open_account,
    tamper,
)
from .database import connect
from .database import configure
from .canonical import canonical_hash, canonical_json, parse_json
from .cli_contract import run_cli
from .errors import V17Error
from .faults import FaultPoint
from .fixtures import identities
from .models import AmountPayload
from .migrations import MIGRATIONS
from .migrations import migrate_database
from .replay import replay_database
from .schema_fingerprint import statements as sql_statements
from .store import Store, verify_database


def integrity_checks() -> tuple[tuple[str, str], ...]:
    return tuple(sorted((
        ("event_only_replay_ignores_projection_drift", _replay_drift()),
        ("event_only_replay_ignores_account_drift", _replay_account_drift()),
        ("exact_schema_fingerprint", _schema_drift()),
        ("forged_runtime_identity_rejected", _forged_identity()),
        ("unknown_event_type_rejected", _event_field("event_type='unknown'", "UNKNOWN_EVENT_TYPE")),
        ("unknown_event_schema_rejected", _event_field(
            "event_schema_version='unknown'", "UNKNOWN_EVENT_SCHEMA")),
        ("unknown_event_policy_rejected", _event_field(
            "policy_version='unknown'", "UNKNOWN_EVENT_POLICY")),
        ("idempotency_event_reference_drift", _idempotency_reference()),
        ("idempotency_full_reconciliation", _idempotency_fields()),
        ("migration_pragmas_verified", _migration_pragmas()),
        ("store_baseexception_cleanup", _system_exit_cleanup()),
        ("store_validationerror_cleanup", _validation_cleanup()),
        ("store_open_failure_closes", _open_cleanup()),
        ("cli_failure_stdout_contract", _cli_failure_stdout()),
    )))


def _replay_drift() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            _ = store.execute(command(identity, "cash.credited", "credit",
                                      AmountPayload(amount_minor=7), head))
        expected = replay_database(path)
        tamper(path, ("UPDATE account_balances SET available_cash_minor=1",))
        _ = expect_failure(lambda: verify_database(path), {"RECONCILIATION_FAILED"})
        replayed = replay_database(path)
        if replayed != expected:
            raise AssertionError("event-only replay changed")
        return replayed


def _replay_account_drift() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            _ = open_account(store, identity)
        expected = replay_database(path)
        tamper(path, ("UPDATE accounts SET runtime_identity='sha256:forged'",))
        _ = expect_failure(lambda: verify_database(path), {"ACCOUNT_IDENTITY_MISMATCH"})
        replayed = replay_database(path)
        if replayed != expected:
            raise AssertionError("event-only replay used account rows")
        return replayed


def _schema_drift() -> str:
    probes = (
        ("DROP TRIGGER events_immutable_update",),
        ("CREATE TABLE extra_table(value INTEGER)",),
        ("CREATE INDEX extra_index ON events(event_type)",),
        ("DROP TABLE account_positions",),
    )
    for statements in probes:
        with database() as path:
            with Store.open(path, migrate=True):
                pass
            tamper(path, statements)
            _ = expect_failure(lambda: Store.open(path), {
                "SCHEMA_FINGERPRINT_MISMATCH", "SCHEMA_OBJECT_INVENTORY_MISMATCH"})
    with database() as path:
        connection = connect(path)
        try:
            configure(connection, writable=True)
            source = (Path(__file__).with_name("migrations") / "001_initial.sql").read_text()
            changed = source.replace("opening_cash_minor>=0", "opening_cash_minor>0")
            for statement in sql_statements(changed):
                _ = connection.execute(statement)
            migration = MIGRATIONS[0]
            _ = connection.execute(
                "INSERT INTO schema_migrations(version,name,sha256) VALUES(?,?,?)",
                (migration.version, migration.name, migration.sha256),
            )
            _ = connection.execute("PRAGMA user_version=1")
        finally:
            connection.close()
        _ = expect_failure(lambda: Store.open(path), {"SCHEMA_FINGERPRINT_MISMATCH"})
    return "MISSING_EXTRA_CHANGED_REJECTED"


def _forged_identity() -> str:
    identity = identities()[0]
    forged = identity.model_copy(update={"runtime_identity": "sha256:" + "f" * 64})
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        before = durable_state(path)
        operation = command(forged, "cash.credited", "forged",
                            AmountPayload(amount_minor=1), head)
        code = expect_failure(lambda: store.execute(operation),
                              {"RUNTIME_IDENTITY_HASH_MISMATCH"})
        if durable_state(path) != before:
            raise AssertionError("forged identity mutated state")
        return code


def _event_field(assignment: str, code: str) -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            _ = open_account(store, identity)
        tamper(path, ("DROP TRIGGER events_immutable_update",
                      f"UPDATE events SET {assignment} WHERE sequence=1",
                      EVENT_UPDATE_TRIGGER_SQL))
        return expect_failure(lambda: Store.open(path), {code})


def _idempotency_reference() -> str:
    identity = identities()[0]
    with database() as path:
        with Store.open(path, migrate=True) as store:
            head = open_account(store, identity)
            _ = store.execute(command(identity, "cash.credited", "credit",
                                      AmountPayload(amount_minor=1), head))
        with connect(path) as connection:
            second = connection.execute(
                "SELECT sequence,event_hash,event_id FROM events WHERE sequence=2").fetchone()
            if second is None:
                raise AssertionError("missing second event")
            _ = connection.execute(
                "UPDATE idempotency_keys SET event_sequence=?,event_hash=?,event_id=? " +
                "WHERE command_type='account.opened'", second)
        return expect_failure(lambda: Store.open(path), {"IDEMPOTENCY_EVENT_MISMATCH"})


def _idempotency_fields() -> str:
    probes = (
        ("UPDATE idempotency_keys SET request_hash='sha256:bad' WHERE event_sequence=2",
         "IDEMPOTENCY_REQUEST_DRIFT"),
        ("UPDATE idempotency_keys SET semantic_key='sha256:bad' WHERE event_sequence=2",
         "IDEMPOTENCY_DRIFT"),
    )
    for statement, code in probes:
        with database() as path:
            _idempotent_database(path)
            tamper(path, (statement,))
            _ = expect_failure(lambda: Store.open(path), {code})
    with database() as path:
        _idempotent_database(path)
        with connect(path) as connection:
            row = connection.execute(
                "SELECT result_json FROM idempotency_keys WHERE event_sequence=2").fetchone()
            if row is None or not isinstance(row[0], str):
                raise AssertionError("missing idempotency result")
            result = parse_json(row[0])
            if not isinstance(result, dict):
                raise AssertionError("invalid idempotency result")
            changed = {**result, "projection_hash": "sha256:" + "f" * 64}
            result_json = canonical_json(changed).decode("utf-8")
            _ = connection.execute(
                "UPDATE idempotency_keys SET result_json=?,result_hash=? WHERE event_sequence=2",
                (result_json, canonical_hash(changed)),
            )
        _ = expect_failure(lambda: Store.open(path), {"IDEMPOTENCY_PROJECTION_DRIFT"})
    return "EVENT_NAMESPACE_SEMANTIC_SEQUENCE_PROJECTION_REQUEST_VERIFIED"


def _idempotent_database(path: Path) -> None:
    identity = identities()[0]
    with Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        _ = store.execute(command(identity, "cash.credited", "credit",
                                  AmountPayload(amount_minor=1), head))


def _migration_pragmas() -> str:
    with database() as path:
        _ = migrate_database(path)
        values: tuple[tuple[str | int | float | bytes | None, ...] | None, ...] = ()
        with connect(path) as connection:
            configure(connection, writable=True)
            values = tuple(connection.execute(f"PRAGMA {name}").fetchone()
                           for name in ("foreign_keys", "journal_mode", "synchronous",
                                        "busy_timeout"))
        if values != ((1,), ("wal",), (2,), (5000,)):
            raise AssertionError(str(values))
        return "SET_AND_VERIFIED"


class _ExitFault:
    def hit(self, point: FaultPoint) -> None:
        if point == "after_event_insert":
            raise SystemExit(17)


def _system_exit_cleanup() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        before = durable_state(path)
        operation = command(identity, "cash.credited", "exit",
                            AmountPayload(amount_minor=1), head)
        try:
            _ = store.execute(operation, _ExitFault())
        except SystemExit as error:
            if error.code != 17:
                raise
        else:
            raise AssertionError("SystemExit not propagated")
        if durable_state(path) != before:
            raise AssertionError("SystemExit transaction survived")
        _ = store.execute(command(identity, "cash.credited", "after-exit",
                                  AmountPayload(amount_minor=1), head))
        return "ROLLED_BACK_PROPAGATED_REUSABLE"


def _validation_cleanup() -> str:
    identity = identities()[0]
    with database() as path, Store.open(path, migrate=True) as store:
        head = open_account(store, identity)
        tamper(path, ("UPDATE accounts SET opening_cash_minor='invalid'",))
        operation = command(identity, "cash.credited", "validation",
                            AmountPayload(amount_minor=1), head)
        try:
            _ = store.execute(operation)
        except ValidationError as error:
            observed = error
        else:
            raise AssertionError("ValidationError not propagated")
        if not observed.errors():
            raise AssertionError("empty ValidationError")
        tamper(path, ("UPDATE accounts SET opening_cash_minor=100000",))
        _ = store.execute(operation)
        return "ROLLED_BACK_PROPAGATED_REUSABLE"


def _open_cleanup() -> str:
    with database() as path:
        with Store.open(path, migrate=True):
            pass
        tamper(path, ("DROP TRIGGER events_immutable_update",))
        _ = expect_failure(lambda: Store.open(path), {"SCHEMA_FINGERPRINT_MISMATCH"})
        with connect(path) as connection:
            _ = connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()
        return "CONNECTION_CLOSED"


def _cli_failure_stdout() -> str:
    def invalid_dispatch(_arguments: list[str]):
        raise V17Error("CLI_USAGE_ERROR", "invalid arguments")

    stdout, stderr = BytesIO(), BytesIO()
    code = run_cli(["unknown-command"], stdout, stderr, invalid_dispatch)
    expected = canonical_json({"code": "CLI_USAGE_ERROR", "schema_version": "v17.error.1",
                               "status": "FAIL"}) + b"\n"
    if code != 2 or stdout.getvalue() != expected or stderr.getvalue():
        raise AssertionError("CLI failure stream contract")
    return "EXIT_2_CANONICAL_STDOUT_EMPTY_STDERR"
