from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from math import isfinite
from typing import Protocol, override

from .models import Action, JsonValue


class RegularSessionView(Protocol):
    @property
    def session_date(self) -> date: ...

    @property
    def regular_close_at(self) -> datetime: ...


class MarketContextView(Protocol):
    @property
    def timezone(self) -> tzinfo: ...

    @property
    def benchmark_id(self) -> str: ...

    @property
    def ordered_regular_sessions(self) -> tuple[RegularSessionView, ...]: ...


@dataclass(frozen=True, slots=True)
class ReturnCloseEvidence:
    entry_total_return_close: float
    exit_total_return_close: float
    source_id: str
    as_of: datetime
    entry_session: date
    target_exit_session: date
    actual_exit_session: date | None = None


@dataclass(frozen=True, slots=True)
class CorporateActionProvenance:
    source_id: str
    checked_through: date
    return_basis: str


@dataclass(frozen=True, slots=True)
class CostModel:
    version: str
    total_rate: float


@dataclass(frozen=True, slots=True)
class SessionProgress:
    entry_session: date
    closed_sessions_after_entry: int


@dataclass(frozen=True, slots=True)
class MeasurementRequest:
    context: MarketContextView
    emitted_at: datetime
    ticker: str
    action: Action
    horizon: int
    instrument_prices: ReturnCloseEvidence | None
    benchmark_prices: ReturnCloseEvidence | None
    corporate_action_provenance: CorporateActionProvenance | None
    cost_model: CostModel | None
    session_progress: SessionProgress | None = None


@dataclass(frozen=True, slots=True)
class MeasurementParseError(Exception):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"measurement input {self.field}: {self.reason}"


def _text(raw: Mapping[str, JsonValue], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        raise MeasurementParseError(field, f"expected string, received {value!r}")
    return value


def _record(raw: Mapping[str, JsonValue], field: str) -> Mapping[str, JsonValue]:
    value = raw.get(field)
    if not isinstance(value, dict):
        raise MeasurementParseError(field, f"expected record, received {value!r}")
    return value


def _number(raw: Mapping[str, JsonValue], field: str) -> float:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
        raise MeasurementParseError(field, f"expected finite number, received {value!r}")
    return float(value)


def _timestamp(raw: Mapping[str, JsonValue], field: str) -> datetime:
    try:
        value = datetime.fromisoformat(_text(raw, field))
    except ValueError as error:
        raise MeasurementParseError(field, "expected ISO 8601 timestamp") from error
    if value.utcoffset() is None:
        raise MeasurementParseError(field, "timestamp must include a UTC offset")
    return value


def _optional_date(raw: Mapping[str, JsonValue], field: str) -> date | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MeasurementParseError(field, f"expected ISO date, received {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise MeasurementParseError(field, "expected ISO date") from error


def _required_date(raw: Mapping[str, JsonValue], field: str) -> date:
    value = _optional_date(raw, field)
    if value is None:
        raise MeasurementParseError(field, "required ISO date is missing")
    return value


def _optional_evidence(
    raw: Mapping[str, JsonValue], field: str
) -> ReturnCloseEvidence | None:
    if raw.get(field) is None:
        return None
    prices = _record(raw, field)
    entry = _number(prices, "entry_total_return_close")
    exit_ = _number(prices, "exit_total_return_close")
    if entry <= 0 or exit_ < 0:
        raise MeasurementParseError(field, "invalid total-return close")
    return ReturnCloseEvidence(
        entry_total_return_close=entry,
        exit_total_return_close=exit_,
        source_id=_text(prices, "source_id"),
        as_of=_timestamp(prices, "as_of"),
        entry_session=_required_date(prices, "entry_session"),
        target_exit_session=_required_date(prices, "target_exit_session"),
        actual_exit_session=_optional_date(prices, "actual_exit_session"),
    )


def _optional_progress(raw: Mapping[str, JsonValue]) -> SessionProgress | None:
    count = raw.get("known_closed_sessions_after_entry")
    if count is None:
        return None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise MeasurementParseError(
            "known_closed_sessions_after_entry", "expected non-negative integer"
        )
    return SessionProgress(_required_date(raw, "entry_session"), count)


def parse_measurement_request(
    raw: Mapping[str, JsonValue], context: MarketContextView
) -> MeasurementRequest:
    horizon = raw.get("horizon")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
        raise MeasurementParseError("horizon", "expected positive integer")
    try:
        action = Action(_text(raw, "action"))
    except ValueError as error:
        raise MeasurementParseError("action", "unsupported action") from error

    corporate: CorporateActionProvenance | None = None
    if raw.get("corporate_action_provenance") is not None:
        source = _record(raw, "corporate_action_provenance")
        try:
            checked_through = date.fromisoformat(_text(source, "checked_through"))
        except ValueError as error:
            raise MeasurementParseError("checked_through", "expected ISO date") from error
        corporate = CorporateActionProvenance(
            _text(source, "source_id"),
            checked_through,
            _text(source, "return_basis"),
        )

    cost_model: CostModel | None = None
    if raw.get("cost_model") is not None:
        cost = _record(raw, "cost_model")
        rate = _number(cost, "total_rate")
        if rate < 0:
            raise MeasurementParseError("total_rate", "cost rate cannot be negative")
        cost_model = CostModel(_text(cost, "version"), rate)

    return MeasurementRequest(
        context=context,
        emitted_at=_timestamp(raw, "emitted_at"),
        ticker=_text(raw, "ticker"),
        action=action,
        horizon=horizon,
        instrument_prices=_optional_evidence(raw, "instrument_prices"),
        benchmark_prices=_optional_evidence(raw, "benchmark_prices"),
        corporate_action_provenance=corporate,
        cost_model=cost_model,
        session_progress=_optional_progress(raw),
    )
