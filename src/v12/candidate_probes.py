from __future__ import annotations

from decimal import Decimal

from src.v11.models import Account

from .artifacts import TradeAttribution
from .integrity import verify_attribution
from .models import V12ContractError


type Probe = tuple[str, str]


def run_candidate_probes(trade: TradeAttribution, account: Account) -> tuple[Probe, ...]:
    return (
        _reject("candidate_collision", "V12_IDENTITY_COLLISION",
            trade.model_copy(update={"candidate": trade.candidate.model_copy(
                update={"strategy_id": "other"})}), account),
        _reject("score_out_of_range", "V12_SCORE_RANGE",
            trade.model_copy(update={"candidate": trade.candidate.model_copy(
                update={"deterministic_score": Decimal(2)})}), account),
    )


def _reject(probe_id: str, code: str, trade: TradeAttribution, account: Account) -> Probe:
    observed = "none"
    try:
        verify_attribution(trade, account)
    except V12ContractError as error:
        observed = error.code
    if observed != code:
        raise V12ContractError("V12_PROBE_FAILED", f"{probe_id}:{observed}")
    return probe_id, code
