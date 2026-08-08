from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum, unique
from typing import Literal, override

from pydantic import AwareDatetime, Field, field_validator
from pydantic_core import PydanticCustomError

from src.v8.event_models import FrozenModel, Side

type PromotionStatus = Literal[
    "paper", "dry_run", "approval_required", "limited_automation", "rolled_back"
]
type Severity = Literal["critical", "high", "medium", "low"]


@unique
class PromotionErrorCode(StrEnum):
    JSON_MALFORMED = "json_malformed"
    FORBIDDEN_LIFECYCLE_FIELD = "forbidden_lifecycle_field"
    THRESHOLD_TAMPERED = "threshold_tampered"
    UNLIMITED_AUTOMATION_FORBIDDEN = "unlimited_automation_forbidden"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INTERRUPTION_COMPLETION_REQUIRED = "interruption_completion_required"
    MISLEADING_PROMOTION_SUCCESS = "misleading_promotion_success"
    REAL_ORDER_MUTATION = "real_order_mutation"
    STALE_SOURCE = "stale_source"
    DIRTY_INPUT = "dirty_input"
    INELIGIBLE_SCOPE = "ineligible_scope"
    BLAST_RADIUS_EXCEEDED = "blast_radius_exceeded"
    TRAFFIC_NOT_SELECTED = "traffic_not_selected"
    REPROMOTION_BLOCKED = "repromotion_blocked"
    RECORD_HASH_MISMATCH = "record_hash_mismatch"
    BROKEN_HASH_CHAIN = "broken_hash_chain"


@dataclass(frozen=True, slots=True)
class PromotionContractError(Exception):
    code: PromotionErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


class EligibleScope(FrozenModel):
    markets: tuple[Literal["KR"], ...]
    symbols: tuple[str, ...] = Field(min_length=1, max_length=2)
    sides: tuple[Side, ...]
    order_types: tuple[Literal["limit"], ...]
    risk_reducing_sell_only: Literal[True]
    regular_session_only: Literal[True]


class BlastRadiusCaps(FrozenModel):
    per_order_notional_krw: Decimal = Field(gt=0)
    per_symbol_daily_notional_krw: Decimal = Field(gt=0)
    total_daily_notional_krw: Decimal = Field(gt=0)
    concurrent_requests: int = Field(gt=0)
    traffic_share_pct: Decimal = Field(gt=0, le=100)
    max_eligible_symbols: int = Field(gt=0)
    max_duration_trading_sessions: int = Field(gt=0)
    unlimited_allowed: Literal[False]


class ObservationWindow(FrozenModel):
    paper_sessions: int = Field(ge=0)
    paper_order_count: int = Field(ge=0)
    live_contamination_count: int = Field(ge=0)
    hash_chain_break_count: int = Field(ge=0)
    reconciliation_mismatch_rate: Decimal = Field(ge=0)
    dry_run_attempts: int = Field(ge=0)
    malformed_response_count: int = Field(ge=0)
    duplicate_idempotency_count: int = Field(ge=0)
    stale_quote_blocked_count: int = Field(ge=0)
    expected_stale_probes: int = Field(ge=0)
    approval_required_sessions: int = Field(ge=0)
    approval_required_count: int = Field(ge=0)
    blocker_override_count: int = Field(ge=0)
    risk_false_allow_count: int = Field(ge=0)
    incident_count: int = Field(ge=0)
    renewal_sessions: int = Field(ge=0)
    cap_breach_count: int = Field(ge=0)
    rollback_drill_fresh: bool
    observed_at: datetime
    fresh_through: datetime


class IncidentPolicy(FrozenModel):
    critical_stop_seconds: Literal[30]
    critical_append_seconds: Literal[120]
    high_stop_seconds: Literal[60]
    high_append_seconds: Literal[300]
    medium_stop_seconds: Literal[300]
    medium_append_seconds: Literal[900]
    clean_sessions_for_repromotion: Literal[5]
    first_repromotion_cap_pct: Literal[50]


class SourceBindings(FrozenModel):
    paper_ledger: str
    approval_dry_run: str
    order_reconciliation: str
    risk_controls: str
    promotion_policy: str
    observation_window: str
    kill_switch: str


class KillSwitchProof(FrozenModel):
    kill_switch_id: str
    scope: Literal["global", "market", "ticker", "none"]
    scope_value: str | None = None
    switch_status: Literal["active", "inactive"]
    hash_chain_verified: bool
    record_hash: str


class PromotionRequest(FrozenModel):
    promotion_status_before: PromotionStatus
    promotion_status_after: PromotionStatus
    requested_by: str
    approved_by: str
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    idempotency_key: str
    eligible_scope: EligibleScope
    blast_radius_caps: BlastRadiusCaps
    observation_window: ObservationWindow
    incident_policy: IncidentPolicy
    source_bindings: SourceBindings
    kill_switch_proof: KillSwitchProof


