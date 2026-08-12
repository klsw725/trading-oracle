from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from src.v4.models import JsonValue
from src.v9.contract import Condition, StrictModel, SubjectId, V9ContractError, ViewId


class ReturnContext(StrictModel):
    query_id: str
    cursor: str | None
    filters: dict[str, JsonValue]


class Navigation(StrictModel):
    current_node: str
    return_context: ReturnContext


class SelectedRecommendation(StrictModel):
    subject_id: SubjectId
    ticker: str
    market: str
    action: str
    consensus_label: str
    confidence: str
    freshness_status: str
    quality_status: str
    risk_level: str


class TimelineItem(StrictModel):
    kind: Literal[
        "source_observed",
        "decision_input_cutoff",
        "decision_emitted",
        "operator_or_execution",
        "outcome_matured",
        "evidence_checked",
    ]
    timestamp: datetime | None
    refs: tuple[str, ...]


class DrilldownLink(StrictModel):
    rel: str
    target_node: str
    target_id: str | None
    health: str
    reason: str | None = None


class OutcomeSection(StrictModel):
    condition: Condition
    metrics: dict[str, JsonValue] | None
    missing_reason: str | None
    counted_as_win: bool
    counted_as_loss: bool


class ViewConditions(StrictModel):
    loading: bool
    empty: bool
    partial: bool
    error: bool


class ReplayViewModel(StrictModel):
    schema_name: Literal["dashboard.replay_view_model"]
    schema_version: Literal["1.0.0"]
    source_contract: Literal["dashboard.query_result.1.0.0"]
    view_id: ViewId
    navigation: Navigation
    selected_recommendation: SelectedRecommendation
    timeline: tuple[TimelineItem, ...]
    known_reference_ids: tuple[str, ...]
    outcome_summary: OutcomeSection
    drilldown_links: tuple[DrilldownLink, ...]
    conditions: ViewConditions


def parse_replay(value: JsonValue) -> ReplayViewModel:
    try:
        replay = ReplayViewModel.model_validate(value)
    except ValidationError as error:
        raise V9ContractError("malformed_replay_view_model", str(error)) from error
    known = set(replay.known_reference_ids)
    known.add(replay.selected_recommendation.subject_id)
    if any(ref not in known for item in replay.timeline for ref in item.refs):
        raise V9ContractError("malformed_replay_view_model", "unresolved timeline ref")
    for link in replay.drilldown_links:
        if link.target_id is None and link.reason is None:
            raise V9ContractError("broken_drilldown_link", link.rel)
        if link.rel == "source_evidence" and not link.target_node.endswith("/sources"):
            raise V9ContractError("broken_drilldown_link", link.rel)
    outcome = replay.outcome_summary
    if outcome.condition is Condition.MISSING and (
        outcome.metrics is not None
        or outcome.missing_reason is None
        or outcome.counted_as_win
        or outcome.counted_as_loss
        or not replay.conditions.partial
    ):
        raise V9ContractError("misleading_outcome", "missing outcome is not neutral")
    order = tuple(item.kind for item in replay.timeline)
    required = ("source_observed", "decision_input_cutoff", "decision_emitted")
    if tuple(kind for kind in order if kind in required) != required:
        raise V9ContractError("malformed_replay_view_model", "timeline order")
    return replay
