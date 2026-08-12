from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, ValidationError

from src.v4.models import JsonValue
from src.v9.contract import (
    Freshness,
    Quality,
    RiskLevel,
    StrictModel,
    SubjectId,
    V9ContractError,
)


class Producer(StrictModel):
    name: str
    version: str
    source_command: str


class SubjectIdentity(StrictModel):
    subject_type: str
    subject_id: SubjectId
    market: str
    ticker: str
    portfolio_scope: str


class EventTimestamps(StrictModel):
    produced_at: datetime
    observed_at: datetime
    data_cutoff_at: datetime
    valid_after_at: datetime
    expires_at: datetime


class FreshnessState(StrictModel):
    status: Freshness
    age_seconds: int = Field(ge=0)
    max_age_seconds: int = Field(gt=0)
    stale_after_seconds: int = Field(gt=0)
    source_lag_seconds: int = Field(ge=0)


class QualityCheck(StrictModel):
    name: str
    status: Literal["pass", "warn", "fail"]
    reason: str | None = None


class QualityState(StrictModel):
    status: Quality
    score: float | None = Field(default=None, ge=0, le=1)
    checks: tuple[QualityCheck, ...]


class RiskState(StrictModel):
    level: RiskLevel
    reasons: tuple[str, ...]
    blocking: bool
    risk_version: str


class Consensus(StrictModel):
    consensus_verdict: Literal["BUY", "SELL", "HOLD", "BLOCKED"]
    consensus_label: str
    confidence: str


class Recommendation(StrictModel):
    ticker: str
    name: str
    market: str
    sector: str
    price: int | float
    selected_by: tuple[str, ...]
    signals: dict[str, JsonValue]
    consensus: Consensus
    action_plan: dict[str, JsonValue]


class PortfolioSizing(StrictModel):
    cash: int | float
    cash_ratio: int | float
    cash_floor: int | float
    available_cash: int | float
    can_buy: bool


class RecommendationSummaryPayload(StrictModel):
    date: str
    market: str
    universe_size: int = Field(ge=0)
    portfolio_sizing: PortfolioSizing
    selection_constraints: dict[str, JsonValue]
    recommendations: tuple[Recommendation, ...]
    no_recommendation_reason: str | None


class Link(StrictModel):
    rel: str
    target_id: str | None
    payload_type: str
    health: str
    reason: str | None = None


class EnvelopeMeta(StrictModel):
    redaction: str
    raw_hash: str


class RecommendationEnvelope(StrictModel):
    schema_name: Literal["dashboard.event_envelope"]
    schema_version: Literal["1.0.0"]
    min_reader_version: Literal["1.0.0"]
    event_id: str
    correlation_id: str
    request_id: str
    producer: Producer
    identity: SubjectIdentity
    timestamps: EventTimestamps
    freshness: FreshnessState
    quality: QualityState
    risk_state: RiskState
    payload_type: Literal["recommendation.summary.v1"]
    payload: RecommendationSummaryPayload
    links: tuple[Link, ...]
    meta: EnvelopeMeta


class SortField(StrictModel):
    field: str
    direction: Literal["asc", "desc"]


class Pagination(StrictModel):
    cursor: str | None
    next_cursor: str | None
    limit: int = Field(ge=1, le=100)
    has_more: bool
    sort: tuple[SortField, ...]


class QuerySummary(StrictModel):
    returned_count: int = Field(ge=0)
    fresh_count: int = Field(ge=0)
    degraded_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)


class DashboardQueryResult(StrictModel):
    schema_name: Literal["dashboard.query_result"]
    schema_version: Literal["1.0.0"]
    query_id: str
    requested_payload_type: Literal["recommendation.summary.v1"]
    accepted_versions: tuple[str, ...]
    returned_version: str
    generated_at: datetime
    pagination: Pagination
    items: tuple[RecommendationEnvelope, ...]
    summary: QuerySummary
    warnings: tuple[str, ...]


class VersionAccept(StrictModel):
    envelope_versions: tuple[str, ...]
    payload_versions: dict[str, tuple[str, ...]]


class DashboardQueryRequest(StrictModel):
    accept: VersionAccept
    payload_type: str
    limit: int = Field(ge=1, le=100)


def negotiate_version(request: DashboardQueryRequest) -> str:
    if not request.accept.envelope_versions or not request.accept.payload_versions:
        raise V9ContractError("missing_version_accept", request.payload_type)
    if "1.0.0" not in request.accept.envelope_versions:
        raise V9ContractError("unsupported_envelope_version", request.payload_type)
    payload_base = request.payload_type.rsplit(".v", 1)[0]
    if "1.0.0" not in request.accept.payload_versions.get(payload_base, ()):
        raise V9ContractError("unsupported_payload_version", request.payload_type)
    return "1.0.0"


def parse_query(value: JsonValue) -> DashboardQueryResult:
    try:
        query = DashboardQueryResult.model_validate(value)
    except ValidationError as error:
        code = "malformed_query" if "pagination" in str(error) else "malformed_envelope"
        raise V9ContractError(code, str(error)) from error
    if query.pagination.has_more != (query.pagination.next_cursor is not None):
        raise V9ContractError("malformed_query", "pagination cursor state")
    for item in query.items:
        if item.timestamps.data_cutoff_at > item.timestamps.produced_at:
            raise V9ContractError("malformed_envelope", "data cutoff after production")
        if item.freshness.status is Freshness.FRESH and (
            item.freshness.age_seconds > item.freshness.max_age_seconds
        ):
            raise V9ContractError("stale_mislabeled_fresh", item.event_id)
        if item.quality.status is Quality.OK and any(
            check.status == "fail" for check in item.quality.checks
        ):
            raise V9ContractError("malformed_envelope", "ok quality has failed check")
        if item.risk_state.level is RiskLevel.BLOCKED and not item.risk_state.blocking:
            raise V9ContractError("malformed_envelope", "blocked risk flag mismatch")
    fresh = sum(item.freshness.status is Freshness.FRESH for item in query.items)
    degraded = sum(item.quality.status is Quality.DEGRADED for item in query.items)
    blocked = sum(
        item.quality.status is Quality.BLOCKED or item.risk_state.blocking
        for item in query.items
    )
    if query.summary != QuerySummary(
        returned_count=len(query.items),
        fresh_count=fresh,
        degraded_count=degraded,
        blocked_count=blocked,
    ):
        raise V9ContractError("misleading_summary", query.query_id)
    return query