class AutomationEvidence(FrozenModel):
    proposal_id: str
    trading_session: str
    ticker: str
    market: Literal["KR"]
    side: Side
    risk_reducing: bool
    order_type: Literal["limit"]
    estimated_notional: Decimal = Field(gt=0)
    estimated_fee: Decimal = Field(ge=0)
    estimated_tax: Decimal = Field(ge=0)
    symbol_daily_notional_before: Decimal = Field(ge=0)
    total_daily_notional_before: Decimal = Field(ge=0)
    concurrent_requests: int = Field(ge=0)
    market_open: bool
    quote_fresh: bool
    risk_status: Literal["allowed"]
    destination: Literal["broker_dry_run", "internal_dry_run"]
    live_submission: bool
    real_order_created: bool
    portfolio_mutated: bool

    @field_validator("trading_session")
    @classmethod
    def validate_trading_session(cls, value: str) -> str:
        session_date, separator, session_scope = value.partition("/")
        _ = date.fromisoformat(session_date)
        if separator != "/" or session_scope != "KR/regular":
            raise PydanticCustomError(
                "trading_session_format",
                "trading session must use YYYY-MM-DD/KR/regular",
            )
        return value


class PromotionDecision(FrozenModel):
    schema_version: Literal["v8.limited_automation_promotion.decision.1"]
    promotion_decision_id: str = Field(pattern=r"^prom_v8_[0-9a-f]{20}$")
    promotion_status_before: PromotionStatus
    promotion_status_after: PromotionStatus
    requested_by: str
    approved_by: str
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    eligible_scope: EligibleScope
    blast_radius_caps: BlastRadiusCaps
    observation_window: ObservationWindow
    incident_policy: IncidentPolicy
    source_hashes: SourceBindings
    kill_switch: KillSwitchProof
    idempotency_key: str
    prev_record_hash: str
    record_hash: str


class AutomationResult(FrozenModel):
    schema_version: Literal["v8.limited_automation_promotion.automation_request.1"]
    automation_request_id: str
    promotion_decision_id: str
    promotion_status: Literal["limited_automation"]
    sampled: bool
    evidence: AutomationEvidence
    destination: Literal["broker_dry_run", "internal_dry_run"]
    idempotency_key: str
    source_hashes: SourceBindings
    dry_run_request_allowed: Literal[True]
    real_order_created: Literal[False]
    portfolio_mutated: Literal[False]
    prev_record_hash: str
    record_hash: str


class PromotionArtifact(FrozenModel):
    schema_version: Literal["v8.limited_automation_promotion.artifact.1"]
    source_input_hash: str
    promotion_status: Literal["limited_automation"]
    decision: PromotionDecision
    automation_result: AutomationResult


class IncidentEvidence(FrozenModel):
    promotion_status_before: Literal["limited_automation"]
    detected_at: datetime
    reason_codes: tuple[str, ...] = Field(min_length=1)
    market: str
    ticker: str
    side: Side
    checked_at: datetime
    quote_expires_at: datetime
    reported_freshness_result: Literal["fresh"]
    new_automation_stopped_at: datetime
    incident_appended_at: datetime
    source_hashes: SourceBindings
    live_submission: bool
    real_order_created: bool
    portfolio_mutated: bool


class IncidentRecord(FrozenModel):
    schema_version: Literal["v8.limited_automation_promotion.incident.1"]
    incident_id: str
    promotion_status: PromotionStatus
    severity: Severity
    evidence: IncidentEvidence
    kill_switch: KillSwitchProof
    stop_sla_met: bool
    append_sla_met: bool
    dry_run_request_allowed: bool
    prev_record_hash: str
    record_hash: str


class RepromotionEvidence(FrozenModel):
    root_cause: str
    affected_scope: str
    corrective_artifact_hash: str
    clean_sessions: int = Field(ge=0)
    prior_caps: BlastRadiusCaps
    proposed_caps: BlastRadiusCaps
    requested_by: str
    approved_by: str
    incident_operator: str
    kill_switch_proof: KillSwitchProof
    replay_clean: bool
    same_scope_incident_count: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class IncidentDisposition:
    severity: Severity
    promotion_status_after: PromotionStatus
    switch_scope: Literal["global", "ticker", "none"]
    stop_sla_seconds: int
    append_sla_seconds: int
    automatic: bool


@dataclass(frozen=True, slots=True)
class CompilePromotionResult:
    artifact: PromotionArtifact | IncidentRecord | None
    error_code: PromotionErrorCode | None = None


class PromotionVerificationResult(FrozenModel):
    verification_status: Literal["pass", "fail"]
    promotion_status: PromotionStatus
    errors: tuple[PromotionErrorCode, ...]
    dry_run_request_allowed: bool
    real_order_created: bool
    portfolio_mutated: bool
