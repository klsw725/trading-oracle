from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from statistics import median
from typing import Final

from .contract import V14ContractError
from .selection_models import SelectionCandidate, SelectedConfig


EIGHT_PLACES: Final = Decimal("0.00000001")


def quantized_median(candidate: SelectionCandidate) -> Decimal:
    if len(candidate.fold_oos_net_excess_returns) != 4:
        raise V14ContractError("V14_FOLD_SCORE_COUNT", candidate.canonical_id)
    value = median(candidate.fold_oos_net_excess_returns)
    return value.quantize(EIGHT_PLACES, rounding=ROUND_HALF_EVEN)


def selection_order(candidate: SelectionCandidate) -> tuple[Decimal, Decimal, str]:
    return (-quantized_median(candidate), candidate.turnover, candidate.canonical_id)


def choose(candidates: tuple[SelectionCandidate, ...], limit: int) -> SelectedConfig:
    if not candidates or len(candidates) > limit:
        raise V14ContractError("V14_GRID_OVERFLOW", str(len(candidates)))
    ids = tuple(candidate.canonical_id for candidate in candidates)
    if len(ids) != len(set(ids)):
        raise V14ContractError("V14_GRID_ID", min(ids))
    winner = min(candidates, key=selection_order)
    return SelectedConfig(canonical_id=winner.canonical_id,
        median_oos_net_excess_return=quantized_median(winner),
        turnover=winner.turnover)
