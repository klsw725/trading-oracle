from __future__ import annotations

from decimal import Decimal
from src.v11.canonical import canonical_hash, model_json, money
from src.v11.models import Account, Decision
from src.v11.reservations import reserve
from src.v11.risk import check_risk
from src.v4.models import JsonValue

from src.v13.models import (
    AllocationAttempt,
    NoTradeDecision,
    RouterRunManifest,
    RouterSelection,
    ScoredCandidate,
    SelectedDecision,
    SymbolDecision,
)
from src.v13.scoring import score_candidates, tie_value


def candidate_order(candidate: ScoredCandidate) -> tuple[Decimal, Decimal, Decimal, str]:
    return (
        -tie_value(candidate.composite_score),
        -tie_value(candidate.deterministic_percentile),
        tie_value(candidate.expected_turnover),
        candidate.evidence.strategy_id,
    )


def allocation_order(
    candidate: ScoredCandidate,
) -> tuple[Decimal, Decimal, Decimal, str, str]:
    return (
        -tie_value(candidate.composite_score),
        -tie_value(candidate.deterministic_percentile),
        tie_value(candidate.expected_turnover),
        candidate.evidence.symbol,
        candidate.evidence.strategy_id,
    )


def select_symbols(
    manifest: RouterRunManifest, scored: tuple[ScoredCandidate, ...]
) -> tuple[SymbolDecision, ...]:
    symbols = tuple(sorted({item.symbol for item in manifest.candidates}))
    decisions: list[SymbolDecision] = []
    for symbol in symbols:
        ranked = tuple(
            sorted(
                (item for item in scored if item.evidence.symbol == symbol),
                key=candidate_order,
            )
        )
        if not ranked:
            decisions.append(
                NoTradeDecision(
                    symbol=symbol,
                    reason_code="NO_CANDIDATE",
                    best_score=None,
                    score_gap=None,
                )
            )
            continue
        best = ranked[0]
        runner_up = ranked[1].composite_score if len(ranked) > 1 else None
        gap = best.composite_score - runner_up if runner_up is not None else None
        if best.composite_score < manifest.policy.minimum_score:
            decisions.append(
                NoTradeDecision(
                    symbol=symbol,
                    reason_code="MINIMUM_SCORE",
                    best_score=best.composite_score,
                    score_gap=gap,
                )
            )
        elif gap is not None and gap < manifest.policy.minimum_gap:
            decisions.append(
                NoTradeDecision(
                    symbol=symbol,
                    reason_code="MINIMUM_GAP",
                    best_score=best.composite_score,
                    score_gap=gap,
                )
            )
        else:
            decisions.append(
                SelectedDecision(
                    symbol=symbol,
                    candidate=best,
                    runner_up_score=runner_up,
                    score_gap=gap,
                )
            )
    return tuple(decisions)


def _v11_decision(manifest_hash: str, candidate: ScoredCandidate) -> Decision:
    evidence = candidate.evidence
    identity: JsonValue = {
        "manifest_hash": manifest_hash,
        "candidate_id": evidence.candidate_id,
    }
    decision_id = f"v13:decision:{canonical_hash(identity)[7:27]}"
    return Decision(
        decision_id=decision_id,
        candidate_id=evidence.candidate_id,
        router_decision_id=manifest_hash,
        strategy_id=evidence.strategy_id,
        strategy_version=evidence.strategy_version,
        market=evidence.market,
        symbol=evidence.symbol,
        sector=evidence.sector,
        side=evidence.side,
        action="open",
        cutoff=evidence.cutoff,
        watermark_at=evidence.watermark_at,
        decision_ready_at=evidence.decision_ready_at,
        deterministic_score=money(evidence.deterministic_score),
    )


def allocate(
    manifest: RouterRunManifest,
    decisions: tuple[SymbolDecision, ...],
    manifest_hash: str,
) -> tuple[tuple[AllocationAttempt, ...], Account]:
    selected: list[ScoredCandidate] = []
    for decision in decisions:
        candidate = decision.allocation_candidate
        if candidate is not None:
            selected.append(candidate)
    shadow = manifest.account
    attempts: list[AllocationAttempt] = []
    reserved_count = 0
    held_symbols = {position.symbol for position in manifest.account.positions}
    for candidate in sorted(selected, key=allocation_order):
        evidence = candidate.evidence
        if evidence.symbol in held_symbols:
            attempts.append(AllocationAttempt(candidate_id=evidence.candidate_id,
                symbol=evidence.symbol, state="deferred_held", reason_code="HELD_SYMBOL",
                reservation=None, risk_input_hash=None))
            continue
        if reserved_count >= manifest.slot_limit:
            attempts.append(AllocationAttempt(candidate_id=evidence.candidate_id,
                symbol=evidence.symbol, state="no_trade", reason_code="SLOT_LIMIT",
                reservation=None, risk_input_hash=None))
            continue
        risk = check_risk(shadow, _v11_decision(manifest_hash, candidate),
            evidence.target_quantity, money(evidence.reference_price),
            evidence.candidate_returns or None, manifest.existing_returns,
            evidence.gates, money(evidence.expected_cost))
        if risk.state == "blocked" or risk.reservation is None:
            attempts.append(AllocationAttempt(candidate_id=evidence.candidate_id,
                symbol=evidence.symbol, state="no_trade", reason_code=risk.reason_code,
                reservation=None, risk_input_hash=risk.input_hash))
            continue
        shadow = reserve(shadow, risk.reservation)
        reserved_count += 1
        attempts.append(AllocationAttempt(candidate_id=evidence.candidate_id,
            symbol=evidence.symbol, state="reserved", reason_code=risk.reason_code,
            reservation=risk.reservation, risk_input_hash=risk.input_hash))
    return tuple(attempts), shadow


def run_router(manifest: RouterRunManifest) -> RouterSelection:
    manifest_hash = canonical_hash(model_json(manifest))
    scored = score_candidates(manifest.candidates, manifest.account)
    decisions = select_symbols(manifest, scored)
    attempts, shadow = allocate(manifest, decisions, manifest_hash)
    body: JsonValue = {
        "manifest_hash": manifest_hash,
        "scored": [model_json(item) for item in scored],
        "decisions": [model_json(item) for item in decisions],
        "attempts": [model_json(item) for item in attempts],
        "final_shadow_account": model_json(shadow),
    }
    return RouterSelection(manifest_hash=manifest_hash, scored=scored,
        decisions=decisions, attempts=attempts, final_shadow_account=shadow,
        selection_hash=canonical_hash(body))
