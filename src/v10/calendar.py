from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from src.v4.models import JsonValue
from src.v10.canonical import model_json, seal_meta
from src.v10.models import (
    CalendarSession,
    MarketCalendarSnapshot,
    SessionState,
    V10ContractError,
)


def build_calendar(value: JsonValue) -> MarketCalendarSnapshot:
    try:
        unsealed = MarketCalendarSnapshot.model_validate(value)
    except ValidationError as error:
        raise V10ContractError("V10_CALENDAR_MISMATCH", str(error)) from error
    try:
        timezone = ZoneInfo(unsealed.timezone)
    except ZoneInfoNotFoundError as error:
        raise V10ContractError("V10_CALENDAR_MISMATCH", unsealed.timezone) from error
    for session in unsealed.sessions:
        _verify_session(session, timezone)
    body = model_json(unsealed, exclude={"meta"})
    return unsealed.model_copy(update={"meta": seal_meta("market_calendar_snapshot", body)})


def _verify_session(session: CalendarSession, timezone: ZoneInfo) -> None:
    if session.open != (session.regular_open is not None and session.regular_end is not None):
        raise V10ContractError("V10_CALENDAR_MISMATCH", str(session.session_date))
    if not session.open:
        if session.intervals:
            raise V10ContractError("V10_CALENDAR_MISMATCH", "closed session intervals")
        return
    assert session.regular_open is not None and session.regular_end is not None
    if (
        session.regular_open >= session.regular_end
        or session.regular_open.astimezone(timezone).date() != session.session_date
        or session.regular_end.astimezone(timezone).date() != session.session_date
    ):
        raise V10ContractError("V10_CALENDAR_MISMATCH", str(session.session_date))
    regular = tuple(item for item in session.intervals if item.state is SessionState.REGULAR)
    if not regular or regular[0].start != session.regular_open or regular[-1].end != session.regular_end:
        raise V10ContractError("V10_CALENDAR_MISMATCH", "regular interval boundary")
    previous: datetime | None = None
    for interval in session.intervals:
        if interval.start >= interval.end or (previous is not None and interval.start < previous):
            raise V10ContractError("V10_CALENDAR_MISMATCH", "interval order")
        previous = interval.end


def session_for(
    calendar: MarketCalendarSnapshot, session_date: date
) -> CalendarSession | None:
    return next(
        (session for session in calendar.sessions if session.session_date == session_date),
        None,
    )
