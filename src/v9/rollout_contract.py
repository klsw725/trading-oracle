from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field, ValidationError

from src.v4.models import JsonValue
from src.v9.contract import StrictModel, V9ContractError, ViewId


class Audience(StrictModel):
    eligible_sessions: int = Field(gt=0)
    exposed_sessions: int = Field(ge=0)
    exposure_percent: str
    audience_rule: str


class SloSummary(StrictModel):
    query_latency_ms_p95: int | None
    detail_latency_ms_p95: int | None
    typed_error_rate: str | None
    malformed_event_rate: str | None
    stale_false_normal_count: int | None
    privacy_violation_count: int | None
    risk_detail_success_rate: str | None
    fallback_success_rate: str | None
    telemetry_lag_seconds_p95: int | None


class Guardrails(StrictModel):
    status: Literal["pass", "fail", "guardrail_unknown", "rollback_required"]
    minimum_sample_count: int = Field(gt=0)
    observed_sample_count: int = Field(ge=0)
    blocking_reasons: tuple[str, ...]
    candidate_next_stage: str | None


class AuditAccess(StrictModel):
    surface_viewed_events: int = Field(ge=0)
    risk_detail_opened_events: int = Field(ge=0)
    missing_required_audit_events: int = Field(ge=0)


class Fallback(StrictModel):
    active: bool
    policy: str
    reason_code: str | None
    last_invoked_at: str | None
    audit_event_present: bool


class Privacy(StrictModel):
    mode: Literal["redacted", "aggregate_only", "blocked"]
    forbidden_fields_present: bool
    redaction_failures: int = Field(ge=0)


class Deprecation(StrictModel):
    old_reader_version: str
    replacement_version: str
    warning_active: bool
    cutoff_active: bool
    replacement_critical_incident: bool


class RolloutConditions(StrictModel):
    loading: bool
    partial: bool
    error: bool
    guardrail_unknown: bool


class RolloutObservabilityViewModel(StrictModel):
    schema_name: Literal["dashboard.rollout_observability_view_model"]
    schema_version: Literal["1.0.0"]
    view_id: ViewId
    stage: Literal[
        "off",
        "internal_dogfood",
        "canary_5",
        "limited_25",
        "default_on",
        "deprecated_read_only",
    ]
    source_contracts: tuple[str, ...]
    audience: Audience
    slo_summary: SloSummary
    guardrails: Guardrails
    audit_access: AuditAccess
    fallback: Fallback
    privacy: Privacy
    deprecation: Deprecation
    conditions: RolloutConditions
    interrupted_journey_counted_success: bool


def _percent(value: str | None, field: str) -> Decimal:
    if value is None:
        raise V9ContractError("guardrail_unknown", field)
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise V9ContractError("malformed_rollout_observability_view_model", field) from error


def parse_rollout(value: JsonValue) -> RolloutObservabilityViewModel:
    try:
        rollout = RolloutObservabilityViewModel.model_validate(value)
    except ValidationError as error:
        raise V9ContractError("malformed_rollout_observability_view_model", str(error)) from error
    expected_exposure = Decimal(rollout.audience.exposed_sessions * 100) / Decimal(
        rollout.audience.eligible_sessions
    )
    if _percent(rollout.audience.exposure_percent, "exposure_percent") != expected_exposure:
        raise V9ContractError("malformed_rollout_observability_view_model", "exposure percent")
    slo = rollout.slo_summary
    required = (
        slo.query_latency_ms_p95,
        slo.detail_latency_ms_p95,
        slo.typed_error_rate,
        slo.malformed_event_rate,
        slo.stale_false_normal_count,
        slo.privacy_violation_count,
        slo.risk_detail_success_rate,
        slo.telemetry_lag_seconds_p95,
    )
    if rollout.guardrails.status == "pass" and (
        any(value is None for value in required)
        or rollout.guardrails.observed_sample_count < rollout.guardrails.minimum_sample_count
    ):
        raise V9ContractError("guardrail_unknown", rollout.view_id)
    if _percent(slo.typed_error_rate, "typed_error_rate") >= Decimal("3.00"):
        raise V9ContractError("error_rate_rollback_required", rollout.view_id)
    if (slo.stale_false_normal_count or 0) > 0 and rollout.guardrails.candidate_next_stage is not None:
        raise V9ContractError("stale_false_normal_blocks_promotion", rollout.view_id)
    if rollout.privacy.forbidden_fields_present or (slo.privacy_violation_count or 0) > 0:
        raise V9ContractError("privacy_boundary_violation", rollout.view_id)
    if rollout.fallback.active and (
        rollout.fallback.reason_code is None
        or rollout.fallback.last_invoked_at is None
        or not rollout.fallback.audit_event_present
    ):
        raise V9ContractError("silent_fallback", rollout.view_id)
    if rollout.deprecation.cutoff_active and rollout.deprecation.replacement_critical_incident:
        raise V9ContractError("unsafe_deprecation_cutoff", rollout.view_id)
    if rollout.interrupted_journey_counted_success:
        raise V9ContractError("interrupted_journey_counted_success", rollout.view_id)
    return rollout
