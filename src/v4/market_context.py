from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique
from typing import NewType, assert_never, override
from zoneinfo import ZoneInfo

from src.v4.models import JsonValue, Market, QualityState

BenchmarkId = NewType("BenchmarkId", str)
CalendarId = NewType("CalendarId", str)
Currency = NewType("Currency", str)


@unique
class Exchange(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    KOSDAQ_GLOBAL = "KOSDAQ GLOBAL"
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"


@dataclass(frozen=True, slots=True)
class RegularSession:
    session_date: date
    regular_close_at: datetime


@dataclass(frozen=True, slots=True)
class MarketContext:
    market: Market
    exchange: Exchange
    calendar_id: CalendarId
    calendar_version: str
    timezone: ZoneInfo
    quote_currency: Currency
    base_reporting_currency: Currency
    benchmark_id: BenchmarkId
    decision_regime: str
    decision_regime_source: BenchmarkId
    ordered_regular_sessions: tuple[RegularSession, ...]
    calendar_source_id: str
    calendar_as_of: datetime
    calendar_content_hash: str


@dataclass(frozen=True, slots=True)
class MarketContextParseError(Exception):
    field: str
    reason: str
    state: QualityState

    @override
    def __str__(self) -> str:
        return f"market context {self.state}: {self.field}: {self.reason}"


def _required(raw: Mapping[str, JsonValue], field: str) -> JsonValue:
    try:
        return raw[field]
    except KeyError as error:
        raise MarketContextParseError(
            field=field,
            reason="required field is missing",
            state=QualityState.UNKNOWN,
        ) from error


def _text(raw: Mapping[str, JsonValue], field: str) -> str:
    value = _required(raw, field)
    if not isinstance(value, str):
        raise MarketContextParseError(
            field=field,
            reason=f"expected string, received {type(value).__name__}",
            state=QualityState.UNKNOWN,
        )
    return value


def _record(raw: Mapping[str, JsonValue], field: str) -> Mapping[str, JsonValue]:
    value = _required(raw, field)
    if not isinstance(value, dict):
        raise MarketContextParseError(
            field=field,
            reason=f"expected record, received {type(value).__name__}",
            state=QualityState.UNKNOWN,
        )
    return value


def _records(
    raw: Mapping[str, JsonValue], field: str
) -> Sequence[Mapping[str, JsonValue]]:
    values = _required(raw, field)
    if not isinstance(values, list):
        raise MarketContextParseError(
            field=field,
            reason=f"expected array, received {type(values).__name__}",
            state=QualityState.UNKNOWN,
        )
    records: list[Mapping[str, JsonValue]] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise MarketContextParseError(
                field=f"{field}[{index}]",
                reason=f"expected record, received {type(value).__name__}",
                state=QualityState.UNKNOWN,
            )
        records.append(value)
    return records


def _timestamp(raw: Mapping[str, JsonValue], field: str) -> datetime:
    value = _text(raw, field)
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise MarketContextParseError(
            field=field,
            reason="expected ISO 8601 timestamp",
            state=QualityState.UNKNOWN,
        ) from error
    if timestamp.utcoffset() is None:
        raise MarketContextParseError(
            field=field,
            reason="timestamp must include a UTC offset",
            state=QualityState.UNKNOWN,
        )
    return timestamp


def _exchange_contract(
    exchange: Exchange,
) -> tuple[Market, CalendarId, str, Currency, BenchmarkId]:
    match exchange:
        case Exchange.KOSPI:
            return (
                Market.KR,
                CalendarId("KRX"),
                "Asia/Seoul",
                Currency("KRW"),
                BenchmarkId("KS11"),
            )
        case Exchange.KOSDAQ | Exchange.KOSDAQ_GLOBAL:
            return (
                Market.KR,
                CalendarId("KRX"),
                "Asia/Seoul",
                Currency("KRW"),
                BenchmarkId("KQ11"),
            )
        case Exchange.NASDAQ:
            return (
                Market.US,
                CalendarId("NASDAQ"),
                "America/New_York",
                Currency("USD"),
                BenchmarkId("IXIC"),
            )
        case remaining:
            if remaining is Exchange.NYSE:
                return (
                    Market.US,
                    CalendarId("NYSE"),
                    "America/New_York",
                    Currency("USD"),
                    BenchmarkId("US500"),
                )
            assert_never(remaining)


def parse_market_context(raw: Mapping[str, JsonValue]) -> MarketContext:
    try:
        market = Market(_text(raw, "market"))
        exchange = Exchange(_text(raw, "exchange"))
    except ValueError as error:
        raise MarketContextParseError(
            field="market/exchange",
            reason="unsupported market or exchange",
            state=QualityState.UNKNOWN,
        ) from error

    expected_market, calendar_id, timezone_name, quote_currency, benchmark_id = (
        _exchange_contract(exchange)
    )
    declared = (
        market,
        _text(raw, "calendar_id"),
        _text(raw, "timezone"),
        _text(raw, "quote_currency"),
        _text(raw, "base_reporting_currency"),
        _text(raw, "benchmark_id"),
        _text(raw, "decision_regime_source"),
    )
    expected = (
        expected_market,
        calendar_id,
        timezone_name,
        quote_currency,
        Currency("KRW"),
        benchmark_id,
        benchmark_id,
    )
    if declared != expected:
        raise MarketContextParseError(
            field="exchange_contract",
            reason=f"declared={declared!r}, expected={expected!r}",
            state=QualityState.BLOCKED,
        )

    timezone = ZoneInfo(timezone_name)
    sessions: list[RegularSession] = []
    for index, session_raw in enumerate(_records(raw, "ordered_regular_sessions")):
        try:
            session_date = date.fromisoformat(_text(session_raw, "session_date"))
        except ValueError as error:
            raise MarketContextParseError(
                field=f"ordered_regular_sessions[{index}].session_date",
                reason="expected ISO date",
                state=QualityState.UNKNOWN,
            ) from error
        close_at = _timestamp(session_raw, "regular_close_at")
        if (
            close_at.date() != session_date
            or close_at.utcoffset() != close_at.astimezone(timezone).utcoffset()
        ):
            raise MarketContextParseError(
                field=f"ordered_regular_sessions[{index}].regular_close_at",
                reason="close timestamp is outside the declared session timezone/date",
                state=QualityState.BLOCKED,
            )
        sessions.append(RegularSession(session_date, close_at))
    if not sessions or any(
        current.session_date >= following.session_date
        for current, following in zip(sessions, sessions[1:], strict=False)
    ):
        raise MarketContextParseError(
            field="ordered_regular_sessions",
            reason="sessions must be non-empty and strictly ordered",
            state=QualityState.UNKNOWN,
        )

    provenance = _record(raw, "calendar_provenance")
    return MarketContext(
        market=market,
        exchange=exchange,
        calendar_id=calendar_id,
        calendar_version=_text(raw, "calendar_version"),
        timezone=timezone,
        quote_currency=quote_currency,
        base_reporting_currency=Currency("KRW"),
        benchmark_id=benchmark_id,
        decision_regime=_text(raw, "decision_regime"),
        decision_regime_source=benchmark_id,
        ordered_regular_sessions=tuple(sessions),
        calendar_source_id=_text(provenance, "source_id"),
        calendar_as_of=_timestamp(provenance, "as_of"),
        calendar_content_hash=_text(provenance, "content_hash"),
    )
