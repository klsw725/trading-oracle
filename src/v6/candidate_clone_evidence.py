import re
from typing import Final

from .models import (
    CandidateProposal,
    ExistingPerspective,
    OverlapReviewStatus,
)


CORE_OBSERVATIONS: Final = {
    ExistingPerspective.KWANGSOO: frozenset(
        {"stop_loss", "trailing_stop", "leading_stock", "momentum", "risk_budget"}
    ),
    ExistingPerspective.OUROBOROS: frozenset(
        {"dilution", "insider_activity", "institutional_flow", "debt_risk"}
    ),
    ExistingPerspective.QUANT: frozenset(
        {"rsi", "macd", "ema", "bb", "bollinger_band", "momentum", "bull_votes", "bear_votes"}
    ),
    ExistingPerspective.MACRO: frozenset(
        {"interest_rate", "foreign_exchange", "sector_cycle", "causal_chain"}
    ),
    ExistingPerspective.VALUE: frozenset(
        {"per", "pbr", "dividend", "dividend_yield", "peg"}
    ),
}
CORE_FAMILIES: Final = {
    ExistingPerspective.KWANGSOO: frozenset({"trend_following", "position_risk_management"}),
    ExistingPerspective.OUROBOROS: frozenset({"forensic_risk", "dilution_risk"}),
    ExistingPerspective.QUANT: frozenset({"six_signal_vote", "technical_signal_reweighting"}),
    ExistingPerspective.MACRO: frozenset({"macro_cycle", "macro_causal_chain"}),
    ExistingPerspective.VALUE: frozenset({"valuation_threshold", "relative_valuation"}),
}
OBSERVATION_PREFIXES: Final = (
    "fundamentals_",
    "signals_",
    "market_context_",
    "position_",
    "web_context_",
    "fx_signal_",
    "ohlcv_",
)


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    for prefix in OBSERVATION_PREFIXES:
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix)
    return normalized


def duplicates_incumbent(candidate: CandidateProposal) -> bool:
    if candidate.candidate_identity.candidate_name in {
        perspective.value for perspective in ExistingPerspective
    }:
        return True
    observations = {
        _identifier(observation)
        for observation in candidate.independent_hypothesis.primary_observations
    }
    family = _identifier(candidate.independent_hypothesis.novel_signal_family)
    for perspective in ExistingPerspective:
        if family in CORE_FAMILIES[perspective]:
            return True
        if len(observations & CORE_OBSERVATIONS[perspective]) >= 2:
            return True
    return any(
        row.manual_review.status is OverlapReviewStatus.DUPLICATE
        for row in candidate.overlap_matrix
    )
