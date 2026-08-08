from __future__ import annotations

from typing import Final

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash
from src.v8.approval_compiler import (
    rebuild_approval_identities,
    request_seed,
)
from src.v8.approval_ledger import build_approval_artifact
from src.v8.approval_models import (
    ApprovalArtifact,
    ApprovalContractError,
    ApprovalErrorCode,
    ApprovalFixture,
    ApprovalVerificationResult,
    ExpectedApprovalReplay,
    ExpectedIndexEntry,
)
from src.v8.identity import deterministic_id, model_json


_FORBIDDEN_KEYS: Final = frozenset(
    {
        "access_token",
        "account_number",
        "broker_order_id",
        "client_secret",
        "live_order_id",
        "state",
        "stage",
    }
)


def _forbidden_keys(value: JsonValue) -> tuple[str, ...]:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            own = tuple(sorted(_FORBIDDEN_KEYS.intersection(record)))
            return own + tuple(
                key for child in record.values() for key in _forbidden_keys(child)
            )
        case list() as items:
            return tuple(key for child in items for key in _forbidden_keys(child))
        case None | bool() | int() | float() | str():
            return ()


def _fixture_from_artifact(
    artifact: ApprovalArtifact,
    fixture_name: str,
    forbidden_fields: tuple[str, ...],
) -> ApprovalFixture:
    expected = ExpectedApprovalReplay(
        approval_status="dry_run_passed",
        real_order_created=False,
        portfolio_mutated=False,
        idempotency_index_entry=ExpectedIndexEntry(
            idempotency_key=artifact.proposed_order.idempotency_key,
            proposed_order_id=artifact.proposed_order.proposed_order_id,
            approval_decision_id=artifact.approval_decision.approval_decision_id,
            dry_run_request_id=artifact.dry_run_request.dry_run_request_id,
            dry_run_response_id=artifact.broker_dry_run_response.dry_run_response_id,
            approval_status="dry_run_passed",
        ),
    )
    return ApprovalFixture(
        schema_version="v8.operator_approval_dry_run.prd02.fixture.1",
        fixture_name=fixture_name,
        strict_no_real_order=True,
        forbidden_fields=forbidden_fields,
        proposed_order=artifact.proposed_order,
        checklist=artifact.checklist,
        approval_decision=artifact.approval_decision,
        dry_run_request=artifact.dry_run_request,
        broker_dry_run_response=artifact.broker_dry_run_response,
        expected_after_replay=expected,
    )


def _identity_errors(
    artifact: ApprovalArtifact, fixture: ApprovalFixture
) -> list[ApprovalErrorCode]:
    errors: list[ApprovalErrorCode] = []
    rebuilt = rebuild_approval_identities(fixture)
    if (
        rebuilt.proposed_order != artifact.proposed_order
        or rebuilt.checklist != artifact.checklist
        or rebuilt.approval_decision != artifact.approval_decision
        or rebuilt.dry_run_request != artifact.dry_run_request
        or rebuilt.broker_dry_run_response != artifact.broker_dry_run_response
    ):
        errors.append(ApprovalErrorCode.DIRTY_INPUT)
    return errors


def _record_errors(
    artifact: ApprovalArtifact, fixture: ApprovalFixture
) -> list[ApprovalErrorCode]:
    errors: list[ApprovalErrorCode] = []
    previous = "sha256:genesis"
    record_hashes: set[str] = set()
    artifact_ids: set[str] = set()
    for record in artifact.records:
        seed: JsonValue = model_json(record, exclude={"record_hash"})
        if (
            record.prev_record_hash != previous
            or canonical_hash(seed) != record.record_hash
        ):
            errors.append(ApprovalErrorCode.BROKEN_HASH_CHAIN)
        if record.record_hash in record_hashes or record.artifact_id in artifact_ids:
            errors.append(ApprovalErrorCode.REPEATED_INTERRUPTION)
        if record.source_hashes != (artifact.source_input_hash,):
            errors.append(ApprovalErrorCode.DIRTY_INPUT)
        record_hashes.add(record.record_hash)
        artifact_ids.add(record.artifact_id)
        previous = record.record_hash
    expected = build_approval_artifact(
        fixture,
        artifact.source_input_hash,
        artifact.idempotency_index_entry.proposal_seed_hash,
    ).records
    if len(artifact.records) != len(expected):
        errors.append(ApprovalErrorCode.REPEATED_INTERRUPTION)
    elif artifact.records != expected:
        errors.append(ApprovalErrorCode.DIRTY_INPUT)
    return errors


