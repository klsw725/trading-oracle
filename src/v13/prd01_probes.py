from __future__ import annotations

from decimal import Decimal

from src.v11.canonical import canonical_hash, model_json
from src.v11.models import Account, Market, Position, Side

from src.v13.models import (
    CandidateEvidence,
    RouterRunManifest,
    ScoredCandidate,
    SelectedDecision,
)
from src.v13.policy import build_policy, policy_grid
from src.v13.prd01_fixture import canonical_account, load_fixture, manifest_for
from src.v13.scoring import expected_turnover, midrank_percentiles, score_candidates
from src.v13.selection import allocate, candidate_order, run_router


def _scored(
    candidate: CandidateEvidence, score: Decimal | None = None
) -> ScoredCandidate:
    score = score or Decimal("0.9")
    return ScoredCandidate(
        evidence=candidate,
        deterministic_percentile=score,
        llm_percentile=score,
        composite_score=score,
        expected_turnover=Decimal("0.01"),
        quant_only=False,
    )


def _allocation_manifest(
    candidates: tuple[CandidateEvidence, ...], account: Account, slot_limit: int
) -> RouterRunManifest:
    return RouterRunManifest(
        schema_version="v13.router_run.1",
        run_id="prd01:allocation",
        market=Market.KR,
        cutoff=candidates[0].cutoff,
        policy=build_policy(Decimal("0.70"), Decimal("0.05")),
        account=account,
        candidates=candidates,
        slot_limit=slot_limit,
    )


