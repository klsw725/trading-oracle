from typing import Literal

from src.v6.models import BoundaryModel

from .models import HashText
from .source_events import AuditEvent, event_hash
from .source_models import SourcePolicyError


class OperationLedgerEntry(BoundaryModel):
    operation_id: str
    idempotency_key: str
    operation_hash: HashText
    event_hash: HashText
    policy_hash: HashText


class OperationLedgerBody(BoundaryModel):
    schema_version: Literal["v7.source-policy.operation-ledger.1"]
    entries: tuple[OperationLedgerEntry, ...]


class OperationLedger(OperationLedgerBody):
    ledger_hash: HashText


def empty_ledger() -> OperationLedger:
    body = OperationLedgerBody(schema_version="v7.source-policy.operation-ledger.1", entries=())
    return OperationLedger.model_validate({**body.model_dump(mode="json"), "ledger_hash": event_hash(body)})


def append_ledger(ledger: OperationLedger, event: AuditEvent) -> OperationLedger:
    entry = OperationLedgerEntry(operation_id=event.payload.operation_id, idempotency_key=event.payload.idempotency_key, operation_hash=event.payload.operation_hash, event_hash=event.audit_event_hash, policy_hash=event.payload.new_policy_hash)
    body = OperationLedgerBody(schema_version="v7.source-policy.operation-ledger.1", entries=(*ledger.entries, entry))
    return OperationLedger.model_validate({**body.model_dump(mode="json"), "ledger_hash": event_hash(body)})


def verify_ledger(ledger: OperationLedger) -> None:
    body = OperationLedgerBody.model_validate(ledger.model_dump(mode="json", exclude={"ledger_hash"}))
    if ledger.ledger_hash != event_hash(body):
        raise SourcePolicyError("HISTORY_HASH_MISMATCH", "operation ledger")
    identities = tuple((entry.operation_id, entry.idempotency_key) for entry in ledger.entries)
    if len(identities) != len(set(identities)):
        raise SourcePolicyError("DUPLICATE_OPERATION_CONFLICT", "operation ledger")
