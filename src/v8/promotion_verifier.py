from __future__ import annotations

from datetime import timedelta

from pydantic import ValidationError

from src.v8.promotion_compiler import (
    IncidentPromotionFixture,
    compile_incident_fixture,
    shape_error,
)
from src.v8.promotion_models import (
    IncidentRecord,
    PromotionArtifact,
    PromotionDecision,
    PromotionErrorCode,
    PromotionRequest,
    PromotionVerificationResult,
)
from src.v8.promotion_rules import (
    automation_error,
    incident_disposition,
    incident_sla,
    incident_switch_seed,
    promotion_error,
)
from src.v8.risk_json import JsonValue, canonical_hash, deterministic_id, model_json


def _failure(error: PromotionErrorCode) -> PromotionVerificationResult:
    return PromotionVerificationResult(
        verification_status="fail",
        promotion_status="rolled_back",
        errors=(error,),
        dry_run_request_allowed=False,
        real_order_created=False,
        portfolio_mutated=False,
    )


def _request(decision: PromotionDecision) -> PromotionRequest:
    return PromotionRequest(
        promotion_status_before=decision.promotion_status_before,
        promotion_status_after=decision.promotion_status_after,
        requested_by=decision.requested_by,
        approved_by=decision.approved_by,
        effective_at=decision.effective_at,
        expires_at=decision.expires_at,
        idempotency_key=decision.idempotency_key,
        eligible_scope=decision.eligible_scope,
        blast_radius_caps=decision.blast_radius_caps,
        observation_window=decision.observation_window,
        incident_policy=decision.incident_policy,
        source_bindings=decision.source_hashes,
        kill_switch_proof=decision.kill_switch,
    )


def verify_promotion_artifact(value: JsonValue) -> PromotionVerificationResult:
    if shape := shape_error(value):
        return _failure(shape.code)
    try:
        artifact = PromotionArtifact.model_validate(value)
    except ValidationError:
        return _failure(PromotionErrorCode.JSON_MALFORMED)
    decision = artifact.decision
    request = _request(decision)
    errors: list[PromotionErrorCode] = []
    if error := promotion_error(request):
        errors.append(error)
    if decision.promotion_decision_id != deterministic_id("prom_v8_", model_json(request)):
        errors.append(PromotionErrorCode.RECORD_HASH_MISMATCH)
    if decision.record_hash != canonical_hash(model_json(decision, exclude={"record_hash"})):
        errors.append(PromotionErrorCode.RECORD_HASH_MISMATCH)
    result = artifact.automation_result
    evidence = result.evidence
    if error := automation_error(request, evidence, decision.promotion_decision_id):
        errors.append(error)
    if (
        artifact.promotion_status != "limited_automation"
        or result.promotion_status != "limited_automation"
        or result.promotion_decision_id != decision.promotion_decision_id
        or result.destination not in {"broker_dry_run", "internal_dry_run"}
        or result.destination != evidence.destination
        or result.idempotency_key != evidence.proposal_id
        or not result.sampled
        or not result.dry_run_request_allowed
    ):
        errors.append(PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS)
    expected_request_id = deterministic_id(
        "auto_v8_",
        {"decision": decision.promotion_decision_id, "proposal": evidence.proposal_id},
    )
    if result.automation_request_id != expected_request_id:
        errors.append(PromotionErrorCode.RECORD_HASH_MISMATCH)
    if (
        result.prev_record_hash != decision.record_hash
        or result.source_hashes != decision.source_hashes
        or result.record_hash != canonical_hash(model_json(result, exclude={"record_hash"}))
    ):
        errors.append(PromotionErrorCode.BROKEN_HASH_CHAIN)
    return PromotionVerificationResult(
        verification_status="fail" if errors else "pass",
        promotion_status=artifact.promotion_status,
        errors=tuple(dict.fromkeys(errors)),
        dry_run_request_allowed=result.dry_run_request_allowed and not errors,
        real_order_created=result.real_order_created,
        portfolio_mutated=result.portfolio_mutated,
    )