def _index_errors(artifact: ApprovalArtifact) -> list[ApprovalErrorCode]:
    index = artifact.idempotency_index_entry
    response = artifact.broker_dry_run_response
    response_seed = model_json(response, exclude={"dry_run_response_id"})
    expected_response_id = deterministic_id("adry_v8_", response_seed)
    mismatched = (
        index.proposal_seed_hash != canonical_hash(request_seed_from_artifact(artifact))
        or index.proposed_order_id != artifact.proposed_order.proposed_order_id
        or index.approval_decision_id != artifact.approval_decision.approval_decision_id
        or index.dry_run_request_id != artifact.dry_run_request.dry_run_request_id
        or index.dry_run_response_id != response.dry_run_response_id
        or index.response_hash != canonical_hash(model_json(response))
        or response.dry_run_response_id != expected_response_id
    )
    return [ApprovalErrorCode.DIRTY_INPUT] if mismatched else []


def request_seed_from_artifact(artifact: ApprovalArtifact) -> JsonValue:
    return request_seed(_fixture_from_artifact(artifact, "seed", ()))


def verify_approval_artifact(value: JsonValue) -> ApprovalVerificationResult:
    forbidden = _forbidden_keys(value)
    if forbidden:
        code = (
            ApprovalErrorCode.FORBIDDEN_FIELD_PRESENT
            if any(key not in {"state", "stage"} for key in forbidden)
            else ApprovalErrorCode.MALFORMED_INPUT
        )
        return ApprovalVerificationResult(
            verification_status="fail",
            approval_status=(
                "dry_run_failed"
                if code is ApprovalErrorCode.FORBIDDEN_FIELD_PRESENT
                else "proposed"
            ),
            errors=(code,),
            record_count=0,
            live_submission=False,
            would_accept=False,
            real_order_created=False,
            portfolio_mutated=False,
        )
    try:
        artifact = ApprovalArtifact.model_validate(value)
    except (ValidationError, ApprovalContractError):
        return ApprovalVerificationResult(
            verification_status="fail",
            approval_status="proposed",
            errors=(ApprovalErrorCode.MALFORMED_INPUT,),
            record_count=0,
            live_submission=False,
            would_accept=False,
            real_order_created=False,
            portfolio_mutated=False,
        )
    fixture = _fixture_from_artifact(
        artifact,
        "persisted_verification",
        (
            "access_token",
            "account_number",
            "broker_order_id",
            "client_secret",
            "live_order_id",
        ),
    )
    errors = (
        _identity_errors(artifact, fixture)
        + _record_errors(artifact, fixture)
        + _index_errors(artifact)
    )
    if (
        artifact.approval_status != "dry_run_passed"
        or artifact.live_submission
        or not artifact.would_accept
        or artifact.real_order_created
        or artifact.portfolio_mutated
    ):
        errors.append(ApprovalErrorCode.MISLEADING_SUCCESS_OUTPUT)
    errors = list(dict.fromkeys(errors))
    priority = {
        ApprovalErrorCode.MISLEADING_SUCCESS_OUTPUT: 0,
        ApprovalErrorCode.REPEATED_INTERRUPTION: 1,
        ApprovalErrorCode.BROKEN_HASH_CHAIN: 2,
        ApprovalErrorCode.DIRTY_INPUT: 3,
    }
    errors.sort(key=lambda code: priority.get(code, 10))
    return ApprovalVerificationResult(
        verification_status="fail" if errors else "pass",
        approval_status=artifact.approval_status,
        errors=tuple(errors),
        record_count=len(artifact.records),
        live_submission=artifact.live_submission,
        would_accept=artifact.would_accept,
        real_order_created=artifact.real_order_created,
        portfolio_mutated=artifact.portfolio_mutated,
    )
