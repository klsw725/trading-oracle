from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, unique
from typing import Literal, override

from pydantic import Field

from src.v8.event_models import FrozenModel, Side

type RiskStatus = Literal["allowed", "blocked", "requires_ack", "kill_switch_active"]
type SwitchStatus = Literal["active", "reset_requested", "reset_approved", "inactive"]
type Scope = Literal["global", "market", "ticker", "side", "strategy", "operator"]


@unique
class RiskErrorCode(StrEnum):
    MALFORMED_INPUT = "json_malformed"
    RISK_STATUS_TAMPERED = "risk_status_tampered"
    RECORD_HASH_MISMATCH = "record_hash_mismatch"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    STALE_QUOTE_FALSELY_FRESH = "stale_quote_falsely_fresh"
    MARKET_HOURS_CONTRADICTION = "market_hours_contradiction"
    CASH_INSUFFICIENT = "cash_insufficient"
    POSITION_INSUFFICIENT = "position_insufficient"
    DAILY_LOSS_LIMIT_HIT = "daily_loss_limit_hit"
    KILL_SWITCH_UNREADABLE = "kill_switch_unreadable"
    ACK_OVERRIDE_BLOCKER = "ack_override_blocker"
    MISLEADING_RISK_SUCCESS = "misleading_risk_success"


@dataclass(frozen=True, slots=True)
class RiskContractError(Exception):
    code: RiskErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


class CashInput(FrozenModel):
    currency: Literal["KRW", "USD"]
    available_cash_after_floor: Decimal
    required_cash: Decimal
    cash_floor_after_order_pct: Decimal
    minimum_cash_floor_pct: Decimal = Decimal("20")


class PositionInput(FrozenModel):
    current_quantity: Decimal = Field(ge=0)
    post_order_quantity: Decimal = Field(ge=0)
    post_order_weight_pct: Decimal = Field(ge=0)
    max_weight_pct: Decimal = Field(ge=0)
    current_distinct_positions: int = Field(default=0, ge=0)
    max_positions: int = Field(default=3, gt=0)
    ticker_already_held: bool = False
    source_trusted: bool = True


class ConcentrationInput(FrozenModel):
    sector_weight_after_pct: Decimal
    max_sector_weight_pct: Decimal
    max_pair_correlation: Decimal
    pair_threshold: Decimal
    source_complete: bool = True


class MarketHoursInput(FrozenModel):
    market: str
    checked_at: datetime
    is_open: bool
    source_hash: str
    holiday: bool = False


class QuoteInput(FrozenModel):
    quote_id: str
    quote_as_of: datetime
    quote_expires_at: datetime
    freshness_result: Literal["fresh", "stale"]
    ticker: str | None = None
    currency: Literal["KRW", "USD"] | None = None
    source_hash: str | None = None


class DailyLossInput(FrozenModel):
    day_start_equity: Decimal = Field(gt=0)
    current_equity: Decimal = Field(ge=0)
    daily_pnl_pct: Decimal
    halt_threshold_pct: Decimal


class SwitchEvidence(FrozenModel):
    switch_status: Literal["active", "inactive"]
    covered_actions: tuple[Side, ...]
    readable: bool = True
    hash_chain_verified: bool = True
    coverage_determined: bool = True
    scope: Scope = "global"
    scope_value: str | None = None


class RiskInputs(FrozenModel):
    cash: CashInput
    position: PositionInput
    concentration: ConcentrationInput
    market_hours: MarketHoursInput
    quote: QuoteInput
    daily_loss: DailyLossInput
    kill_switch: SwitchEvidence


class RiskRequest(FrozenModel):
    proposed_order_id: str = Field(pattern=r"^aprop_v8_")
    paper_order_id: str = Field(pattern=r"^pord_v8_")
    ticker: str
    side: Side
    quantity: Decimal = Field(gt=0)
    currency: Literal["KRW", "USD"]
    estimated_notional: Decimal = Field(gt=0)
    estimated_fee: Decimal = Field(ge=0)
    estimated_tax: Decimal = Field(ge=0)
    idempotency_key: str = Field(min_length=1)
    inputs: RiskInputs
    ack_required_reasons: tuple[str, ...] = ()
    risk_increasing_action: bool = True
    fee_tax_known: bool = True


class RiskDecision(FrozenModel):
    schema_version: Literal["v8.risk_controls.decision.1"]
    risk_decision_id: str = Field(pattern=r"^risk_v8_[0-9a-f]{20}$")
    proposed_order_id: str
    paper_order_id: str
    ticker: str
    side: Side
    quantity: Decimal
    currency: Literal["KRW", "USD"]
    estimated_notional: Decimal
    estimated_fee: Decimal
    estimated_tax: Decimal
    risk_status: RiskStatus
    blocking_reasons: tuple[str, ...]
    ack_required_reasons: tuple[str, ...]
    source_hashes: dict[str, str]
    idempotency_key: str
    prev_record_hash: str
    fail_closed: bool
    next_allowed_destination: Literal["broker_dry_run"] | None = None
    dry_run_request_allowed: bool
    real_order_created: Literal[False]
    portfolio_mutated: Literal[False]
    record_hash: str


class RiskArtifact(FrozenModel):
    schema_version: Literal["v8.risk_controls.artifact.1"]
    source_input_hash: str
    request: RiskRequest
    decision: RiskDecision


class RiskAcknowledgement(FrozenModel):
    schema_version: Literal["v8.risk_controls.acknowledgement.1"]
    risk_ack_id: str
    risk_decision_id: str
    risk_version: str
    operator_ref: str
    permission: Literal["risk.acknowledge"]
    reason_code: str
    acknowledged_at: datetime
    expires_at: datetime
    source_hashes: dict[str, str]
    prev_record_hash: str
    record_hash: str


class KillSwitchRecord(FrozenModel):
    schema_version: Literal["v8.risk_controls.kill_switch.1"]
    kill_switch_id: str
    switch_status: SwitchStatus
    scope: Scope
    scope_value: str | None = None
    activated_by: str
    activated_at: datetime
    reason_codes: tuple[str, ...] = Field(min_length=1)
    covered_actions: tuple[Side, ...]
    reset_requirements: tuple[str, ...]
    source_hashes: dict[str, str]
    prev_record_hash: str
    record_hash: str


class ResetAttempt(FrozenModel):
    requester_ref: str
    reviewer_refs: tuple[str, ...]
    permissions: tuple[Literal["risk.kill_switch.reset"], ...]
    evidence: tuple[str, ...]
    requested_at: datetime
    reviewed_at: datetime
    cooldown_seconds: int = Field(ge=0)
    chain_recomputed: bool


class AckVerificationContext(FrozenModel):
    operator_ref: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ResetResult:
    reset_status: Literal["approved", "blocked"]
    records: tuple[KillSwitchRecord, ...]
    error_code: str | None = None


class RiskVerificationResult(FrozenModel):
    verification_status: Literal["pass", "fail"]
    risk_status: RiskStatus
    errors: tuple[RiskErrorCode, ...]
    fail_closed: bool
    dry_run_request_allowed: bool
    real_order_created: bool
    portfolio_mutated: bool
