from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from pydantic import ValidationError

from src.v8.event_models import FrozenModel
from src.v8.promotion_models import (
    AutomationEvidence,
    AutomationResult,
    CompilePromotionResult,
    IncidentEvidence,
    IncidentRecord,
    KillSwitchProof,
    PromotionArtifact,
    PromotionDecision,
    PromotionErrorCode,
    PromotionRequest,
)
from src.v8.promotion_rules import (
    automation_error,
    genesis_hash,
    incident_disposition,
    incident_sla,
    incident_switch_seed,
    promotion_error,
)
from src.v8.risk_json import JsonValue, canonical_hash, deterministic_id, model_json

_FORBIDDEN: Final = frozenset(
    {
        "state", "stage", "access_token", "client_secret", "account_number",
        "broker_order_id", "live_order_id", "forbidden", "live",
        "raw_broker_order_id", "credential_key",
    }
)
_DECIMALS: Final = frozenset(
    {
        "per_order_notional_krw", "per_symbol_daily_notional_krw",
        "total_daily_notional_krw", "traffic_share_pct", "estimated_notional",
        "estimated_fee", "estimated_tax", "symbol_daily_notional_before",
        "total_daily_notional_before", "reconciliation_mismatch_rate",
    }
)


class HappyPromotionFixture(FrozenModel):
    schema_version: Literal["v8.limited_automation_promotion.prd05.fixture.1"]
    fixture_name: Literal["happy_limited_automation_promotion"]
    strict_no_real_order: Literal[True]
    promotion_request: PromotionRequest
    automation_evidence: AutomationEvidence


class IncidentPromotionFixture(FrozenModel):
    schema_version: Literal["v8.limited_automation_promotion.prd05.failure_fixture.1"]
    fixture_name: Literal["incident_auto_rollback_after_stale_quote_false_allow"]
    strict_no_real_order: Literal[True]
    incident_evidence: IncidentEvidence


@dataclass(frozen=True, slots=True)
class ShapeError:
    code: PromotionErrorCode


def shape_error(value: JsonValue) -> ShapeError | None:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            lifecycle = {"state", "stage"}.intersection(record)
            if lifecycle:
                return ShapeError(PromotionErrorCode.FORBIDDEN_LIFECYCLE_FIELD)
            if _FORBIDDEN.intersection(record):
                return ShapeError(PromotionErrorCode.REAL_ORDER_MUTATION)
            for key, child in record.items():
                if key in _DECIMALS and not isinstance(child, str):
                    return ShapeError(PromotionErrorCode.JSON_MALFORMED)
                if isinstance(child, str) and child.lower() == "unlimited":
                    return ShapeError(PromotionErrorCode.UNLIMITED_AUTOMATION_FORBIDDEN)
                if nested := shape_error(child):
                    return nested
            return None
        case list() as values:
            return next((error for child in values if (error := shape_error(child))), None)
        case None | bool() | int() | float() | str():
            if isinstance(value, str) and value in {
                "broker_live", "toss_live", "real_account", "unlimited"
            }:
                return ShapeError(
                    PromotionErrorCode.UNLIMITED_AUTOMATION_FORBIDDEN
                    if value == "unlimited"
                    else PromotionErrorCode.REAL_ORDER_MUTATION
                )
            return None


def _decision(request: PromotionRequest) -> PromotionDecision:
    seed = model_json(request)
    decision = PromotionDecision(
        schema_version="v8.limited_automation_promotion.decision.1",
        promotion_decision_id=deterministic_id("prom_v8_", seed),
        promotion_status_before=request.promotion_status_before,
        promotion_status_after=request.promotion_status_after,
        requested_by=request.requested_by,
        approved_by=request.approved_by,
        effective_at=request.effective_at,
        expires_at=request.expires_at,
        eligible_scope=request.eligible_scope,
        blast_radius_caps=request.blast_radius_caps,
        observation_window=request.observation_window,
        incident_policy=request.incident_policy,
        source_hashes=request.source_bindings,
        kill_switch=request.kill_switch_proof,
        idempotency_key=request.idempotency_key,
        prev_record_hash=genesis_hash(),
        record_hash="sha256:pending",
    )
    return decision.model_copy(
        update={"record_hash": canonical_hash(model_json(decision, exclude={"record_hash"}))}
    )


