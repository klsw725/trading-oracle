from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Final, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    InstanceOf,
    TypeAdapter,
)

from src.v4.models import JsonValue

type EventType = Literal[
    "PAPER_ACCOUNT_OPENED",
    "PAPER_RECOMMENDATION_ACCEPTED",
    "PAPER_ORDER_CREATED",
    "PAPER_FILL_RECORDED",
    "PAPER_POSITION_UPDATED",
    "PAPER_CORPORATE_ACTION_APPLIED",
    "PAPER_FEE_MODEL_CHANGED",
    "PAPER_RECONCILED",
    "PAPER_CORRECTION_RECORDED",
]
type QualityState = Literal[
    "available", "degraded", "blocked", "unknown", "not_applicable"
]
type Side = Literal["BUY", "SELL"]


_DECIMAL_INPUT: Final[TypeAdapter[str | Decimal]] = TypeAdapter(
    str | InstanceOf[Decimal]
)


def _require_decimal_string(value: JsonValue | Decimal) -> str | Decimal:
    return _DECIMAL_INPUT.validate_python(value)


type DecimalString = Annotated[
    Decimal, BeforeValidator(_require_decimal_string, json_schema_input_type=str)
]


class FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class EntityRef(FrozenModel):
    entity_type: str
    entity_id: str


class CashBalance(FrozenModel):
    currency: str
    cash: DecimalString


class PositionSummary(FrozenModel):
    paper_position_id: str
    ticker: str
    quantity: DecimalString = Field(ge=0)
    avg_price: DecimalString = Field(ge=0)
    cost_basis: DecimalString = Field(ge=0)


class FillSummary(FrozenModel):
    paper_fill_id: str
    gross_notional: DecimalString = Field(ge=0)
    fee: DecimalString = Field(ge=0)
    net_cash_delta: DecimalString


class AccountOpenedPayload(FrozenModel):
    cash: dict[str, DecimalString]
    positions: tuple[PositionSummary, ...]


class RecommendationPayload(FrozenModel):
    paper_recommendation_id: str
    ticker: str
    side: Side
    quantity: DecimalString = Field(gt=0)
    limit_price: DecimalString = Field(gt=0)
    order_intent: Literal["paper_only"]


class OrderPayload(FrozenModel):
    paper_order_id: str
    paper_recommendation_id: str
    side: Side
    quantity: DecimalString = Field(gt=0)
    limit_price: DecimalString = Field(gt=0)
    idempotency_key: str = Field(min_length=1)
    destination: str


class FillPayload(FrozenModel):
    paper_fill_id: str
    paper_order_id: str
    ticker: str
    side: Side
    quantity: DecimalString = Field(gt=0)
    fill_price: DecimalString = Field(gt=0)
    gross_notional: DecimalString = Field(gt=0)
    fee: DecimalString = Field(ge=0)
    tax: DecimalString | None = Field(default=None, ge=0)
    net_cash_delta: DecimalString
    price_source_id: str
    fill_rule: str


class PositionPayload(FrozenModel):
    paper_position_id: str
    ticker: str
    quantity: DecimalString = Field(ge=0)
    avg_price: DecimalString = Field(ge=0)
    cost_basis: DecimalString = Field(ge=0)
    cash_after: dict[str, DecimalString]


class CorporateActionPayload(FrozenModel):
    action: Literal["split", "reverse_split", "cash_dividend", "symbol_change"]
    ticker: str
    source_hash: str
    effective_at: datetime
    ratio_numerator: DecimalString | None = Field(default=None, gt=0)
    ratio_denominator: DecimalString | None = Field(default=None, gt=0)
    amount_per_share: DecimalString | None = Field(default=None, ge=0)
    new_ticker: str | None = None
    fractional_policy: Literal["allow", "cash_in_lieu"] | None = None


class FeeModelPayload(FrozenModel):
    currency: str
    fee_bps: DecimalString = Field(ge=0)
    sell_tax_bps: DecimalString = Field(ge=0)
    rounding: Literal["decimal_half_up_2dp"]
    effective_at: datetime


class ReconciledPayload(FrozenModel):
    paper_reconciliation_id: str
    replayed_cash: dict[str, DecimalString]
    replayed_positions_hash: str
    source: Literal["ledger_replay"]
    mismatch_count: int = Field(ge=0)


class CorrectionPayload(FrozenModel):
    corrected_event_id: str
    reason: str
    replacement_event_hash: str


class LedgerEventBase(FrozenModel):
    ledger_id: str
    paper_namespace: str
    event_id: str
    event_version: str
    occurred_at: datetime
    recorded_at: datetime
    entity_ref: EntityRef
    prev_event_hash: str
    quality_state: QualityState
    event_hash: str

class AccountOpenedEvent(LedgerEventBase):
    event_type: Literal["PAPER_ACCOUNT_OPENED"]
    payload: AccountOpenedPayload


class RecommendationEvent(LedgerEventBase):
    event_type: Literal["PAPER_RECOMMENDATION_ACCEPTED"]
    payload: RecommendationPayload


class OrderEvent(LedgerEventBase):
    event_type: Literal["PAPER_ORDER_CREATED"]
    payload: OrderPayload


class FillEvent(LedgerEventBase):
    event_type: Literal["PAPER_FILL_RECORDED"]
    payload: FillPayload


class PositionEvent(LedgerEventBase):
    event_type: Literal["PAPER_POSITION_UPDATED"]
    payload: PositionPayload


class CorporateActionEvent(LedgerEventBase):
    event_type: Literal["PAPER_CORPORATE_ACTION_APPLIED"]
    payload: CorporateActionPayload


class FeeModelEvent(LedgerEventBase):
    event_type: Literal["PAPER_FEE_MODEL_CHANGED"]
    payload: FeeModelPayload


class ReconciledEvent(LedgerEventBase):
    event_type: Literal["PAPER_RECONCILED"]
    payload: ReconciledPayload


class CorrectionEvent(LedgerEventBase):
    event_type: Literal["PAPER_CORRECTION_RECORDED"]
    payload: CorrectionPayload


type LedgerEvent = Annotated[
    AccountOpenedEvent
    | RecommendationEvent
    | OrderEvent
    | FillEvent
    | PositionEvent
    | CorporateActionEvent
    | FeeModelEvent
    | ReconciledEvent
    | CorrectionEvent,
    Field(discriminator="event_type"),
]
