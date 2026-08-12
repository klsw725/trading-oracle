from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Annotated, ClassVar, Literal, NewType, override

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.v4.models import JsonValue


Money = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")]
Quantity = Annotated[StrictInt, Field(ge=0)]
IntentId = NewType("IntentId", str)
EventHash = NewType("EventHash", str)


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="forbid", strict=True
    )


@unique
class Market(StrEnum):
    KR = "KR"
    US = "US"


@unique
class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


@unique
class OrderAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"


@unique
class EventType(StrEnum):
    SIGNAL_OBSERVED = "signal_observed"
    ORDER_INTENDED = "order_intended"
    RISK_CHECKED = "risk_checked"
    ORDER_ACCEPTED = "order_accepted"
    FILL_PARTIAL = "fill_partial"
    FILL_COMPLETE = "fill_complete"
    ORDER_CANCELLED = "order_cancelled"
    POSITION_UPDATED = "position_updated"
    COST_ACCRUED = "cost_accrued"
    RECONCILED = "reconciled"
    SESSION_CLOSED = "session_closed"


class Position(StrictModel):
    symbol: str
    side: Annotated[Side, Field(strict=False)]
    sector: str
    quantity: Quantity
    mark_price: Money


class Reservation(StrictModel):
    intent_id: IntentId
    cash: Money
    collateral: Money
    gross: Money
    net: Money
    sector: str
    expected_cost: Money


class Account(StrictModel):
    market: Annotated[Market, Field(strict=False)]
    currency: Literal["KRW", "USD"]
    prior_close_nav: Money
    cash: Money
    positions: Annotated[tuple[Position, ...], Field(strict=False)] = ()
    reservations: Annotated[tuple[Reservation, ...], Field(strict=False)] = ()
    halted: bool = False


class Decision(StrictModel):
    decision_id: str
    candidate_id: str
    router_decision_id: str
    strategy_id: str
    strategy_version: str
    market: Annotated[Market, Field(strict=False)]
    symbol: str
    sector: str
    side: Annotated[Side, Field(strict=False)]
    action: Literal["open"]
    cutoff: Annotated[datetime, Field(strict=False)]
    watermark_at: Annotated[datetime, Field(strict=False)]
    decision_ready_at: Annotated[datetime, Field(strict=False)]
    deterministic_score: Money
    market_input_hash: str = "sha256:local"


class GateInputs(StrictModel):
    eligible: bool
    session_open: bool
    data_fresh: bool
    borrow_allowed: bool
    liquidity_allowed: bool
    daily_loss_halted: bool
    execution_halted: bool
    accounting_consistent: bool = True


class GateResult(StrictModel):
    gate: str
    state: Literal["pass", "blocked", "not_evaluated"]
    reason_code: str


class RiskIncident(StrictModel):
    kind: Literal["exposure_drift", "accounting_mismatch"]
    market: Annotated[Market, Field(strict=False)]
    input_hash: str
    halt_requested: bool


class RiskResult(StrictModel):
    decision_id: str
    state: Literal["accepted", "blocked"]
    reason_code: str
    input_hash: str
    quantity: Quantity
    reference_price: Money
    target_notional: Money
    reservation: Reservation | None
    gates: Annotated[tuple[GateResult, ...], Field(strict=False)]


class CostBreakdown(StrictModel):
    commission: Money
    tax: Money
    spread: Money
    slippage: Money
    participation: Money
    borrow: Money
    locate: Money
    total: Money


class Fill(StrictModel):
    intent_id: IntentId
    target_at: datetime
    side: Annotated[Side, Field(strict=False)]
    action: Annotated[OrderAction, Field(strict=False)] = OrderAction.BUY
    requested_quantity: Quantity
    filled_quantity: Quantity
    cancelled_quantity: Quantity
    price: Money
    state: Literal["partial", "complete", "cancelled"]
    costs: CostBreakdown


class LedgerEvent(StrictModel):
    event_id: str
    event_index: StrictInt
    event_type: Annotated[EventType, Field(strict=False)]
    entity_id: str
    occurred_at: Annotated[datetime, Field(strict=False)]
    recorded_at: Annotated[datetime, Field(strict=False)]
    payload_hash: str
    previous_event_hash: EventHash
    event_hash: EventHash
    experiment_manifest_hash: str
    payload: dict[str, JsonValue]


class ReplayState(StrictModel):
    cash: Money
    positions: Annotated[tuple[Position, ...], Field(strict=False)]
    open_intents: Annotated[tuple[str, ...], Field(strict=False)]
    fill_quantity: Quantity
    accrued_cost: Money
    halted: bool
    tail_hash: EventHash


class ReplayCheckpoint(StrictModel):
    event_index: StrictInt
    state: ReplayState


class IntentReceipt(StrictModel):
    intent_id: IntentId
    identity_hash: str
    state: Literal["appended", "no_op"]


class ExecutionLedger(StrictModel):
    initial_cash: Money
    checkpoint: ReplayCheckpoint
    events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    source_snapshot: ReplayState


class MarketInput(StrictModel):
    market: Annotated[Market, Field(strict=False)]
    symbol: str
    reference_price: Money
    target_volume: Quantity
    watermark_at: Annotated[datetime, Field(strict=False)]
    regular_close: Annotated[datetime, Field(strict=False)]
    eligible: bool
    provenance_refs: Annotated[tuple[str, ...], Field(strict=False)]
    input_hash: str


class CostPolicy(StrictModel):
    version: str
    policy_hash: str
    effective_session: str
    prior_hash: str
    reviewer: str
    approved: bool
    commission_rate: Money
    kr_sell_tax_rate: Money
    spread_rate: Money
    slippage_rate: Money
    participation_rate: Money
    borrow_rate: Money
    locate_rate: Money


class Probe(StrictModel):
    probe_id: str
    owner_prd: Literal[1, 2, 3, 4]
    state: Literal["pass"]
    result_code: str


@dataclass(frozen=True, slots=True)
class V11ContractError(Exception):
    code: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"
