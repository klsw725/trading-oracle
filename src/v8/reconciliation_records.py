from __future__ import annotations

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash
from src.v8.identity import model_json
from src.v8.reconciliation_identity import rebuild_reconciliation
from src.v8.reconciliation_models import (
    BrokerTruth,
    ExecutionOrder,
    FillFragment,
    OrderStatus,
    PortfolioDelta,
    Reconciliation,
    ReconciliationArtifact,
    ReconciliationErrorCode,
    ReconciliationRecord,
)

type RecordPart = tuple[
    str, str, OrderStatus, ExecutionOrder | BrokerTruth | FillFragment | PortfolioDelta | Reconciliation
]


def build_records(
    source_hash: str,
    order: ExecutionOrder,
    truth: BrokerTruth | None,
    fills: tuple[FillFragment, ...],
    delta: PortfolioDelta | None,
    reconciliation: Reconciliation,
) -> tuple[ReconciliationRecord, ...]:
    parts: list[RecordPart] = [
        ("execution_order", order.execution_order_id, order.order_status, order)
    ]
    if truth is not None:
        parts.append(("broker_truth", truth.broker_truth_id, truth.order_status, truth))
    parts.extend(
        ("fill_fragment", fill.fill_fragment_id, reconciliation.order_status, fill)
        for fill in fills
    )
    if delta is not None:
        parts.append(
            ("portfolio_delta", delta.portfolio_delta_id, delta.order_status, delta)
        )
    parts.append(
        (
            "reconciliation",
            reconciliation.order_reconciliation_id,
            reconciliation.order_status,
            reconciliation,
        )
    )
    previous = "sha256:genesis"
    records: list[ReconciliationRecord] = []
    for artifact_type, artifact_id, status, payload in parts:
        seed: JsonValue = {
            "schema_version": "v8.order_reconciliation.record.1",
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "order_status": status,
            "payload": model_json(payload),
            "source_hashes": [source_hash],
            "prev_record_hash": previous,
        }
        record = ReconciliationRecord.model_validate(
            {**seed, "record_hash": canonical_hash(seed)}
        )
        records.append(record)
        previous = record.record_hash
    return tuple(records)


def rechain_record(
    record: ReconciliationRecord, previous_hash: str
) -> ReconciliationRecord:
    seed = model_json(record, exclude={"record_hash", "prev_record_hash"})
    assert isinstance(seed, dict)
    seed["prev_record_hash"] = previous_hash
    return ReconciliationRecord.model_validate(
        {**seed, "record_hash": canonical_hash(seed)}
    )


def _canonical_unknown_transition(
    record: ReconciliationRecord, artifact: ReconciliationArtifact
) -> bool:
    if record.artifact_type != "reconciliation" or record.order_status != "unknown":
        return False
    try:
        historical = Reconciliation.model_validate(record.payload)
    except ValidationError:
        return False
    rebuilt = rebuild_reconciliation(
        historical,
        artifact.execution_order,
        "unknown",
        "sha256:genesis",
        artifact.execution_order.record_hash,
    )
    return (
        rebuilt == historical
        and record.artifact_id == historical.order_reconciliation_id
        and record.payload == model_json(historical)
        and historical.quality_result == "fail"
        and historical.mismatch_count == len(historical.mismatches) == 1
        and historical.operator_review_required
        and historical.allowed_next_action
        == "refresh_broker_truth_for_same_ref_hash"
        and historical.expected_arithmetic is None
    )


def inventory_errors(
    artifact: ReconciliationArtifact,
) -> list[ReconciliationErrorCode]:
    canonical = build_records(
        artifact.source_input_hash,
        artifact.execution_order,
        artifact.broker_truth,
        artifact.fill_fragments,
        artifact.portfolio_delta,
        artifact.reconciliation,
    )
    chain_fields = {"source_hashes", "prev_record_hash", "record_hash"}
    expected = tuple(model_json(record, exclude=chain_fields) for record in canonical)
    observed = tuple(
        model_json(record, exclude=chain_fields) for record in artifact.records
    )
    if observed == expected:
        return []
    legal_recovery = (
        len(observed) == len(expected) + 1
        and observed[:1] == expected[:1]
        and observed[2:] == expected[1:]
        and _canonical_unknown_transition(artifact.records[1], artifact)
    )
    if legal_recovery:
        return []
    expected_ids = {record.artifact_id for record in canonical}
    fill_payloads = tuple(
        record.payload for record in canonical if record.artifact_type == "fill_fragment"
    )
    if any(
        record.artifact_type == "fill_fragment"
        and record.artifact_id not in expected_ids
        and record.payload in fill_payloads
        for record in artifact.records
    ):
        return [ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT]
    return [ReconciliationErrorCode.RECORD_HASH_MISMATCH]
