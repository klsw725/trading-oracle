from __future__ import annotations

from dataclasses import dataclass

from src.v4.models import JsonValue, canonical_hash
from src.v8.approval_models import (
    ApprovalArtifact,
    ApprovalErrorCode,
    ApprovalFixture,
    ApprovalRecord,
    ApprovalStatus,
    CompileApprovalResult,
    IdempotencyIndexEntry,
)
from src.v8.identity import model_json


def build_approval_artifact(
    fixture: ApprovalFixture, source_hash: str, proposal_seed_hash: str
) -> ApprovalArtifact:
    response = fixture.broker_dry_run_response
    assert response is not None
    parts: tuple[tuple[str, str, ApprovalStatus, JsonValue], ...] = (
        ("proposal", fixture.proposed_order.proposed_order_id, "proposed", model_json(fixture.proposed_order)),
        ("checklist", fixture.checklist.checklist_id, "checklisted", model_json(fixture.checklist)),
        ("decision", fixture.approval_decision.approval_decision_id, "approved", model_json(fixture.approval_decision)),
        ("dry_run_request", fixture.dry_run_request.dry_run_request_id, "dry_run_requested", model_json(fixture.dry_run_request)),
        ("dry_run_response", response.dry_run_response_id, "dry_run_passed", model_json(response)),
    )
    records: list[ApprovalRecord] = []
    previous = "sha256:genesis"
    for artifact_type, artifact_id, status, payload in parts:
        seed: JsonValue = {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "approval_status": status,
            "payload": payload,
            "source_hashes": [source_hash],
            "prev_record_hash": previous,
        }
        record = ApprovalRecord.model_validate(
            {**seed, "record_hash": canonical_hash(seed)}
        )
        records.append(record)
        previous = record.record_hash
    index = IdempotencyIndexEntry(
        idempotency_key=fixture.proposed_order.idempotency_key,
        proposal_seed_hash=proposal_seed_hash,
        proposed_order_id=fixture.proposed_order.proposed_order_id,
        approval_decision_id=fixture.approval_decision.approval_decision_id,
        dry_run_request_id=fixture.dry_run_request.dry_run_request_id,
        dry_run_response_id=response.dry_run_response_id,
        approval_status="dry_run_passed",
        response_hash=canonical_hash(model_json(response)),
    )
    return ApprovalArtifact(
        schema_version="v8.operator_approval_dry_run.artifact.1",
        approval_status="dry_run_passed",
        source_input_hash=source_hash,
        proposed_order=fixture.proposed_order,
        checklist=fixture.checklist,
        approval_decision=fixture.approval_decision,
        dry_run_request=fixture.dry_run_request,
        broker_dry_run_response=response,
        records=tuple(records),
        idempotency_index_entry=index,
        live_submission=False,
        would_accept=True,
        real_order_created=False,
        portfolio_mutated=False,
    )


@dataclass(frozen=True, slots=True)
class StoredApproval:
    idempotency_key: str
    request_seed_hash: str
    artifact: ApprovalArtifact


@dataclass(frozen=True, slots=True)
class ApprovalLedger:
    entries: tuple[StoredApproval, ...]

    @classmethod
    def empty(cls) -> ApprovalLedger:
        return cls(())


@dataclass(frozen=True, slots=True)
class AppendApprovalResult:
    ledger: ApprovalLedger
    artifact: ApprovalArtifact | None
    error_code: ApprovalErrorCode | None
    returned_existing: bool


def append_approval_request(
    ledger: ApprovalLedger, compiled: CompileApprovalResult
) -> AppendApprovalResult:
    if compiled.artifact is None:
        return AppendApprovalResult(ledger, None, compiled.error_code, False)
    artifact = compiled.artifact
    seed_hash = canonical_hash(request_seed_from_artifact(artifact))
    for stored in ledger.entries:
        if stored.idempotency_key != artifact.proposed_order.idempotency_key:
            continue
        if stored.request_seed_hash == seed_hash:
            return AppendApprovalResult(ledger, stored.artifact, None, True)
        return AppendApprovalResult(
            ledger, None, ApprovalErrorCode.IDEMPOTENCY_CONFLICT, False
        )
    stored = StoredApproval(
        artifact.proposed_order.idempotency_key, seed_hash, artifact
    )
    return AppendApprovalResult(
        ApprovalLedger((*ledger.entries, stored)), artifact, None, False
    )


def request_seed_from_artifact(artifact: ApprovalArtifact) -> JsonValue:
    fixture_seed: JsonValue = {
        "schema_version": artifact.proposed_order.schema_version,
        "paper_order_id": artifact.proposed_order.paper_order_id,
        "ticker": artifact.proposed_order.ticker,
        "side": artifact.proposed_order.side,
        "order_type": artifact.proposed_order.order_type,
        "quantity": str(artifact.proposed_order.quantity),
        "limit_price": (
            str(artifact.proposed_order.limit_price)
            if artifact.proposed_order.limit_price is not None
            else None
        ),
        "quote_id": artifact.proposed_order.quote_ref.quote_id,
        "quote_as_of": artifact.proposed_order.quote_ref.quote_as_of.isoformat(),
        "idempotency_key": artifact.proposed_order.idempotency_key,
    }
    result: dict[str, JsonValue] = {
        "proposal": fixture_seed,
        "approver": artifact.approval_decision.approved_by,
        "approved_role": artifact.approval_decision.approved_role,
    }
    return result
