from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum, unique
from typing import Annotated, Literal, override

from pydantic import BeforeValidator, Field
from pydantic_core import PydanticCustomError

from src.v4.models import JsonValue
from src.v8.event_models import FrozenModel, Side

type OrderStatus = Literal[
    "submitted", "accepted", "partial", "filled", "cancelled", "rejected", "unknown"
]
type Currency = Literal["KRW", "USD"]


def _parse_decimal_string(value: JsonValue | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as error:
            raise PydanticCustomError(
                "decimal_string", "Input should be a valid decimal string"
            ) from error
    raise PydanticCustomError(
        "decimal_string", "Input should be a valid decimal string"
    )


type DecimalString = Annotated[Decimal, BeforeValidator(_parse_decimal_string)]


@unique
class ReconciliationErrorCode(StrEnum):
    MALFORMED_INPUT = "malformed_input"
    BROKER_TRUTH_CONTRADICTION = "broker_truth_contradiction"
    STALE_BROKER_TRUTH = "stale_broker_truth"
    BROKEN_HASH_CHAIN = "broken_hash_chain"
    RECORD_HASH_MISMATCH = "record_hash_mismatch"
    FILL_QUANTITY_MISMATCH = "fill_quantity_mismatch"
    CASH_MISMATCH = "cash_mismatch"
    POSITION_MISMATCH = "position_mismatch"
    TERMINAL_MISMATCH = "terminal_mismatch"
    DUPLICATE_FILL_FRAGMENT = "duplicate_fill_fragment"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    REORDER_BLOCKED_UNDER_UNKNOWN = "reorder_blocked_under_unknown"
    LIVE_STATE_CONTAMINATION = "live_state_contamination"
    MISLEADING_SUCCESS_OUTPUT = "misleading_success_output"


@dataclass(frozen=True, slots=True)
class ReconciliationContractError(Exception):
    code: ReconciliationErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


class ExecutionOrder(FrozenModel):
    schema_version: Literal["v8.order_reconciliation.execution_order.1"]
    execution_order_id: str
    proposed_order_id: str = Field(pattern=r"^aprop_v8_")
    dry_run_response_id: str = Field(pattern=r"^adry_v8_")
    ticker: str = Field(min_length=1)
    side: Side
    order_type: Literal["market", "limit"]
    quantity: DecimalString = Field(gt=0)
    limit_price: DecimalString | None = Field(default=None, gt=0)
    currency: Currency
    idempotency_key: str = Field(min_length=1)
    order_status: Literal["submitted"]
    broker_order_ref_hash: str
    record_hash: str


class BrokerAdapter(FrozenModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    mode: Literal["redacted_truth_snapshot"]


class FillFragment(FrozenModel):
    fill_fragment_id: str
    sequence: int = Field(gt=0)
    filled_at: datetime
    quantity: DecimalString = Field(gt=0)
    price: DecimalString = Field(gt=0)
    gross_notional: DecimalString = Field(gt=0)
    fee: DecimalString = Field(ge=0)
    tax: DecimalString = Field(ge=0)
    record_hash: str | None = None


class BrokerTruth(FrozenModel):
    schema_version: Literal["v8.order_reconciliation.broker_truth.1"]
    broker_truth_id: str
    broker_adapter: BrokerAdapter
    observed_at: datetime
    truth_fresh_until: datetime
    broker_order_ref_hash: str
    order_status: OrderStatus
    ticker: str
    side: Side
    currency: Currency
    original_quantity: DecimalString = Field(gt=0)
    cumulative_filled_quantity: DecimalString = Field(ge=0)
    remaining_quantity: DecimalString = Field(ge=0)
    fill_fragments: tuple[FillFragment, ...]
    fee_total: DecimalString = Field(ge=0)
    tax_total: DecimalString = Field(ge=0)
    forbidden_fields_absent: Literal[True]
    accepted_at: datetime | None = None
    terminal_fill_at: datetime | None = None
    cancelled_at: datetime | None = None
    reject_code: str | None = None
    rejected_at: datetime | None = None
    record_hash: str


class PositionDelta(FrozenModel):
    ticker: str
    quantity_delta: DecimalString
    cost_basis_delta: DecimalString
    avg_price_after: DecimalString = Field(ge=0)


class PortfolioDelta(FrozenModel):
    portfolio_delta_id: str
    order_status: OrderStatus
    cash_before: dict[Currency, DecimalString]
    cash_delta: dict[Currency, DecimalString]
    cash_after: dict[Currency, DecimalString]
    position_delta: PositionDelta
    portfolio_state_before_hash: str
    portfolio_state_after_hash: str
    record_hash: str


class ExpectedArithmetic(FrozenModel):
    gross_notional: DecimalString
    fee: DecimalString
    tax: DecimalString
    cash_delta: DecimalString
    cash_after: DecimalString
    remaining_quantity: DecimalString


class Reconciliation(FrozenModel):
    order_reconciliation_id: str
    as_of: datetime
    order_status: OrderStatus
    matched_checks: tuple[str, ...]
    mismatches: tuple[ReconciliationErrorCode, ...] = ()
    mismatch_count: int = Field(ge=0)
    quality_result: Literal["pass", "fail"] = "pass"
    reorder_allowed: Literal[False]
    operator_review_required: bool = False
    allowed_next_action: Literal["refresh_broker_truth_for_same_ref_hash"] | None = None
    expected_arithmetic: ExpectedArithmetic | None = None
    prev_record_hash: str
    record_hash: str


class HappyFixture(FrozenModel):
    schema_version: Literal["v8.order_reconciliation.prd03.fixture.1"]
    fixture_name: str
    strict_no_real_order: Literal[True]
    forbidden_fields: tuple[str, ...]
    execution_order: ExecutionOrder
    broker_truth: BrokerTruth
    portfolio_delta: PortfolioDelta
    reconciliation: Reconciliation


class TruthFailure(FrozenModel):
    observed_at: datetime
    truth_fresh_until: datetime
    broker_order_ref_hash: str
    order_status: OrderStatus
    cumulative_filled_quantity: DecimalString = Field(ge=0)
    remaining_quantity: DecimalString = Field(ge=0)
    contradiction: str


class UnknownExpected(FrozenModel):
    order_status: Literal["unknown"]
    mismatch: Literal["broker_truth_contradiction"]
    cash_delta_appended: Literal[False]
    position_delta_appended: Literal[False]
    reorder_allowed: Literal[False]
    operator_review_required: Literal[True]
    allowed_next_action: Literal["refresh_broker_truth_for_same_ref_hash"]


class UnknownFixture(FrozenModel):
    schema_version: Literal["v8.order_reconciliation.prd03.failure_fixture.1"]
    fixture_name: str
    strict_no_real_order: Literal[True]
    forbidden_fields: tuple[str, ...]
    execution_order: ExecutionOrder
    submitted_at: datetime
    truth_failure: TruthFailure
    expected_result: UnknownExpected
    record_hash: str


class ReconciliationRecord(FrozenModel):
    schema_version: Literal["v8.order_reconciliation.record.1"]
    artifact_type: Literal["execution_order", "broker_truth", "fill_fragment", "portfolio_delta", "reconciliation"]
    artifact_id: str
    order_status: OrderStatus
    payload: JsonValue
    source_hashes: tuple[str, ...]
    prev_record_hash: str
    record_hash: str


class ReconciliationArtifact(FrozenModel):
    schema_version: Literal["v8.order_reconciliation.artifact.1"]
    source_input_hash: str
    execution_seed_hash: str
    order_status: OrderStatus
    execution_order: ExecutionOrder
    broker_truth: BrokerTruth | None = None
    fill_fragments: tuple[FillFragment, ...]
    portfolio_delta: PortfolioDelta | None = None
    reconciliation: Reconciliation
    records: tuple[ReconciliationRecord, ...]
    cash_delta_appended: bool
    position_delta_appended: bool
    reorder_allowed: Literal[False]
    real_order_created: Literal[False]
    portfolio_mutated: Literal[False]


@dataclass(frozen=True, slots=True)
class CompileReconciliationResult:
    order_status: OrderStatus
    artifact: ReconciliationArtifact | None
    error_code: ReconciliationErrorCode | None = None


class ReconciliationVerificationResult(FrozenModel):
    verification_status: Literal["pass", "fail"]
    order_status: OrderStatus
    errors: tuple[ReconciliationErrorCode, ...]
    record_count: int
    fill_count: int
    cash_delta_appended: bool
    position_delta_appended: bool
    reorder_allowed: bool
    real_order_created: bool
    portfolio_mutated: bool
