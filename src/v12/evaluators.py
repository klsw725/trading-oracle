from __future__ import annotations

from decimal import Decimal

from .evaluator_common import base_features, breakout_result, direction, prior_range, session_range
from .features import atr14, percentile, true_range, vwap
from .artifacts import GateComputation
from .models import Bar, ParameterSet, Side, StrategyInput, StrategySpec, V12ContractError


def evaluate_gate(spec: StrategySpec, parameters: ParameterSet,
                  source: StrategyInput) -> GateComputation:
    match spec.evaluator:
        case "orb15":
            return _orb(source, spec.side, parameters, 3, 15, 60)
        case "orb30":
            return _orb(source, spec.side, parameters, 6, 30, 90)
        case "gap":
            return _gap(source, spec.side, parameters)
        case "session":
            return _session(source, spec.side, parameters)
        case "vwap":
            return _vwap_signal(source, spec.side, parameters)
        case "ma":
            return _ma(source, parameters)
        case "rs":
            return _relative_strength(source, parameters)
        case "volume":
            return _volume(source, spec.side, parameters)
        case "expansion":
            return _expansion(source, parameters)
        case "compression":
            return _compression(source, parameters)
        case _:
            raise V12ContractError("V12_EVALUATOR_UNKNOWN", spec.evaluator)


def _orb(source: StrategyInput, side: Side, parameters: ParameterSet,
         range_count: int, start_minute: int, end_minute: int) -> GateComputation:
    _, atr, volume, _, _ = base_features(source)
    range_high = max(item.high for item in source.bars[:range_count])
    range_low = min(item.low for item in source.bars[:range_count])
    elapsed = int((source.bars[-1].end - source.regular_open).total_seconds() / 60)
    signed = direction(side)
    boundary = range_high if side is Side.LONG else range_low
    distance = signed * (source.bars[-1].close - boundary) / atr
    passed = start_minute < elapsed <= end_minute and distance > parameters.values["b"]
    passed = passed and volume >= parameters.values["r"]
    return breakout_result(passed, distance, volume)


def _gap(source: StrategyInput, side: Side, parameters: ParameterSet) -> GateComputation:
    _, atr, volume, current_vwap, _ = base_features(source)
    count = int(parameters.values["w"] / Decimal(5))
    if len(source.bars) <= count:
        raise V12ContractError("V12_FEATURE_MISSING", "gap_range")
    opening = source.bars[:count]
    boundary = max(item.high for item in opening) if side is Side.LONG else min(item.low for item in opening)
    signed = direction(side)
    gap = source.bars[0].open / source.previous_adjusted_close - 1
    distance = signed * (source.bars[-1].close - boundary) / atr
    directional_gap = signed * gap
    price_vwap = signed * (source.bars[-1].close - current_vwap) > 0
    passed = directional_gap >= parameters.values["g"] and distance > 0 and price_vwap
    return GateComputation(passed=passed, components={"gap": directional_gap,
        "distance": distance, "rvol": volume}, features={"gap": gap,
        "distance": distance, "rvol": volume, "vwap": current_vwap})


def _session(source: StrategyInput, side: Side, parameters: ParameterSet) -> GateComputation:
    _, atr, volume, _, _ = base_features(source)
    count = int(parameters.values["n"])
    high, low = session_range(source, count)
    signed = direction(side)
    boundary = high if side is Side.LONG else low
    distance = signed * (source.bars[-1].close - boundary) / atr
    return breakout_result(distance > parameters.values["b"], distance, volume)


def _vwap_signal(source: StrategyInput, side: Side, parameters: ParameterSet) -> GateComputation:
    _, atr, volume, current_vwap, current_clv = base_features(source)
    count = int(parameters.values["k"])
    if len(source.bars) <= count:
        raise V12ContractError("V12_FEATURE_MISSING", "vwap_history")
    prior = source.bars[-count - 1:-1]
    prior_vwaps = tuple(vwap(source.bars[:len(source.bars) - count + index]) for index in range(count))
    signed = direction(side)
    distance = signed * (source.bars[-1].close - current_vwap) / atr
    if side is Side.LONG:
        setup = all(bar.close <= value for bar, value in zip(prior, prior_vwaps, strict=True))
        confirmation = source.bars[-2].close <= prior_vwaps[-1]
        close_component = current_clv
    else:
        setup = any(bar.high >= value for bar, value in zip(prior, prior_vwaps, strict=True))
        confirmation = source.bars[-2].close >= prior_vwaps[-1]
        close_component = 1 - current_clv
    return GateComputation(passed=setup and confirmation and distance > parameters.values["b"],
        components={"distance": distance, "rvol": volume, "clv": close_component},
        features={"distance": distance, "rvol": volume, "clv": current_clv})


