from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, unique
from pathlib import Path
from typing import ClassVar, Literal, NewType, override

from pydantic import BaseModel, ConfigDict, Field

from src.v8.event_models import (
    CashBalance,
    DecimalString,
    FillSummary,
    FrozenModel,
    LedgerEvent,
    PositionSummary,
    Side,
)

PaperRecommendationId = NewType("PaperRecommendationId", str)
PaperOrderId = NewType("PaperOrderId", str)
PaperFillId = NewType("PaperFillId", str)
PaperPositionId = NewType("PaperPositionId", str)
PaperEventId = NewType("PaperEventId", str)
PaperReconciliationId = NewType("PaperReconciliationId", str)


@unique
class FailureCode(StrEnum):
    STALE_STATE = "stale_state"
    DIRTY_WORKTREE = "dirty_worktree"
    MISLEADING_SUCCESS_OUTPUT = "misleading_success_output"
    MALFORMED_INPUT = "malformed_input"
    REPEATED_INTERRUPTION = "repeated_interruption"
    LIVE_STATE_CONTAMINATION = "live_state_contamination"
    BROKEN_HASH_CHAIN = "broken_hash_chain"
    CASH_MISMATCH = "cash_mismatch"
    POSITION_MISMATCH = "position_mismatch"
    FEE_MISMATCH = "fee_mismatch"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


@dataclass(frozen=True, slots=True)
class LedgerContractError(Exception):
    code: FailureCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


class FeeModel(FrozenModel):
    currency: str
    fee_bps: DecimalString = Field(ge=0)
    sell_tax_bps: DecimalString = Field(ge=0)
    rounding: Literal["decimal_half_up_2dp"]


class VirtualCash(FrozenModel):
    currency: str
    opening_balance: DecimalString
    delta: DecimalString
    closing_balance: DecimalString


class VirtualPosition(FrozenModel):
    paper_position_id: str
    ticker: str
    market: str
    currency: str
    quantity: DecimalString = Field(ge=0)
    average_price: DecimalString = Field(ge=0)
    cost_basis: DecimalString = Field(ge=0)
    realized_pnl: DecimalString


class Recommendation(FrozenModel):
    paper_recommendation_id: str
    schema_version: str
    paper_namespace: str
    decision_at: datetime
    ticker: str
    side: Side
    quantity: DecimalString = Field(gt=0)
    limit_price: DecimalString = Field(gt=0)
    source_recommendation_fingerprint: str
    external_recommendation_ref: str | None = None


class ExpectedReplay(FrozenModel):
    cash: dict[str, DecimalString]
    positions: tuple[PositionSummary, ...]
    fills: tuple[FillSummary, ...]
    last_reconciliation_id: str
    idempotency_key: str


class PaperLedgerFixture(FrozenModel):
    schema_version: str
    fixture_name: str
    paper_namespace: str
    live_namespace_forbidden: bool
    credential_fields_forbidden: tuple[str, ...]
    fee_model: FeeModel
    starting_balances: tuple[CashBalance, ...]
    recommendation: Recommendation
    expected_after_replay: ExpectedReplay
    events: tuple[LedgerEvent, ...]


class PaperLedgerArtifact(PaperLedgerFixture):
    source_input_hash: str


class VerificationContext(FrozenModel):
    replay_cutoff: datetime
    declared_input_hash: str
    observed_input_hash: str
    claimed_success: bool


class ReplayedPosition(FrozenModel):
    paper_position_id: str
    ticker: str
    currency: str
    quantity: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal


class VerificationResult(FrozenModel):
    state: Literal["pass", "fail", "blocked"]
    errors: tuple[FailureCode, ...]
    cash: dict[str, str]
    positions: tuple[PositionSummary, ...]
    fills: tuple[FillSummary, ...]
    last_event_hash: str
    forbidden_keys: tuple[str, ...]
    broker_destinations: tuple[str, ...]
    live_orders: tuple[str, ...]


class CliOutput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    state: Literal["pass", "fail"]
    detail: str
    output: Path | None = None
