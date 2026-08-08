from __future__ import annotations

from dataclasses import dataclass

from src.v8.reconciliation_models import (
    CompileReconciliationResult,
    ReconciliationArtifact,
    ReconciliationErrorCode,
    ReconciliationRecord,
)
from src.v8.reconciliation_records import rechain_record


@dataclass(frozen=True, slots=True)
class StoredReconciliation:
    idempotency_key: str
    execution_seed_hash: str
    broker_order_ref_hash: str
    artifact: ReconciliationArtifact
    records: tuple[ReconciliationRecord, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationLedger:
    entries: tuple[StoredReconciliation, ...]

    @classmethod
    def empty(cls) -> ReconciliationLedger:
        return cls(())


@dataclass(frozen=True, slots=True)
class AppendReconciliationResult:
    ledger: ReconciliationLedger
    artifact: ReconciliationArtifact | None
    error_code: ReconciliationErrorCode | None
    appended_count: int
    returned_existing: bool


def with_record_prefix(
    artifact: ReconciliationArtifact, count: int
) -> ReconciliationLedger:
    stored = StoredReconciliation(
        idempotency_key=artifact.execution_order.idempotency_key,
        execution_seed_hash=artifact.execution_seed_hash,
        broker_order_ref_hash=artifact.execution_order.broker_order_ref_hash,
        artifact=artifact.model_copy(update={"records": artifact.records[:count]}),
        records=artifact.records[:count],
    )
    return ReconciliationLedger((stored,))


def append_reconciliation(
    ledger: ReconciliationLedger, compiled: CompileReconciliationResult
) -> AppendReconciliationResult:
    artifact = compiled.artifact
    if artifact is None:
        return AppendReconciliationResult(ledger, None, compiled.error_code, 0, False)
    key = artifact.execution_order.idempotency_key
    for index, stored in enumerate(ledger.entries):
        if stored.idempotency_key != key:
            continue
        if stored.execution_seed_hash != artifact.execution_seed_hash:
            return AppendReconciliationResult(
                ledger, None, ReconciliationErrorCode.IDEMPOTENCY_CONFLICT, 0, False
            )
        if stored.broker_order_ref_hash != artifact.execution_order.broker_order_ref_hash:
            return AppendReconciliationResult(
                ledger, None, ReconciliationErrorCode.IDEMPOTENCY_CONFLICT, 0, False
            )
        existing_ids = {record.artifact_id for record in stored.records}
        missing = tuple(
            record for record in artifact.records if record.artifact_id not in existing_ids
        )
        if not missing:
            return AppendReconciliationResult(
                ledger, stored.artifact, compiled.error_code, 0, True
            )
        previous = stored.records[-1].record_hash if stored.records else "sha256:genesis"
        appended: list[ReconciliationRecord] = []
        for record in missing:
            rebuilt = rechain_record(record, previous)
            appended.append(rebuilt)
            previous = rebuilt.record_hash
        records = (*stored.records, *appended)
        updated_artifact = artifact.model_copy(update={"records": records})
        updated = StoredReconciliation(
            key,
            artifact.execution_seed_hash,
            artifact.execution_order.broker_order_ref_hash,
            updated_artifact,
            records,
        )
        entries = (*ledger.entries[:index], updated, *ledger.entries[index + 1 :])
        return AppendReconciliationResult(
            ReconciliationLedger(entries), updated_artifact, compiled.error_code, len(appended), False
        )
    stored = StoredReconciliation(
        key,
        artifact.execution_seed_hash,
        artifact.execution_order.broker_order_ref_hash,
        artifact,
        artifact.records,
    )
    return AppendReconciliationResult(
        ReconciliationLedger((*ledger.entries, stored)),
        artifact,
        compiled.error_code,
        len(artifact.records),
        False,
    )


def request_reorder(ledger: ReconciliationLedger, idempotency_key: str) -> ReconciliationErrorCode | None:
    for stored in ledger.entries:
        if (
            stored.idempotency_key == idempotency_key
            and stored.artifact.order_status == "unknown"
        ):
            return ReconciliationErrorCode.REORDER_BLOCKED_UNDER_UNKNOWN
    return None