def _sma(bars: tuple[Bar, ...], count: int) -> Decimal:
    if len(bars) < count:
        raise V12ContractError("V12_FEATURE_MISSING", f"SMA_{count}")
    return sum((item.close for item in bars[-count:]), Decimal(0)) / Decimal(count)


def _ma(source: StrategyInput, parameters: ParameterSet) -> GateComputation:
    bars, atr, volume, _, _ = base_features(source)
    fast, slow = int(parameters.values["fast"]), int(parameters.values["slow"])
    fast_now, slow_now = _sma(bars, fast), _sma(bars, slow)
    fast_prior, slow_prior = _sma(bars[:-1], fast), _sma(bars[:-1], slow)
    spread, price = (fast_now - slow_now) / atr, (bars[-1].close - fast_now) / atr
    passed = fast_now > slow_now and bars[-1].close > fast_now
    passed = passed and fast_now > fast_prior and slow_now > slow_prior
    return GateComputation(passed=passed, components={"spread": spread, "price": price,
        "rvol": volume}, features={"spread": spread, "price": price, "rvol": volume})


def _relative_strength(source: StrategyInput, parameters: ParameterSet) -> GateComputation:
    bars, _, volume, current_vwap, _ = base_features(source)
    lookback = int(parameters.values["l"])
    if len(bars) <= lookback or len(source.benchmark_bars) <= lookback:
        raise V12ContractError("V12_BENCHMARK_MISSING", str(lookback))
    benchmark = source.benchmark_bars
    expected_benchmark = "KR_BROAD_KS11" if source.market.value == "KR" else "US_BROAD_SPY"
    if source.benchmark_id != expected_benchmark:
        raise V12ContractError("V12_BENCHMARK_IDENTITY", source.benchmark_id)
    if any(not item.complete for item in benchmark) or benchmark[-1].end != source.bars[-1].end:
        raise V12ContractError("V12_BENCHMARK_POINT_IN_TIME", source.symbol)
    symbol_return = bars[-1].close / bars[-lookback - 1].close - 1
    benchmark_return = benchmark[-1].close / benchmark[-lookback - 1].close - 1
    relative = symbol_return - benchmark_return
    relative_percentile = percentile(source, "rs", relative)
    passed = relative > 0 and relative_percentile >= Decimal("0.70") and bars[-1].close > current_vwap
    return GateComputation(passed=passed, components={"rs": relative,
        "ret": symbol_return, "rvol": volume}, features={"rs": relative,
        "ret": symbol_return, "benchmark_ret": benchmark_return, "rvol": volume})


def _volume(source: StrategyInput, side: Side, parameters: ParameterSet) -> GateComputation:
    bars, atr, volume, _, current_clv = base_features(source)
    high, low = prior_range(bars, int(parameters.values["n"]))
    signed = direction(side)
    boundary = high if side is Side.LONG else low
    distance = signed * (bars[-1].close - boundary) / atr
    close_component = current_clv if side is Side.LONG else 1 - current_clv
    return GateComputation(passed=distance > 0 and volume >= parameters.values["r"],
        components={"distance": distance, "rvol": volume, "clv": close_component},
        features={"distance": distance, "rvol": volume, "clv": current_clv})


def _expansion(source: StrategyInput, parameters: ParameterSet) -> GateComputation:
    bars, _, volume, _, current_clv = base_features(source)
    prior_atr = atr14(bars[:-1])
    expansion = true_range(bars[-1], bars[-2]) / prior_atr
    passed = expansion >= parameters.values["e"] and current_clv >= parameters.values["q"]
    passed = passed and bars[-1].close > bars[-2].close
    return GateComputation(passed=passed, components={"expansion": expansion,
        "clv": current_clv, "rvol": volume}, features={"expansion": expansion,
        "clv": current_clv, "rvol": volume})


def _compression(source: StrategyInput, parameters: ParameterSet) -> GateComputation:
    bars, atr, volume, _, _ = base_features(source)
    count = int(parameters.values["n"])
    high, low = prior_range(bars, count)
    compression = (high - low) / atr14(bars[:-1])
    distance = (bars[-1].close - high) / atr
    return GateComputation(passed=compression <= parameters.values["c"] and distance > 0,
        components={"compression": -compression, "distance": distance, "rvol": volume},
        features={"compression": compression, "distance": distance, "rvol": volume})
