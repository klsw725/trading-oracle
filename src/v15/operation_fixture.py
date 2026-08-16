from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Final, Literal
from zoneinfo import ZoneInfo

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .approvals import (
    Approval,
    DataExceptionEvidence,
    seal_data_exception,
    verify_manual_approval_artifact,
)
from .contract import StrictModel, V15Failure, V15FailureCode
from .fixtures import read_pinned_fixture
from .retirement import RetirementRegistry


class OfficialCalendar(StrictModel):
    schema_version: Literal["v15.official_calendar.1"]
    market: Literal["KR", "US"]
    calendar_id: str
    source: str
    version: str
    timezone: str
    holidays: Annotated[tuple[date, ...], Field(strict=False)]
    early_closes: Annotated[tuple[date, ...], Field(strict=False)]
    calendar_hash: str


class MarketTimeline(StrictModel):
    market: Literal["KR", "US"]
    calendar: OfficialCalendar
    calendar_fixture_path: str
    calendar_fixture_hash: str
    qualification_start: date
    qualification_session_count: Literal[20]
    comparison_session_count: int
    no_trade_offsets: Annotated[tuple[int, ...], Field(strict=False)]
    loss_kill_offset: int


class ReturnPolicy(StrictModel):
    orb: Decimal
    router_winner_period: Decimal
    router_rollback_period: Decimal
    router_gross: Decimal
    router_execution_cost: Decimal


class OperationSourceFixture(StrictModel):
    schema_version: Literal["v15.operation_source.4"]
    destination: Literal["paper"]
    v14_artifact: str
    markets: Annotated[tuple[MarketTimeline, MarketTimeline], Field(strict=False)]
    initial_nav: Decimal
    completed_trades_per_trade_day: int
    returns: ReturnPolicy
    policy_version: str
    data_exceptions: Annotated[tuple[DataExceptionEvidence, ...],
        Field(strict=False)]
    prior_retirement_registry: RetirementRegistry
    manual_approvals: Annotated[tuple[Approval, ...], Field(strict=False)]


class MarketSchedule(StrictModel):
    market: Literal["KR", "US"]
    calendar_hash: str
    gate_available_at: datetime
    qualification_sessions: Annotated[tuple[date, ...], Field(strict=False)]
    comparison_sessions: Annotated[tuple[date, ...], Field(strict=False)]
    challenger_session: date
    router_primary_session: date | None
    performance_sessions: Annotated[tuple[date, ...], Field(strict=False)]
    no_trade_sessions: Annotated[tuple[date, ...], Field(strict=False)]
    loss_kill_session: date


_PINNED_CALENDARS: Final = {
    "KR": ("docs/specs/v15/fixtures/calendar-kr.json",
        "sha256:7f6efae985e18df84dda58ad20302c3c6f7ab2c6333e861819fbfd99a09dc307"),
    "US": ("docs/specs/v15/fixtures/calendar-us.json",
        "sha256:b453946b0eddc7bea8ff88400b0765acfa5631ed9693719c5784272a6897f926"),
}


def load_operation_source(path: Path) -> OperationSourceFixture:
    return OperationSourceFixture.model_validate_json(path.read_bytes())


def official_sessions(
    calendar: OfficialCalendar, start: date, count: int
) -> tuple[date, ...]:
    sessions: list[date] = []
    current = start
    holidays = set(calendar.holidays)
    while len(sessions) < count:
        if current.weekday() < 5 and current not in holidays:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def build_schedule(
    timeline: MarketTimeline, gate_available_at: datetime
) -> MarketSchedule:
    verify_calendar(timeline)
    local_gate_date = gate_available_at.astimezone(
        ZoneInfo(timeline.calendar.timezone)).date()
    first_eligible = official_sessions(timeline.calendar,
        local_gate_date + timedelta(days=1), 1)[0]
    if timeline.qualification_start != first_eligible:
        raise V15Failure(V15FailureCode.COMPARISON_INVALID,
            f"first_post_gate_session:{timeline.market}")
    qualification = official_sessions(timeline.calendar,
        timeline.qualification_start, timeline.qualification_session_count)
    comparison = official_sessions(timeline.calendar,
        qualification[-1] + timedelta(days=1),
        timeline.comparison_session_count)
    if len(comparison) < 80:
        raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT, timeline.market)
    try:
        no_trade = tuple(comparison[index] for index in timeline.no_trade_offsets)
        loss_kill = comparison[timeline.loss_kill_offset]
    except IndexError as error:
        raise V15Failure(V15FailureCode.COMPARISON_INVALID,
            f"scenario_offset:{timeline.market}") from error
    return MarketSchedule(market=timeline.market,
        calendar_hash=timeline.calendar.calendar_hash,
        gate_available_at=gate_available_at,
        qualification_sessions=qualification, comparison_sessions=comparison,
        challenger_session=comparison[0], router_primary_session=None,
        performance_sessions=(), no_trade_sessions=no_trade,
        loss_kill_session=loss_kill)


def verify_calendar(timeline: MarketTimeline) -> None:
    calendar = timeline.calendar
    pinned_path, pinned_hash = _PINNED_CALENDARS[calendar.market]
    expected_parts = ("docs", "specs", "v15", "fixtures",
        "calendar-kr.json" if calendar.market == "KR" else "calendar-us.json")
    payload = read_pinned_fixture(timeline.calendar_fixture_path, expected_parts)
    payload_hash = "sha256:" + sha256(payload).hexdigest()
    authoritative = OfficialCalendar.model_validate_json(payload)
    body = calendar.model_copy(update={"calendar_hash": ""})
    if timeline.calendar_fixture_path != pinned_path \
            or timeline.calendar_fixture_hash != pinned_hash \
            or payload_hash != pinned_hash or authoritative != calendar \
            or calendar.market == "KR" and calendar.timezone != "Asia/Seoul" \
            or calendar.market == "US" and calendar.timezone != "America/New_York" \
            or calendar.calendar_hash != canonical_hash(model_json(body)):
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE,
            f"calendar:{calendar.market}")


def verify_source(source: OperationSourceFixture) -> None:
    if tuple(item.market for item in source.markets) != ("KR", "US") \
            or any(item.market != item.calendar.market for item in source.markets) \
            or source.completed_trades_per_trade_day <= 0 \
            or any(seal_data_exception(item) != item
                for item in source.data_exceptions) \
            or any(item.source_hash != next(market.calendar.calendar_hash
                for market in source.markets if market.market == item.market)
                for item in source.data_exceptions) \
            or len({item.approval_hash for item in source.manual_approvals}) \
                != len(source.manual_approvals):
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "market_timelines")
    for approval in source.manual_approvals:
        verify_manual_approval_artifact(approval)
