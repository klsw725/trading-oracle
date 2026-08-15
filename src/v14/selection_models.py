from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from src.v12.models import Market

from .contract import StrictModel


JsonDecimal = Annotated[Decimal, Field(strict=False)]
JsonMarket = Annotated[Market, Field(strict=False)]


class ScoreTemplate(StrictModel):
    fold_returns: Annotated[tuple[JsonDecimal, ...], Field(strict=False)]
    turnover: JsonDecimal


class MarketScoreDescriptor(StrictModel):
    market: JsonMarket
    strategy_templates: Annotated[tuple[ScoreTemplate, ...], Field(strict=False)]
    router_templates: Annotated[tuple[ScoreTemplate, ...], Field(strict=False)]


class SelectionInputs(StrictModel):
    markets: Annotated[tuple[MarketScoreDescriptor, ...], Field(strict=False)]


class SelectionCandidate(StrictModel):
    canonical_id: str
    fold_oos_net_excess_returns: Annotated[
        tuple[JsonDecimal, ...], Field(strict=False)
    ]
    turnover: JsonDecimal


class DevelopmentGrid(StrictModel):
    segment: Literal["development"]
    candidates: Annotated[tuple[SelectionCandidate, ...], Field(strict=False)]


class SelectedConfig(StrictModel):
    canonical_id: str
    median_oos_net_excess_return: JsonDecimal
    turnover: JsonDecimal


class StrategySelection(StrictModel):
    strategy_id: str
    selected: SelectedConfig


class MarketSelection(StrictModel):
    market: JsonMarket
    strategies: Annotated[tuple[StrategySelection, ...], Field(strict=False)]
    router_policy: SelectedConfig


class DevelopmentSelectionBody(StrictModel):
    schema_version: Literal["v14.development_selection.1"]
    cohort_hash: str
    markets: Annotated[tuple[MarketSelection, ...], Field(strict=False)]


class DevelopmentSelection(DevelopmentSelectionBody):
    selection_hash: str
