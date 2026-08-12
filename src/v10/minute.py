from __future__ import annotations

from datetime import timedelta

from pydantic import ValidationError

from src.v4.models import JsonValue
from .calendar import session_for
from .canonical import model_json, seal_meta
from .models import (
    MarketCalendarSnapshot,
    MinuteBar,
    SessionState,
    SourceObservation,
    V10ContractError,
)


def build_minute(
    value: JsonValue,
    calendar: MarketCalendarSnapshot,
    source: SourceObservation,
) -> MinuteBar:
    try:
        unsealed = MinuteBar.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_MINUTE_BAR_MALFORMED", str(error)) from error
    if unsealed.market is not calendar.market or unsealed.source_ref.artifact_id != source.meta.artifact_id:
        raise V10ContractError("V10_SOURCE_PROVENANCE_MISMATCH", unsealed.symbol)
    if unsealed.interval_end - unsealed.interval_start != timedelta(minutes=1):
        raise V10ContractError("V10_MINUTE_BAR_MALFORMED", "interval duration")
    if (
        unsealed.volume < 0
        or unsealed.revision < 0
        or unsealed.low > unsealed.high
        or not unsealed.low <= unsealed.open <= unsealed.high
        or not unsealed.low <= unsealed.close <= unsealed.high
    ):
        raise V10ContractError("V10_MINUTE_BAR_MALFORMED", unsealed.symbol)
    session = session_for(calendar, unsealed.session_date)
    if session is None or not session.open:
        raise V10ContractError("V10_CALENDAR_MISMATCH", str(unsealed.session_date))
    matching = tuple(
        interval
        for interval in session.intervals
        if interval.state is unsealed.session_state
        and interval.start <= unsealed.interval_start
        and unsealed.interval_end <= interval.end
    )
    if not matching or (
        unsealed.session_state is SessionState.REGULAR
        and unsealed.calendar_ref.artifact_id != calendar.meta.artifact_id
    ):
        raise V10ContractError("V10_CALENDAR_MISMATCH", unsealed.interval_start.isoformat())
    body = model_json(unsealed, exclude={"meta"})
    return unsealed.model_copy(update={"meta": seal_meta("minute_bar", body)})


def build_minutes(
    values: tuple[JsonValue, ...],
    calendar: MarketCalendarSnapshot,
    source: SourceObservation,
) -> tuple[MinuteBar, ...]:
    bars = tuple(build_minute(value, calendar, source) for value in values)
    keys = tuple((bar.symbol, bar.interval_start, bar.revision) for bar in bars)
    if len(set(keys)) != len(keys) or tuple(bar.interval_start for bar in bars) != tuple(
        sorted(bar.interval_start for bar in bars)
    ):
        raise V10ContractError("V10_MINUTE_BAR_MALFORMED", "duplicate or reversed timestamp")
    return bars
