from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from .errors import FailureCode, V16Failure
from .models import CalendarArtifact, Market


_EXPECTED = {Market.KR: ("Asia/Seoul", "KRW"),
             Market.US: ("America/New_York", "USD")}


@dataclass(frozen=True, slots=True)
class SessionWindow:
    opened_at: datetime
    closed_at: datetime


def _local_time(session_date: str, local_time: str, timezone: ZoneInfo) -> datetime:
    try:
        naive = datetime.fromisoformat(f"{session_date}T{local_time}")
    except ValueError as error:
        raise V16Failure(FailureCode.CALENDAR_INVALID, "invalid session time") from error
    first = naive.replace(tzinfo=timezone, fold=0)
    second = naive.replace(tzinfo=timezone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise V16Failure(FailureCode.CALENDAR_INVALID, "ambiguous session time")
    if first.astimezone(ZoneInfo("UTC")).astimezone(timezone).replace(tzinfo=None) != naive:
        raise V16Failure(FailureCode.CALENDAR_INVALID, "nonexistent session time")
    return first


def load_calendar(path: Path) -> CalendarArtifact:
    try:
        artifact = CalendarArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise V16Failure(FailureCode.CALENDAR_INVALID, "calendar schema rejected") from error
    expected_timezone = _EXPECTED[artifact.market][0]
    seen: set[str] = set()
    for record in artifact.records:
        try:
            _ = date.fromisoformat(record.session_date)
        except ValueError as error:
            raise V16Failure(FailureCode.CALENDAR_INVALID, "invalid session date") from error
        if record.market is not artifact.market or record.timezone != expected_timezone or \
                record.session_date in seen:
            raise V16Failure(FailureCode.CALENDAR_INVALID, "calendar identity or duplicate")
        seen.add(record.session_date)
        if record.status == "CLOSED":
            if record.open is not None or record.close is not None or record.early_close:
                raise V16Failure(FailureCode.CALENDAR_INVALID, "invalid closed session")
            continue
        if record.open is None or record.close is None or \
                (record.status == "EARLY_CLOSE") is not record.early_close:
            raise V16Failure(FailureCode.CALENDAR_INVALID, "invalid open session")
        try:
            timezone = ZoneInfo(record.timezone)
            opened = _local_time(record.session_date, record.open, timezone)
            closed = _local_time(record.session_date, record.close, timezone)
        except ZoneInfoNotFoundError as error:
            raise V16Failure(FailureCode.CALENDAR_INVALID, "invalid session time") from error
        if opened.astimezone(ZoneInfo("UTC")) >= closed.astimezone(ZoneInfo("UTC")):
            raise V16Failure(FailureCode.CALENDAR_INVALID, "open must precede close")
    return artifact


def expected_currency(market: Market) -> str:
    return _EXPECTED[market][1]


def session_window(artifact: CalendarArtifact, session_date: str) -> SessionWindow | None:
    record = next((item for item in artifact.records if item.session_date == session_date), None)
    if record is None or record.status == "CLOSED":
        return None
    if record.open is None or record.close is None:
        raise V16Failure(FailureCode.CALENDAR_INVALID, "open session has no bounds")
    timezone = ZoneInfo(record.timezone)
    opened = _local_time(record.session_date, record.open, timezone)
    closed = _local_time(record.session_date, record.close, timezone)
    return SessionWindow(opened.astimezone(ZoneInfo("UTC")), closed.astimezone(ZoneInfo("UTC")))