def verify_incident_record(value: JsonValue) -> PromotionVerificationResult:
    if shape := shape_error(value):
        return _failure(shape.code)
    try:
        incident = IncidentRecord.model_validate(value)
    except ValidationError:
        return _failure(PromotionErrorCode.JSON_MALFORMED)
    errors: list[PromotionErrorCode] = []
    if incident.record_hash != canonical_hash(model_json(incident, exclude={"record_hash"})):
        errors.append(PromotionErrorCode.RECORD_HASH_MISMATCH)
    evidence = incident.evidence
    disposition = incident_disposition(evidence.reason_codes[0])
    if disposition is None:
        errors.append(PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS)
    else:
        switch_seed = incident_switch_seed(evidence, disposition)
        switch_hash = canonical_hash(switch_seed)
        expected_switch_status = "active" if disposition.automatic else "inactive"
        expected_scope_value = evidence.ticker if disposition.switch_scope == "ticker" else None
        if (
            incident.severity != disposition.severity
            or incident.promotion_status != disposition.promotion_status_after
            or incident.kill_switch.scope != disposition.switch_scope
            or incident.kill_switch.scope_value != expected_scope_value
            or incident.kill_switch.switch_status != expected_switch_status
            or incident.kill_switch.kill_switch_id
            != deterministic_id("ksw_v8_", switch_seed)
            or incident.kill_switch.record_hash != switch_hash
            or not incident.kill_switch.hash_chain_verified
            or incident.dry_run_request_allowed == disposition.automatic
        ):
            errors.append(PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS)
        stop_met, append_met = incident_sla(evidence, disposition)
        if (
            not stop_met
            or not append_met
            or incident.stop_sla_met != stop_met
            or incident.append_sla_met != append_met
        ):
            errors.append(PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED)
    if incident.incident_id != deterministic_id("inc_v8_", model_json(evidence)):
        errors.append(PromotionErrorCode.RECORD_HASH_MISMATCH)
    if (
        evidence.reason_codes[0] == "stale_quote_falsely_fresh"
        and evidence.checked_at <= evidence.quote_expires_at
    ):
        errors.append(PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS)
    if evidence.live_submission or evidence.real_order_created or evidence.portfolio_mutated:
        errors.append(PromotionErrorCode.REAL_ORDER_MUTATION)
    return PromotionVerificationResult(
        verification_status="fail" if errors else "pass",
        promotion_status=incident.promotion_status,
        errors=tuple(dict.fromkeys(errors)),
        dry_run_request_allowed=False,
        real_order_created=evidence.real_order_created,
        portfolio_mutated=evidence.portfolio_mutated,
    )


def forged_sample_rejected(artifact: PromotionArtifact) -> bool:
    result = artifact.automation_result.model_copy(
        update={"sampled": False, "record_hash": "sha256:pending"}
    )
    result = result.model_copy(
        update={"record_hash": canonical_hash(model_json(result, exclude={"record_hash"}))}
    )
    verified = verify_promotion_artifact(
        model_json(artifact.model_copy(update={"automation_result": result}))
    )
    return verified.errors == (PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS,)


def forged_automation_id_rejected(artifact: PromotionArtifact) -> bool:
    result = artifact.automation_result.model_copy(
        update={"automation_request_id": "auto_v8_forged", "record_hash": "sha256:pending"}
    )
    result = result.model_copy(
        update={"record_hash": canonical_hash(model_json(result, exclude={"record_hash"}))}
    )
    verified = verify_promotion_artifact(
        model_json(artifact.model_copy(update={"automation_result": result}))
    )
    return verified.errors == (PromotionErrorCode.RECORD_HASH_MISMATCH,)


def forged_incident_sla_rejected(incident: IncidentRecord) -> bool:
    evidence = incident.evidence.model_copy(
        update={
            "new_automation_stopped_at": incident.evidence.detected_at
            + timedelta(seconds=61),
            "incident_appended_at": incident.evidence.detected_at
            + timedelta(seconds=301),
        }
    )
    disposition = incident_disposition(evidence.reason_codes[0])
    assert disposition is not None
    switch_seed = incident_switch_seed(evidence, disposition)
    kill_switch = incident.kill_switch.model_copy(
        update={
            "kill_switch_id": deterministic_id("ksw_v8_", switch_seed),
            "record_hash": canonical_hash(switch_seed),
        }
    )
    forged = incident.model_copy(
        update={
            "incident_id": deterministic_id("inc_v8_", model_json(evidence)),
            "evidence": evidence,
            "kill_switch": kill_switch,
            "stop_sla_met": True,
            "append_sla_met": True,
        }
    )
    forged = forged.model_copy(
        update={"record_hash": canonical_hash(model_json(forged, exclude={"record_hash"}))}
    )
    return verify_incident_record(model_json(forged)).errors == (
        PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED,
    )


def all_severity_records_verify(value: JsonValue) -> bool:
    fixture = IncidentPromotionFixture.model_validate(value)
    cases = (
        ("real_order_attempt", "critical", "paper", 100),
        ("stale_quote_falsely_fresh", "high", "dry_run", 200),
        ("approval_evidence_missing", "medium", "approval_required", 600),
        ("non_blocking_evidence_lag", "low", "limited_automation", 3_600),
    )
    for reason, severity, status, append_seconds in cases:
        evidence = fixture.incident_evidence.model_copy(
            update={
                "reason_codes": (reason,),
                "incident_appended_at": fixture.incident_evidence.detected_at
                + timedelta(seconds=append_seconds),
            }
        )
        compiled = compile_incident_fixture(
            model_json(fixture.model_copy(update={"incident_evidence": evidence}))
        )
        if not isinstance(compiled.artifact, IncidentRecord):
            return False
        record = compiled.artifact
        if (
            record.severity != severity
            or record.promotion_status != status
            or verify_incident_record(model_json(record)).verification_status != "pass"
        ):
            return False
    return True
