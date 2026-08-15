from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from src.v12.models import Market

from .contract import StrictModel


JsonDate = Annotated[date, Field(strict=False)]
JsonMarket = Annotated[Market, Field(strict=False)]


class MarketDescriptor(StrictModel):
    market: JsonMarket
    start: JsonDate
    month_count: int
    context_snapshot_hashes: Annotated[tuple[str, ...], Field(strict=False)]


class MonthRow(StrictModel):
    market: JsonMarket
    start: JsonDate
    end: JsonDate
    observed_at: JsonDate
    context_snapshot_hash: str


class Segment(StrictModel):
    role: Literal["development", "validation", "holdout"]
    start: JsonDate
    end: JsonDate
    months: Annotated[tuple[MonthRow, ...], Field(strict=False)]


class MarketCohort(StrictModel):
    market: JsonMarket
    development: Segment
    validation: Segment
    holdout: Segment


class FrozenCohortBody(StrictModel):
    schema_version: Literal["v14.frozen_cohort.1"]
    markets: Annotated[tuple[MarketCohort, ...], Field(strict=False)]


class FrozenCohort(FrozenCohortBody):
    cohort_hash: str
