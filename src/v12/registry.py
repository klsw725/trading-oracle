from __future__ import annotations

from decimal import Decimal
from typing import Final

from .models import ParameterSet, Side, StrategySpec, V12ContractError


def _sets(prefix: str, names: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> tuple[ParameterSet, ...]:
    return tuple(ParameterSet(parameter_set_id=f"{prefix}_{chr(65 + index)}",
        values={name: Decimal(value) for name, value in zip(names, row, strict=True)})
        for index, row in enumerate(rows))


def _spec(strategy_id: str, side: Side, evaluator: str, prefix: str,
          names: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> StrategySpec:
    return StrategySpec(strategy_id=strategy_id, version="v12.2", side=side,
        evaluator=evaluator, parameter_sets=_sets(prefix, names, rows))


_BR: Final = (("0", "1"), ("0", "1.5"), ("0.05", "1"), ("0.05", "1.5"))
_NB: Final = (("6", "0"), ("6", "0.05"), ("12", "0"), ("12", "0.05"))
_GW: Final = (("0.01", "15"), ("0.01", "30"), ("0.02", "15"), ("0.02", "30"))
_KB: Final = (("1", "0"), ("1", "0.05"), ("2", "0"), ("2", "0.05"))
_NR: Final = (("6", "1.5"), ("6", "2"), ("12", "1.5"), ("12", "2"))

REGISTRY: Final = (
    _spec("long_orb_15m", Side.LONG, "orb15", "L15", ("b", "r"), _BR),
    _spec("long_orb_30m", Side.LONG, "orb30", "L30", ("b", "r"), _BR),
    _spec("long_gap_continuation", Side.LONG, "gap", "LGC", ("g", "w"), _GW),
    _spec("long_session_high_breakout", Side.LONG, "session", "LSH", ("n", "b"), _NB),
    _spec("long_vwap_reclaim", Side.LONG, "vwap", "LVR", ("k", "b"), _KB),
    _spec("long_ma_trend", Side.LONG, "ma", "LMA", ("fast", "slow"),
          (("3", "9"), ("6", "18"), ("9", "27"), ("12", "36"))),
    _spec("long_relative_strength", Side.LONG, "rs", "LRS", ("l",),
          (("6",), ("12",), ("24",), ("36",))),
    _spec("long_volume_breakout", Side.LONG, "volume", "LVB", ("n", "r"), _NR),
    _spec("long_volatility_expansion", Side.LONG, "expansion", "LVE", ("e", "q"),
          (("1.25", "0.70"), ("1.25", "0.80"), ("1.50", "0.70"), ("1.50", "0.80"))),
    _spec("long_range_compression", Side.LONG, "compression", "LRC", ("n", "c"),
          (("3", "0.75"), ("3", "0.50"), ("6", "0.75"), ("6", "0.50"))),
    _spec("short_orb_15m", Side.SHORT, "orb15", "S15", ("b", "r"), _BR),
    _spec("short_gap_continuation", Side.SHORT, "gap", "SGC", ("g", "w"), _GW),
    _spec("short_session_low_breakdown", Side.SHORT, "session", "SSL", ("n", "b"), _NB),
    _spec("short_vwap_rejection", Side.SHORT, "vwap", "SVR", ("k", "b"), _KB),
    _spec("short_volume_breakdown", Side.SHORT, "volume", "SVB", ("n", "r"), _NR),
)


def validate_registry(registry: tuple[StrategySpec, ...] = REGISTRY) -> None:
    expected = {item.strategy_id for item in REGISTRY}
    observed = {item.strategy_id for item in registry}
    if observed != expected or len(registry) != 15:
        raise V12ContractError("V12_STRATEGY_INVENTORY", str(sorted(expected ^ observed)))
    for spec in registry:
        if len(spec.parameter_sets) != 4:
            raise V12ContractError("V12_GRID_COUNT", spec.strategy_id)
        if len({item.parameter_set_id for item in spec.parameter_sets}) != 4:
            raise V12ContractError("V12_GRID_ID", spec.strategy_id)
    if registry != REGISTRY:
        raise V12ContractError("V12_SHARED_GRID", "KR_US_DRIFT")


def strategy(strategy_id: str) -> StrategySpec:
    match tuple(item for item in REGISTRY if item.strategy_id == strategy_id):
        case (found,):
            return found
        case _:
            raise V12ContractError("V12_STRATEGY_UNKNOWN", strategy_id)
