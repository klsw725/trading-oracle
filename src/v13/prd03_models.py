from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from src.v11.models import (
    Account,
    CostPolicy,
    LedgerEvent,
    Market,
    Position,
    RiskResult,
)
from src.v13.models import ScoredCandidate, StrictModel


@unique
class SwitchState(StrEnum):
    INCUMBENT = "incumbent"
    EXIT_PENDING = "exit_pending"
    EXIT_RECONCILED_FLAT = "exit_reconciled_flat"
    ENTRY_PENDING = "entry_pending"
    TERMINAL = "terminal"


class IncumbentBinding(StrictModel):
    market: Annotated[Market, Field(strict=False)]
    regular_session_id: str
    position_hash: str
    candidate_id: str
    strategy_id: str
    entry_at: Annotated[datetime, Field(strict=False)]
    composite_score: Annotated[Decimal, Field(ge=0, le=1)]
    binding_hash: str


class IncumbentSeed(StrictModel):
    position: Position
    regular_session_id: str
    candidate_id: str
    strategy_id: str
    entry_at: Annotated[datetime, Field(strict=False)]
    composite_score: Annotated[Decimal, Field(ge=0, le=1)]


class SwitchTimelineEvent(StrictModel):
    event_index: Annotated[StrictInt, Field(ge=0)]
    state: Annotated[SwitchState, Field(strict=False)]
    occurred_at: Annotated[datetime, Field(strict=False)]
    reason_code: str
    previous_event_hash: str
    event_hash: str


class SwitchExecution(StrictModel):
    account: Account
    incumbent: Position
    binding: IncumbentBinding
    challenger: ScoredCandidate
    regular_session_id: str
    evaluated_at: Annotated[datetime, Field(strict=False)]
    exit_execution_at: Annotated[datetime | None, Field(strict=False)]
    entry_execution_at: Annotated[datetime | None, Field(strict=False)]
    exit_target_volume: Annotated[StrictInt, Field(ge=0)]
    entry_target_volume: Annotated[StrictInt, Field(ge=0)]
    cost_policy: CostPolicy
    manifest_hash: str
    existing_returns: dict[str, Annotated[tuple[str, ...], Field(strict=False)]] = Field(
        default_factory=dict
    )
    released_reservation_ids: Annotated[tuple[str, ...], Field(strict=False)] = ()


class SwitchResult(StrictModel):
    state: Literal["held", "residual_incumbent", "flat", "challenger"]
    reason_code: str
    binding_hash: str
    exit_target_at: Annotated[datetime | None, Field(strict=False)]
    entry_target_at: Annotated[datetime | None, Field(strict=False)]
    residual_incumbent: Position | None
    challenger_position: Position | None
    exit_cost: str
    entry_cost: str
    entry_risk: RiskResult | None
    timeline: Annotated[tuple[SwitchTimelineEvent, ...], Field(strict=False)]
    ledger_events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    result_hash: str


class CircuitKey(StrictModel):
    market: Annotated[Market, Field(strict=False)]
    regular_session_id: str


class CircuitObservation(StrictModel):
    succeeded: bool
    reason_code: str


class CircuitState(StrictModel):
    key: CircuitKey
    recent: Annotated[tuple[CircuitObservation, ...], Field(strict=False)] = ()
    consecutive_failures: Annotated[StrictInt, Field(ge=0)] = 0
    is_open: bool = False


class SwitchFixtureIncumbent(StrictModel):
    candidate_id: str
    strategy_id: str
    symbol: str
    side: Literal["long", "short"]
    entry_at: Annotated[datetime, Field(strict=False)]
    composite_score: Decimal


class SwitchFixtureScores(StrictModel):
    below: Decimal
    exact: Decimal
    above: Decimal


class SwitchFixture(StrictModel):
    schema_version: Literal["v13.prd03.switch_fixture.1"]
    session_id: str
    incumbent: SwitchFixtureIncumbent
    challengers: SwitchFixtureScores
    expected_path: Annotated[tuple[SwitchState, ...], Field(strict=False)]
