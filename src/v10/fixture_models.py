from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from .models import CalendarSession, Market, StrictModel, Symbol
from .sources import SourceFixture


class CalendarInput(StrictModel):
    market: Market
    calendar_id: str
    timezone: str
    version: str
    observed_at: datetime
    sessions: tuple[CalendarSession, ...]


class MinuteInput(StrictModel):
    interval_start: datetime
    interval_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    observed_at: datetime
    revision: int


class Prd01Fixture(StrictModel):
    schema_version: Literal["v10.prd01.fixture.1"]
    calendar: CalendarInput
    us_calendar: CalendarInput
    source: SourceFixture
    minutes: tuple[MinuteInput, ...]


class AggregateMinuteInput(StrictModel):
    start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    observed_at: datetime


class RevisionInput(StrictModel):
    minute_index: int
    revision: int
    close: Decimal
    observed_at: datetime


class Prd02Fixture(StrictModel):
    schema_version: Literal["v10.prd02.fixture.1"]
    market: Market
    symbol: Symbol
    session_date: date
    evaluated_at: datetime
    max_observation_lag_seconds: int
    minutes: tuple[AggregateMinuteInput, ...]
    revision: RevisionInput


class CandidateOverride(StrictModel):
    index: int
    instrument_type: str | None = None
    listed_sessions: int | None = None


class CandidateSeed(StrictModel):
    count: int
    symbol_prefix: str
    first_turnover: Decimal
    turnover_step: Decimal
    sessions: int
    overrides: tuple[CandidateOverride, ...]


class EligibilityInput(StrictModel):
    blocked_index: int
    effective_at: datetime
    reason: str


class CorporateActionInput(StrictModel):
    symbol: Symbol
    action_type: Literal["split", "reverse_split", "dividend", "rights"]
    effective_at: datetime
    observed_at: datetime
    adjustment_factor: Decimal


class PriceInput(StrictModel):
    cutoff: datetime
    raw_price: Decimal


class Prd03Fixture(StrictModel):
    schema_version: Literal["v10.prd03.fixture.1"]
    market: Market
    secondary_market: Market
    secondary_symbol_prefix: str
    ranking_date: date
    effective_date: date
    candidate_seed: CandidateSeed
    eligibility: EligibilityInput
    corporate_action: CorporateActionInput
    price: PriceInput


class ContextInput(StrictModel):
    context_type: Literal["news", "filing", "corporate_event", "regulatory"]
    symbols: tuple[Symbol, ...]
    sectors: tuple[str, ...]
    published_at: datetime
    observed_at: datetime
    ingested_at: datetime
    text: str
    source_identity: str
    archival_copy_verified: bool
    revision: int
    supersedes_index: int | None = None


class BackfillProbeInput(StrictModel):
    context_index: int
    cutoff: datetime


class Prd04Fixture(StrictModel):
    schema_version: Literal["v10.prd04.fixture.1"]
    market: Market
    cutoff: datetime
    coverage: Literal["healthy", "gap"]
    contexts: tuple[ContextInput, ...]
    backfill_probe: BackfillProbeInput