def compile_promotion_fixture(value: JsonValue) -> CompilePromotionResult:
    if shape := shape_error(value):
        return CompilePromotionResult(None, shape.code)
    try:
        fixture = HappyPromotionFixture.model_validate(value)
    except ValidationError:
        return CompilePromotionResult(None, PromotionErrorCode.JSON_MALFORMED)
    request = fixture.promotion_request
    if error := promotion_error(request):
        return CompilePromotionResult(None, error)
    decision = _decision(request)
    evidence = fixture.automation_evidence
    if error := automation_error(request, evidence, decision.promotion_decision_id):
        return CompilePromotionResult(None, error)
    result = AutomationResult(
        schema_version="v8.limited_automation_promotion.automation_request.1",
        automation_request_id=deterministic_id(
            "auto_v8_", {"decision": decision.promotion_decision_id, "proposal": evidence.proposal_id}
        ),
        promotion_decision_id=decision.promotion_decision_id,
        promotion_status="limited_automation",
        sampled=True,
        evidence=evidence,
        destination=evidence.destination,
        idempotency_key=evidence.proposal_id,
        source_hashes=request.source_bindings,
        dry_run_request_allowed=True,
        real_order_created=False,
        portfolio_mutated=False,
        prev_record_hash=decision.record_hash,
        record_hash="sha256:pending",
    )
    result = result.model_copy(
        update={"record_hash": canonical_hash(model_json(result, exclude={"record_hash"}))}
    )
    return CompilePromotionResult(
        PromotionArtifact(
            schema_version="v8.limited_automation_promotion.artifact.1",
            source_input_hash=canonical_hash(value),
            promotion_status="limited_automation",
            decision=decision,
            automation_result=result,
        )
    )


def compile_incident_fixture(value: JsonValue) -> CompilePromotionResult:
    if shape := shape_error(value):
        return CompilePromotionResult(None, shape.code)
    try:
        fixture = IncidentPromotionFixture.model_validate(value)
    except ValidationError:
        return CompilePromotionResult(None, PromotionErrorCode.JSON_MALFORMED)
    evidence = fixture.incident_evidence
    real_mutation = evidence.live_submission or evidence.real_order_created or evidence.portfolio_mutated
    disposition = incident_disposition(evidence.reason_codes[0])
    if real_mutation:
        return CompilePromotionResult(None, PromotionErrorCode.REAL_ORDER_MUTATION)
    if disposition is None:
        return CompilePromotionResult(None, PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS)
    if (
        evidence.reason_codes[0] == "stale_quote_falsely_fresh"
        and evidence.checked_at <= evidence.quote_expires_at
    ):
        return CompilePromotionResult(None, PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS)
    switch_seed = incident_switch_seed(evidence, disposition)
    switch_hash = canonical_hash(switch_seed)
    switch = KillSwitchProof(
        kill_switch_id=deterministic_id("ksw_v8_", switch_seed),
        scope=disposition.switch_scope,
        scope_value=evidence.ticker if disposition.switch_scope == "ticker" else None,
        switch_status="active" if disposition.automatic else "inactive",
        hash_chain_verified=True,
        record_hash=switch_hash,
    )
    stop_met, append_met = incident_sla(evidence, disposition)
    record = IncidentRecord(
        schema_version="v8.limited_automation_promotion.incident.1",
        incident_id=deterministic_id("inc_v8_", model_json(evidence)),
        promotion_status=disposition.promotion_status_after,
        severity=disposition.severity,
        evidence=evidence,
        kill_switch=switch,
        stop_sla_met=stop_met,
        append_sla_met=append_met,
        dry_run_request_allowed=not disposition.automatic,
        prev_record_hash=genesis_hash(),
        record_hash="sha256:pending",
    )
    record = record.model_copy(
        update={"record_hash": canonical_hash(model_json(record, exclude={"record_hash"}))}
    )
    if not stop_met or not append_met:
        return CompilePromotionResult(None, PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED)
    return CompilePromotionResult(record)
