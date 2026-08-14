from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from .features import atr14, clv, rvol, vwap
from .artifacts import GateComputation
from .models import Bar, Side, StrategyInput, V12ContractError


def complete_bars(source: StrategyInput) -> tuple[Bar, ...]:
    bars = (*source.prior_bars, *source.bars)
    if not source.bars or any(not item.complete for item in bars):
        raise V12ContractError("V12_INCOMPLETE_FEATURE", source.symbol)
    current = source.bars[-1]
    if any(left.end != right.start for left, right in zip(source.bars, source.bars[1:], strict=False)):
        raise V12ContractError("V12_BAR_CONTINUITY", source.symbol)
    if any(item.session_date != source.session_date for item in source.bars):
        raise V12ContractError("V12_SESSION_DATE", source.symbol)
    if source.watermark_at < current.end or (source.watermark_at - current.end).total_seconds() < 10:
        raise V12ContractError("V12_WATERMARK_EARLY", current.end.isoformat())
    if current.end >= source.regular_close - timedelta(minutes=20):
        raise V12ContractError("V12_ENTRY_CUTOFF", current.end.isoformat())
    return bars


def base_features(source: StrategyInput) -> tuple[tuple[Bar, ...], Decimal, Decimal, Decimal, Decimal]:
    bars = complete_bars(source)
    session = source.bars
    return bars, atr14(bars), rvol(bars), vwap(session), clv(session[-1])


def prior_range(bars: tuple[Bar, ...], count: int) -> tuple[Decimal, Decimal]:
    if len(bars) <= count:
        raise V12ContractError("V12_FEATURE_MISSING", f"range_{count}")
    prior = bars[-count - 1:-1]
    return max(item.high for item in prior), min(item.low for item in prior)


def session_range(source: StrategyInput, count: int) -> tuple[Decimal, Decimal]:
    if len(source.bars) <= count:
        raise V12ContractError("V12_FEATURE_MISSING", f"session_range_{count}")
    prior = source.bars[-count - 1:-1]
    return max(item.high for item in prior), min(item.low for item in prior)


def direction(side: Side) -> Decimal:
    return Decimal(1) if side is Side.LONG else Decimal(-1)


def breakout_result(passed: bool, distance: Decimal, volume: Decimal,
                    extra: tuple[str, Decimal] | None = None) -> GateComputation:
    components = {"distance": distance, "rvol": volume}
    if extra is not None:
        components[extra[0]] = extra[1]
    return GateComputation(passed=passed, components=components,
        features={"distance": distance, "rvol": volume})