def run_probes() -> tuple[dict[str, bool], dict[str, str], dict[str, str]]:
    fixture = load_fixture()
    default_manifest = manifest_for(fixture, build_policy())
    result = run_router(default_manifest)
    repeated = run_router(default_manifest)
    scored_by_id = {item.evidence.candidate_id: item for item in result.scored}
    decisions_by_symbol = {item.symbol: item for item in result.decisions}
    policy_states = tuple(
        next(item.state for item in run_router(manifest_for(fixture, policy)).decisions
             if item.symbol == "AAA")
        for policy in policy_grid()
    )
    singleton_candidate = fixture.candidates[0].model_copy(update={
        "candidate_id": "cand:SINGLE:alpha", "symbol": "SINGLE"
    })
    singleton_manifest = RouterRunManifest(
        schema_version="v13.router_run.1", run_id="prd01:singleton",
        market=Market.KR, cutoff=singleton_candidate.cutoff,
        policy=build_policy(Decimal("0.90"), Decimal("0.10")),
        account=canonical_account(), candidates=(singleton_candidate,), slot_limit=1)
    singleton = run_router(singleton_manifest)
    left = fixture.candidates[0].model_copy(update={
        "candidate_id": "cand:ZZZ:alpha", "symbol": "ZZZ",
        "strategy_id": "alpha", "deterministic_score": Decimal("0.9"),
        "llm_score": Decimal("0.9")})
    right = fixture.candidates[1].model_copy(update={
        "candidate_id": "cand:AAA:alpha", "symbol": "AAA",
        "strategy_id": "alpha", "deterministic_score": Decimal("0.9"),
        "llm_score": Decimal("0.9")})
    tied = (_scored(left), _scored(right))
    tied_decisions = tuple(SelectedDecision(symbol=item.evidence.symbol,
        candidate=item, runner_up_score=None, score_gap=None) for item in tied)
    allocation_manifest = _allocation_manifest((left, right), canonical_account(), 2)
    attempts, shadow = allocate(allocation_manifest, tied_decisions, "sha256:allocation")
    reversed_attempts, _ = allocate(
        allocation_manifest, tuple(reversed(tied_decisions)), "sha256:allocation")
    slot_attempts, _ = allocate(
        allocation_manifest.model_copy(update={"slot_limit": 1}),
        tied_decisions, "sha256:allocation")
    held_account = Account(market=Market.KR, currency="KRW",
        prior_close_nav="100000", cash="100000",
        positions=(Position(symbol="AAA", side=Side.SHORT, sector="technology",
            quantity=3, mark_price="100"),))
    held_manifest = _allocation_manifest((right,), held_account, 1)
    held_attempts, held_shadow = allocate(held_manifest,
        (SelectedDecision(symbol="AAA", candidate=_scored(right),
            runner_up_score=None, score_gap=None),), "sha256:held")
    blocked = right.model_copy(update={
        "candidate_id": "cand:BLOCK:alpha", "symbol": "BLOCK",
        "gates": right.gates.model_copy(update={"eligible": False})})
    blocked_manifest = _allocation_manifest((blocked,), canonical_account(), 1)
    blocked_attempts, _ = allocate(blocked_manifest,
        (SelectedDecision(symbol="BLOCK", candidate=_scored(blocked),
            runner_up_score=None, score_gap=None),), "sha256:blocked")
    confidence_changed = tuple(item.model_copy(update={"confidence": Decimal("0")})
        if item.confidence is not None else item for item in fixture.candidates)
    confidence_scores = score_candidates(confidence_changed, canonical_account())
    original_scores = tuple(item.composite_score for item in result.scored)
    changed_scores = tuple(item.composite_score for item in confidence_scores)
    checks = {
        "midrank_edges": midrank_percentiles((Decimal("1"), Decimal("2"),
            Decimal("2"), Decimal("4"))) == (Decimal("0"), Decimal("0.5"),
                Decimal("0.5"), Decimal("1")),
        "all_tie_half": midrank_percentiles((Decimal("2"), Decimal("2")))
            == (Decimal("0.5"), Decimal("0.5")),
        "singleton_one": midrank_percentiles((Decimal("2"),)) == (Decimal("1"),),
        "hard_veto_rerank": "cand:CCC:veto" not in scored_by_id
            and scored_by_id["cand:CCC:valid"].deterministic_percentile == Decimal(2) / Decimal(6),
        "symbol_quant_only": all(item.quant_only and item.llm_percentile is None
            and item.composite_score == item.deterministic_percentile
            for item in result.scored if item.evidence.symbol == "BBB"),
        "confidence_ignored": original_scores == changed_scores,
        "exact_tie_strategy_order": sorted(
            (item for item in result.scored if item.evidence.symbol == "DDD"),
            key=candidate_order)[0].evidence.strategy_id == "eta",
        "policy_grid": policy_states == ("selected", "no_trade", "selected",
            "no_trade", "no_trade", "no_trade"),
        "single_candidate_gap": singleton.decisions[0].state == "selected",
        "no_trade_reasons": decisions_by_symbol["CCC"].state == "no_trade"
            and decisions_by_symbol["DDD"].state == "no_trade",
        "slot_total_order": tuple(item.symbol for item in attempts) == ("AAA", "ZZZ")
            and attempts == reversed_attempts,
        "sequential_shadow": len(shadow.reservations) == 2
            and len(allocation_manifest.account.reservations) == 0
            and attempts[0].risk_input_hash != attempts[1].risk_input_hash,
        "slot_no_trade": tuple(item.state for item in slot_attempts)
            == ("reserved", "no_trade"),
        "held_deferred": held_attempts[0].state == "deferred_held"
            and held_shadow == held_account,
        "signed_turnover": expected_turnover(right, held_account) == Decimal("0.013"),
        "risk_no_trade": blocked_attempts[0].state == "no_trade"
            and blocked_attempts[0].reason_code == "ELIGIBILITY_BLOCKED",
        "repeat_determinism": result == repeated,
    }
    mutations = {
        "confidence_weight": "killed" if checks["confidence_ignored"] else "survived",
        "rank_tie_drift": "killed" if checks["midrank_edges"] else "survived",
        "single_candidate_gap": "killed" if checks["single_candidate_gap"] else "survived",
        "slot_tie_nondeterministic": "killed" if checks["slot_total_order"] else "survived",
    }
    hashes = {
        "fixture_hash": canonical_hash(model_json(fixture)),
        "policy_hash": default_manifest.policy.policy_hash,
        "manifest_hash": result.manifest_hash,
        "selection_hash": result.selection_hash,
    }
    return checks, mutations, hashes
