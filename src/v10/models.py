from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, Literal, NewType, override

from pydantic import BaseModel, ConfigDict


ArtifactId = NewType("ArtifactId", str)
ContentHash = NewType("ContentHash", str)
Symbol = NewType("Symbol", str)


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class Market(StrEnum):
    KR = "KR"
    US = "US"


class SessionState(StrEnum):
    REGULAR = "regular"
    AUCTION = "auction"
    HALTED = "halted"
    RESUMED = "resumed"


class ArtifactRef(StrictModel):
    role: str
    artifact_type: str
    artifact_id: ArtifactId
    content_hash: ContentHash


class ArtifactMeta(StrictModel):
    schema_version: str
    artifact_type: str
    artifact_id: ArtifactId
    content_hash: ContentHash
    lineage: tuple[ArtifactRef, ...]


class SessionInterval(StrictModel):
    state: SessionState
    start: datetime
    end: datetime


class CalendarSession(StrictModel):
    session_date: date
    open: bool
    regular_open: datetime | None
    regular_end: datetime | None
    early_close: bool
    intervals: tuple[SessionInterval, ...]


class MarketCalendarSnapshot(StrictModel):
    meta: ArtifactMeta
    market: Market
    calendar_id: str
    timezone: str
    version: str
    observed_at: datetime
    sessions: tuple[CalendarSession, ...]


class SourceObservation(StrictModel):
    meta: ArtifactMeta
    market: Market
    symbol: Symbol
    role: Literal["primary", "secondary"]
    source_identity: str
    adapter_version: str
    fetched_at: datetime
    observed_at: datetime
    source_timestamp: datetime
    outcome: Literal["success", "failure", "accepted_fallback"]
    selected: bool
    raw_payload_hash: str | None
    failure_code: str | None
    capabilities_verified: bool


class MinuteBar(StrictModel):
    meta: ArtifactMeta
    market: Market
    symbol: Symbol
    session_date: date
    interval_start: datetime
    interval_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    session_state: SessionState
    observed_at: datetime
    revision: int
    source_ref: ArtifactRef
    calendar_ref: ArtifactRef


class DataIncident(StrictModel):
    meta: ArtifactMeta
    code: str
    market: Market
    symbol: Symbol | None
    detected_at: datetime
    disposition: Literal["degraded", "blocked"]
    affected_refs: tuple[ArtifactRef, ...]


class FiveMinuteBar(StrictModel):
    meta: ArtifactMeta
    market: Market
    symbol: Symbol
    session_date: date
    interval_start: datetime
    interval_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    minute_refs: tuple[ArtifactRef, ...]
    evaluated_at: datetime
    watermark_at: datetime
    max_observation_lag_seconds: int
    policy_hash: ContentHash
    complete: Literal[True]


class AggregationFailure(StrictModel):
    meta: ArtifactMeta
    market: Market
    symbol: Symbol
    interval_start: datetime
    interval_end: datetime
    watermark_at: datetime
    reason: Literal["missing", "stale", "session_state"]
    present_refs: tuple[ArtifactRef, ...]
    missing_starts: tuple[datetime, ...]
    downstream_eligible: Literal[False]


class SupersedeEvent(StrictModel):
    meta: ArtifactMeta
    prior: ArtifactRef
    replacement: ArtifactRef
    reason: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class V10ContractError(Exception):
    code: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"
