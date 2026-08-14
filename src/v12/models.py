from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, ClassVar, Literal, override

from pydantic import BaseModel, ConfigDict, Field

from src.v11.models import Account, CostPolicy, GateInputs


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


@unique
class Market(StrEnum):
    KR = "KR"
    US = "US"


@unique
class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


@unique
class Scenario(StrEnum):
    HAPPY = "happy"
    NO_SIGNAL = "no_signal"
    MISSING = "missing"


class ArtifactRef(StrictModel):
    artifact_type: str
    artifact_id: str
    content_hash: str
    bundle_hash: str


class BundleRef(StrictModel):
    version: Literal["v10", "v10_strategy_input", "v11"]
    path: str
    bundle_hash: str
    artifact_refs: Annotated[tuple[ArtifactRef, ...], Field(strict=False)]


class Bar(StrictModel):
    ref: ArtifactRef
    source_ref: ArtifactRef
    calendar_ref: ArtifactRef
    session_date: date
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(gt=0)
    complete: bool
    observed_at: datetime
    watermark_at: datetime
    adjustment_factor: Decimal


class HistoricalValue(StrictModel):
    ref: ArtifactRef | None = None
    session_date: date
    minute_slot: int = Field(ge=0)
    value: Decimal


class BorrowEligibility(StrictModel):
    ref: ArtifactRef | None = None
    market: Market
    symbol: str
    effective_from: datetime
    effective_until: datetime
    evaluated_at: datetime
    recalled_at: datetime | None
    annual_fee: Decimal
    locate: bool
    etb: bool
    shortable: bool
    regulation_known: bool
    refs: Annotated[tuple[ArtifactRef, ...], Field(strict=False)]

    @property
    def eligible(self) -> bool:
        return self.locate and self.etb and self.shortable and self.regulation_known


class ExecutionSnapshot(StrictModel):
    ref: ArtifactRef | None = None
    target_at: datetime
    open: Decimal
    volume: int = Field(gt=0)
    source_ref: ArtifactRef
    calendar_ref: ArtifactRef
    watermark_ref: ArtifactRef
    snapshot_hash: str


class CausalSizingObservation(StrictModel):
    ref: ArtifactRef | None = None
    observed_at: datetime
    close: Decimal
    prior_turnovers: Annotated[tuple[Decimal, ...], Field(strict=False)]


class ExecutionBinding(StrictModel):
    cutoff: datetime
    causal_sizing: CausalSizingObservation
    execution_snapshot: ExecutionSnapshot


class StrategyInput(StrictModel):
    market: Market
    symbol: str
    sector: str
    benchmark_id: Literal["KR_BROAD_KS11", "US_BROAD_SPY"]
    session_date: date
    regular_open: datetime
    regular_close: datetime
    watermark_at: datetime
    adjustment_factor: Decimal
    previous_adjusted_close: Decimal
    risk_kill_at: datetime | None
    bars: Annotated[tuple[Bar, ...], Field(strict=False)]
    prior_bars: Annotated[tuple[Bar, ...], Field(strict=False)]
    benchmark_bars: Annotated[tuple[Bar, ...], Field(strict=False)]
    historical: dict[str, Annotated[tuple[HistoricalValue, ...], Field(strict=False)]]
    eligibility_refs: Annotated[tuple[ArtifactRef, ...], Field(strict=False)]
    borrow: BorrowEligibility | None
    causal_sizing: CausalSizingObservation
    execution_snapshot: ExecutionSnapshot
    execution_bindings: Annotated[tuple[ExecutionBinding, ...], Field(strict=False)] = ()


class ParameterSet(StrictModel):
    parameter_set_id: str
    values: dict[str, Decimal]


class StrategySpec(StrictModel):
    strategy_id: str
    version: Literal["v12.2"]
    side: Side
    evaluator: str
    parameter_sets: Annotated[tuple[ParameterSet, ...], Field(strict=False)]


class FixtureCase(StrictModel):
    strategy_id: str
    scenario: Scenario
    expected_result: Literal["candidate", "no_signal", "missing_feature"]
    input: StrategyInput


class ExecutionInputs(StrictModel):
    account: Account
    historical_turnovers: Annotated[tuple[str, ...], Field(strict=False)]
    gates: GateInputs
    cost_policy: CostPolicy


class CohortFixture(StrictModel):
    schema_version: Literal["v12.strategy.fixture.2"]
    upstream_bundles: Annotated[tuple[BundleRef, ...], Field(strict=False)]
    cases: Annotated[tuple[FixtureCase, ...], Field(strict=False)]
    expected_case_ids: Annotated[tuple[str, ...], Field(strict=False)]
    execution: ExecutionInputs


@dataclass(frozen=True, slots=True)
class V12ContractError(Exception):
    code: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"
