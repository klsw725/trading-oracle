from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from .daily_loss import DailyLossInputs
from .models import CostPolicy, Decision, GateInputs, Market, Position, StrictModel


LooseDateTime = Annotated[datetime, Field(strict=False)]
LooseTuple = Annotated[tuple[str, ...], Field(strict=False)]


class RiskCase(StrictModel):
    decision: Decision
    reference_price: str
    historical_turnovers: LooseTuple
    expected_cost: str
    gates: GateInputs
    candidate_returns: LooseTuple | None = None
    existing_returns: dict[str, LooseTuple] = {}


class Prd01Fixture(StrictModel):
    schema_version: Literal["v11.prd01.fixture.2"]
    cases: Annotated[tuple[RiskCase, ...], Field(strict=False)]
    daily_loss_inputs: DailyLossInputs
    v10_fixtures: Annotated[tuple[str, ...], Field(strict=False)]


class MinuteExecution(StrictModel):
    decision: Decision
    requested_quantity: int
    target_volume: int
    target_open: str
    intent_recorded_at: LooseDateTime
    regular_close: LooseDateTime
    snapshot: "ExecutionSnapshot"


class ExecutionSnapshot(StrictModel):
    schema_version: Literal["v11.local_execution_snapshot.1"]
    market: Annotated[Market, Field(strict=False)]
    symbol: str
    interval_start: LooseDateTime
    interval_end: LooseDateTime
    open: str
    volume: int
    source_ref: str
    calendar_ref: str
    watermark_ref: str
    snapshot_hash: str


class BorrowInput(StrictModel):
    market: Annotated[Market, Field(strict=False)]
    symbol: str
    observed_at: LooseDateTime
    effective_from: LooseDateTime
    effective_until: LooseDateTime
    regulation_hash: str
    locate: bool
    etb: bool
    shortable: bool
    rule_known: bool
    annual_fee: str
    recalled_at: LooseDateTime | None


class Prd02Fixture(StrictModel):
    schema_version: Literal["v11.prd02.fixture.2"]
    executions: Annotated[tuple[MinuteExecution, ...], Field(strict=False)]
    borrow: BorrowInput
    daily_loss_positions: Annotated[tuple[Position, ...], Field(strict=False)]
    daily_loss_exit_at: LooseDateTime
    v10_fixtures: Annotated[tuple[str, ...], Field(strict=False)]
    cost_policy: CostPolicy
    prd01_fixture: str


class Prd03Fixture(StrictModel):
    schema_version: Literal["v11.prd03.fixture.2"]
    event_at: LooseDateTime
    initial_cash: str
    manifest_hash: str
    checkpoint_after: int
    source_cash: str


class Prd04Fixture(StrictModel):
    schema_version: Literal["v11.prd04.fixture.2"]
    destination: Literal["paper"]
    prd01_fixture: str
    prd02_fixture: str
    prd03_fixture: str
    v10_fixtures: Annotated[tuple[str, ...], Field(strict=False)]
