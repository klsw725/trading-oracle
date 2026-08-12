from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, ValidationError

from src.v4.models import JsonValue
from src.v9.contract import RiskItemId, SourceHealthLabel, StrictModel, V9ContractError, ViewId


class RiskItem(StrictModel):
    risk_item_id: RiskItemId
    subject_id: str
    category: str
    severity: Literal["info", "watch", "action_required", "blocking", "critical"]
    status: Literal["open", "acknowledged", "snoozed", "resolved_by_source", "blocked", "stale"]
    opened_at: datetime
    updated_at: datetime
    reason_codes: tuple[str, ...]
    affected_fields: tuple[str, ...]
    actionability: Literal["informational", "needs_review", "blocks_action", "blocks_current_use"]
    available_actions: tuple[str, ...]


class SourceHealth(StrictModel):
    source_health_id: str
    freshness_status: str
    quality_status: str
    health_label: SourceHealthLabel
    age_seconds: int | None = Field(ge=0)
    max_age_seconds: int = Field(gt=0)
    affected_fields: tuple[str, ...]
    stale_action: str


class Divergence(StrictModel):
    divergence_id: str
    subject_id: str
    paper_namespace: str
    live_reference_status: str
    severity: str
    open: bool


class RiskSummary(StrictModel):
    open_risk_count: int = Field(ge=0)
    blocking_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    stale_source_count: int = Field(ge=0)
    healthy_source_count: int = Field(ge=0)
    acknowledged_count: int = Field(ge=0)
    paper_live_divergence_count: int = Field(ge=0)
    confidence_watch_count: int = Field(ge=0)


class RiskConditions(StrictModel):
    loading: bool
    empty: bool
    partial: bool
    error: bool


class RiskHealthViewModel(StrictModel):
    schema_name: Literal["dashboard.risk_health_view_model"]
    schema_version: Literal["1.0.0"]
    source_contract: Literal["dashboard.query_result.1.0.0"]
    view_id: ViewId
    summary: RiskSummary
    selected_risk_item_id: RiskItemId | None
    selection_missing_reason: str | None
    risk_inbox: tuple[RiskItem, ...]
    source_health: tuple[SourceHealth, ...]
    confidence_condition: str
    paper_live_divergence: tuple[Divergence, ...]
    conditions: RiskConditions


class RiskAcknowledgementRequest(StrictModel):
    schema_name: Literal["dashboard.risk_acknowledgement_request"]
    schema_version: Literal["1.0.0"]
    ack_request_id: str
    risk_item_id: RiskItemId
    risk_version: str
    operator_ref: str
    requested_action: Literal["acknowledge", "snooze"]
    reason_code: str
    requested_at: datetime
    snooze_until: datetime | None


def parse_risk(value: JsonValue) -> RiskHealthViewModel:
    try:
        risk = RiskHealthViewModel.model_validate(value)
    except ValidationError as error:
        raise V9ContractError("malformed_risk_health_view_model", str(error)) from error
    items = {item.risk_item_id: item for item in risk.risk_inbox}
    if risk.selected_risk_item_id is not None and risk.selected_risk_item_id not in items:
        raise V9ContractError("malformed_risk_health_view_model", "selected risk missing")
    if risk.selected_risk_item_id is None and risk.selection_missing_reason is None:
        raise V9ContractError("malformed_risk_health_view_model", "selection reason missing")
    for source in risk.source_health:
        if source.freshness_status == "stale" and source.health_label is SourceHealthLabel.HEALTHY:
            raise V9ContractError("stale_health_falsely_normal", source.source_health_id)
        if source.age_seconds is not None and source.age_seconds > source.max_age_seconds and source.health_label is SourceHealthLabel.HEALTHY:
            raise V9ContractError("stale_health_falsely_normal", source.source_health_id)
    open_count = sum(item.status in {"open", "stale"} for item in risk.risk_inbox)
    blocking_count = sum(item.actionability in {"blocks_action", "blocks_current_use"} for item in risk.risk_inbox)
    stale_count = sum(source.health_label is SourceHealthLabel.STALE for source in risk.source_health)
    healthy_count = sum(source.health_label is SourceHealthLabel.HEALTHY for source in risk.source_health)
    divergence_count = sum(item.open for item in risk.paper_live_divergence)
    if (
        risk.summary.open_risk_count != open_count
        or risk.summary.blocking_count != blocking_count
        or risk.summary.stale_source_count != stale_count
        or risk.summary.healthy_source_count != healthy_count
        or risk.summary.paper_live_divergence_count != divergence_count
    ):
        raise V9ContractError("misleading_risk_summary", risk.view_id)
    return risk


def verify_acknowledgement_projection(
    before: RiskHealthViewModel, after: RiskHealthViewModel
) -> None:
    before_facts = (
        tuple((item.risk_item_id, item.severity, item.actionability) for item in before.risk_inbox),
        before.source_health,
        before.paper_live_divergence,
        before.summary.stale_source_count,
    )
    after_facts = (
        tuple((item.risk_item_id, item.severity, item.actionability) for item in after.risk_inbox),
        after.source_health,
        after.paper_live_divergence,
        after.summary.stale_source_count,
    )
    if before_facts != after_facts:
        raise V9ContractError("forbidden_surface_mutation", before.view_id)
