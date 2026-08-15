from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field

from src.v11.models import CostBreakdown, CostPolicy, OrderAction

from .cohort_models import JsonDate, JsonMarket
from .contract import StrictModel
from .selection_models import JsonDecimal


@unique
class ResearchSegment(StrEnum):
    VALIDATION = "validation"
    HOLDOUT = "holdout"


JsonSegment = Annotated[ResearchSegment, Field(strict=False)]
JsonAction = Annotated[OrderAction, Field(strict=False)]


class RunDescriptor(StrictModel):
    market: JsonMarket
    segment: JsonSegment
    hypothesis_id: str
    configuration_id: str = "unbound_fixture_template"
    nav: JsonDecimal
    traded_notional: JsonDecimal
    gross_base: JsonDecimal
    gross_wave: Annotated[
        tuple[JsonDecimal, ...], Field(strict=False, min_length=1)
    ]
    trade_day_modulus: int = Field(gt=0)
    signal_skip_modulus: int = Field(gt=1)
    completed_trades_per_trade: int = Field(gt=0)
    wins_per_trade: int = Field(ge=0)


class DailyObservation(StrictModel):
    session_date: JsonDate
    revision_observed_at: JsonDate
    action: JsonAction
    nav: JsonDecimal
    gross_excess_return: JsonDecimal
    traded_notional: JsonDecimal
    pre_portfolio_candidates: int = Field(ge=0)
    completed_trades: int = Field(ge=0)
    winning_trades: int = Field(ge=0)
    turnover: JsonDecimal
    integrity_valid: bool


class DailyRunInput(StrictModel):
    plan_manifest_hash: str
    market: JsonMarket
    segment: JsonSegment
    hypothesis_id: str
    configuration_id: str
    calendar_hash: str
    official_sessions: Annotated[tuple[JsonDate, ...], Field(strict=False)]
    observations: Annotated[tuple[DailyObservation, ...], Field(strict=False)]
    cost_policy: CostPolicy


class DailySeriesPoint(StrictModel):
    session_date: JsonDate
    gross_excess_return: JsonDecimal
    baseline_net_excess_return: JsonDecimal
    stress_net_excess_return: JsonDecimal
    baseline_costs: CostBreakdown
    stress_costs: CostBreakdown
    traded_notional: JsonDecimal
    pre_portfolio_candidates: int
    completed_trades: int
    winning_trades: int
    turnover: JsonDecimal
    integrity_valid: bool


class DailySeriesBody(StrictModel):
    schema_version: Literal["v14.daily_series.1"]
    plan_manifest_hash: str
    market: JsonMarket
    segment: JsonSegment
    hypothesis_id: str
    configuration_id: str
    calendar_hash: str
    official_sessions: Annotated[tuple[JsonDate, ...], Field(strict=False)]
    points: Annotated[tuple[DailySeriesPoint, ...], Field(strict=False)]


class DailySeriesArtifact(DailySeriesBody):
    series_hash: str


class CostFixture(StrictModel):
    schema_version: Literal["v14.prd02.input.1"]
    policy: CostPolicy
    stress_model_id: str
    descriptors: Annotated[tuple[RunDescriptor, ...], Field(strict=False)]


class CostReplayInput(StrictModel):
    policy: CostPolicy
    market: JsonMarket
    action: JsonAction
    notional: JsonDecimal
