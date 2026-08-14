from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ArtifactMeta, ArtifactRef


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class ExternalRef(StrictModel):
    artifact_type: str
    artifact_id: str
    content_hash: str
    bundle_hash: str


class StrategyBarInput(StrictModel):
    series_id: str
    role: Literal["prior", "symbol", "benchmark"]
    benchmark_id: Literal["KR_BROAD_KS11", "US_BROAD_SPY"] | None
    symbol: str
    session_date: date
    interval_start: datetime
    interval_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(gt=0)
    complete: bool
    observed_at: datetime
    watermark_at: datetime
    source_ref: ExternalRef
    calendar_ref: ExternalRef
    adjustment_factor: Decimal


class StrategySeriesInput(StrictModel):
    series_id: str
    symbol: str
    benchmark_id: Literal["KR_BROAD_KS11", "US_BROAD_SPY"]
    adjustment_factor: Decimal
    risk_kill_at: datetime | None
    eligibility_refs: Annotated[tuple[ExternalRef, ...], Field(strict=False)]


class HistoricalObservationInput(StrictModel):
    series_id: str
    feature: str
    session_date: date
    minute_slot: int = Field(ge=0)
    value: Decimal


class CausalSizingInput(StrictModel):
    series_id: str
    market: Literal["KR", "US"]
    symbol: str
    causal_observed_at: datetime
    causal_close: Decimal
    prior_turnovers: Annotated[tuple[Decimal, ...], Field(strict=False)]


class TargetSnapshotInput(StrictModel):
    series_id: str
    market: Literal["KR", "US"]
    symbol: str
    target_at: datetime
    target_open: Decimal
    target_volume: int = Field(gt=0)
    source_ref: ExternalRef
    calendar_ref: ExternalRef


class BorrowInput(StrictModel):
    series_id: str
    market: Literal["KR", "US"]
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
    source_refs: Annotated[tuple[ExternalRef, ...], Field(strict=False)]


class StrategyInputFixture(StrictModel):
    schema_version: Literal["v10.strategy_input.fixture.1"]
    bars: Annotated[tuple[StrategyBarInput, ...], Field(strict=False)]
    series: Annotated[tuple[StrategySeriesInput, ...], Field(strict=False)]
    historical: Annotated[tuple[HistoricalObservationInput, ...], Field(strict=False)]
    causal_sizing: Annotated[tuple[CausalSizingInput, ...], Field(strict=False)]
    target_snapshots: Annotated[tuple[TargetSnapshotInput, ...], Field(strict=False)]
    borrows: Annotated[tuple[BorrowInput, ...], Field(strict=False)]


class StrategyBarArtifact(StrategyBarInput):
    meta: ArtifactMeta


class StrategySeriesArtifact(StrategySeriesInput):
    meta: ArtifactMeta
    prior_refs: Annotated[tuple[ArtifactRef, ...], Field(strict=False)]
    symbol_refs: Annotated[tuple[ArtifactRef, ...], Field(strict=False)]
    benchmark_refs: Annotated[tuple[ArtifactRef, ...], Field(strict=False)]
    historical_ref: ArtifactRef
    causal_ref: ArtifactRef
    target_ref: ArtifactRef
    borrow_ref: ArtifactRef


class HistoricalObservationArtifact(StrictModel):
    meta: ArtifactMeta
    series_id: str
    observations: Annotated[tuple[HistoricalObservationInput, ...], Field(strict=False)]


class CausalSizingArtifact(CausalSizingInput):
    meta: ArtifactMeta


class TargetSnapshotArtifact(TargetSnapshotInput):
    meta: ArtifactMeta


class BorrowArtifact(BorrowInput):
    meta: ArtifactMeta
