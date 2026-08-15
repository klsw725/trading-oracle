from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Final

from src.v11.models import Account, Side

from src.v13.models import CandidateEvidence, ScoredCandidate


TIE_QUANTUM: Final = Decimal("0.00000001")


def tie_value(value: Decimal) -> Decimal:
    return value.quantize(TIE_QUANTUM, rounding=ROUND_HALF_EVEN)


def midrank_percentiles(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    size = len(values)
    if size == 0:
        return ()
    if size == 1:
        return (Decimal(1),)
    if len(set(values)) == 1:
        return tuple(Decimal("0.5") for _ in values)
    denominator = Decimal(size - 1)
    return tuple(
        (Decimal(sum(item < value for item in values))
         + Decimal(sum(item == value for item in values) + 1) / Decimal(2)
         - Decimal(1))
        / denominator
        for value in values
    )


def expected_turnover(candidate: CandidateEvidence, account: Account) -> Decimal:
    current_signed = sum(
        (
            position.quantity
            if position.side is Side.LONG
            else -position.quantity
        )
        for position in account.positions
        if position.symbol == candidate.symbol
    )
    target_signed = (
        candidate.target_quantity
        if candidate.side is Side.LONG
        else -candidate.target_quantity
    )
    changed_notional = (
        Decimal(abs(target_signed - current_signed)) * candidate.reference_price
    )
    return changed_notional / Decimal(account.prior_close_nav)


def score_candidates(
    candidates: tuple[CandidateEvidence, ...], account: Account
) -> tuple[ScoredCandidate, ...]:
    active = tuple(
        sorted(
            (item for item in candidates if not item.hard_veto_verified),
            key=lambda item: item.candidate_id,
        )
    )
    deterministic = midrank_percentiles(
        tuple(item.deterministic_score for item in active)
    )
    quant_symbols = {
        item.symbol for item in active if not item.item_valid or item.abstain
    }
    llm_candidates = tuple(
        item for item in active if item.symbol not in quant_symbols
    )
    llm_values = tuple(
        item.llm_score
        for item in llm_candidates
        if item.llm_score is not None
    )
    llm_percentiles = midrank_percentiles(llm_values)
    llm_by_id = {
        item.candidate_id: percentile
        for item, percentile in zip(llm_candidates, llm_percentiles, strict=True)
    }
    scored: list[ScoredCandidate] = []
    for item, deterministic_percentile in zip(active, deterministic, strict=True):
        quant_only = item.symbol in quant_symbols
        llm_percentile = None if quant_only else llm_by_id[item.candidate_id]
        composite = (
            deterministic_percentile
            if quant_only
            else Decimal("0.80") * deterministic_percentile
            + Decimal("0.20") * llm_by_id[item.candidate_id]
        )
        scored.append(
            ScoredCandidate(
                evidence=item,
                deterministic_percentile=deterministic_percentile,
                llm_percentile=llm_percentile,
                composite_score=composite,
                expected_turnover=expected_turnover(item, account),
                quant_only=quant_only,
            )
        )
    return tuple(scored)
