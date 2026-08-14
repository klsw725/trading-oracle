from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.v4.models import JsonValue
from src.v11.canonical import canonical_hash

from .artifacts import FeatureSnapshot
from .models import Bar, HistoricalValue, StrategyInput, V12ContractError


def true_range(current: Bar, previous: Bar) -> Decimal:
    return max(current.high - current.low, abs(current.high - previous.close),
               abs(current.low - previous.close))


def atr14(bars: tuple[Bar, ...]) -> Decimal:
    if len(bars) < 15:
        raise V12ContractError("V12_FEATURE_MISSING", "ATR14")
    ranges = tuple(true_range(bars[index], bars[index - 1]) for index in range(len(bars) - 14, len(bars)))
    value = sum(ranges, Decimal(0)) / Decimal(14)
    if value <= 0:
        raise V12ContractError("V12_FEATURE_MISSING", "ATR14_ZERO")
    return value


def rvol(bars: tuple[Bar, ...], lookback: int = 12) -> Decimal:
    if len(bars) <= lookback:
        raise V12ContractError("V12_FEATURE_MISSING", "RVOL")
    ordered = sorted(item.volume for item in bars[-lookback - 1:-1])
    middle = lookback // 2
    median = Decimal(ordered[middle - 1] + ordered[middle]) / Decimal(2)
    if median == 0:
        raise V12ContractError("V12_FEATURE_MISSING", "RVOL_ZERO")
    return Decimal(bars[-1].volume) / median


def vwap(bars: tuple[Bar, ...]) -> Decimal:
    volume = sum(item.volume for item in bars)
    if volume == 0:
        raise V12ContractError("V12_FEATURE_MISSING", "VWAP")
    weighted = sum(((item.high + item.low + item.close) / Decimal(3)) * item.volume for item in bars)
    return weighted / Decimal(volume)


def clv(bar: Bar) -> Decimal:
    width = bar.high - bar.low
    return Decimal("0.5") if width == 0 else (bar.close - bar.low) / width


def p60(value: Decimal, history: tuple[HistoricalValue, ...], cutoff_date: date,
        minute_slot: int) -> Decimal:
    eligible = tuple(item for item in history
                     if item.session_date < cutoff_date and item.minute_slot == minute_slot)
    ordered = tuple(sorted(eligible, key=lambda item: item.session_date)[-60:])
    if len({item.session_date for item in ordered}) != len(ordered):
        raise V12ContractError("V12_P60_SESSION_DUPLICATE", str(minute_slot))
    prior = tuple(item.value for item in ordered)
    if len(prior) < 20:
        raise V12ContractError("V12_P60_HISTORY", str(len(prior)))
    below = sum(item < value for item in prior)
    equal = sum(item == value for item in prior)
    if equal == len(prior):
        return Decimal("0.5")
    midrank = Decimal(below + 1) + Decimal(equal - 1) / Decimal(2)
    return (midrank - 1) / Decimal(len(prior) - 1)


def percentile(source: StrategyInput, key: str, value: Decimal) -> Decimal:
    history = source.historical.get(key)
    if history is None:
        raise V12ContractError("V12_FEATURE_MISSING", key)
    minute_slot = int((source.bars[-1].end - source.regular_open).total_seconds() / 60)
    result = p60(value, history, source.session_date, minute_slot)
    return min(Decimal(1), max(Decimal(0), result))


def snapshot(source: StrategyInput, values: dict[str, Decimal]) -> FeatureSnapshot:
    cutoff = source.bars[-1].end
    body: dict[str, JsonValue] = {"market": source.market.value, "symbol": source.symbol,
        "session_date": source.session_date.isoformat(), "cutoff": cutoff.isoformat(),
        "regular_open": source.regular_open.isoformat(),
        "regular_close": source.regular_close.isoformat(),
        "watermark_at": source.watermark_at.isoformat(),
        "adjustment_factor": str(source.adjustment_factor),
        "previous_adjusted_close": str(source.previous_adjusted_close),
        "benchmark_id": source.benchmark_id,
        "bars": [item.model_dump(mode="json") for item in (*source.prior_bars, *source.bars)],
        "benchmark_bars": [item.model_dump(mode="json") for item in source.benchmark_bars],
        "historical": {key: [item.model_dump(mode="json") for item in history]
                       for key, history in sorted(source.historical.items())},
        "eligibility_refs": [item.model_dump(mode="json") for item in source.eligibility_refs],
        "execution_snapshot": source.execution_snapshot.model_dump(mode="json"),
        "borrow": None if source.borrow is None else source.borrow.model_dump(mode="json"),
        "values": {key: str(value) for key, value in sorted(values.items())}}
    return FeatureSnapshot(cutoff=cutoff, values=values, input_hash=canonical_hash(body))
