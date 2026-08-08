from __future__ import annotations

from pydantic import ValidationError

from src.v8.risk_evaluator import evaluate_risk, source_hashes
from src.v8.risk_json import JsonValue, canonical_hash, model_json
from src.v8.risk_models import (
    RiskArtifact,
    RiskDecision,
    RiskErrorCode,
    RiskVerificationResult,
)


def _forbidden_lifecycle(value: JsonValue) -> bool:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            return bool({"state", "stage"}.intersection(record)) or any(
                _forbidden_lifecycle(child) for child in record.values()
            )
        case list() as values:
            return any(_forbidden_lifecycle(child) for child in values)
        case None | bool() | int() | float() | str():
            return False


def _result(
    decision: RiskDecision | None, errors: tuple[RiskErrorCode, ...]
) -> RiskVerificationResult:
    if decision is None:
        return RiskVerificationResult(
            verification_status="fail",
            risk_status="kill_switch_active",
            errors=errors,
            fail_closed=True,
            dry_run_request_allowed=False,
            real_order_created=False,
            portfolio_mutated=False,
        )
    return RiskVerificationResult(
        verification_status="fail" if errors else "pass",
        risk_status=decision.risk_status,
        errors=errors,
        fail_closed=decision.fail_closed,
        dry_run_request_allowed=decision.dry_run_request_allowed,
        real_order_created=decision.real_order_created,
        portfolio_mutated=decision.portfolio_mutated,
    )


def verify_risk_artifact(value: JsonValue) -> RiskVerificationResult:
    if _forbidden_lifecycle(value):
        return _result(None, (RiskErrorCode.RISK_STATUS_TAMPERED,))
    try:
        artifact = RiskArtifact.model_validate(value)
    except ValidationError:
        return _result(None, (RiskErrorCode.MALFORMED_INPUT,))
    decision = artifact.decision
    expected = evaluate_risk(artifact.request)
    errors: list[RiskErrorCode] = []
    if decision.risk_status == "allowed" and decision.blocking_reasons:
        errors.append(RiskErrorCode.MISLEADING_RISK_SUCCESS)
    if decision.risk_status != expected.risk_status or decision.blocking_reasons != expected.blocking_reasons:
        errors.append(RiskErrorCode.RISK_STATUS_TAMPERED)
    if decision.source_hashes != source_hashes(artifact.request):
        errors.append(RiskErrorCode.RECORD_HASH_MISMATCH)
    if decision.record_hash != canonical_hash(model_json(decision, exclude={"record_hash"})):
        errors.append(RiskErrorCode.RECORD_HASH_MISMATCH)
    if decision != expected and not errors:
        errors.append(RiskErrorCode.RECORD_HASH_MISMATCH)
    return _result(decision, tuple(dict.fromkeys(errors)))
