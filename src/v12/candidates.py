from __future__ import annotations

from decimal import Decimal

from src.v4.models import JsonValue
from src.v11.canonical import canonical_hash

from .artifacts import Candidate, Evaluation
from .evaluators import evaluate_gate
from .features import percentile, snapshot
from .models import ParameterSet, Scenario, Side, StrategyInput, StrategySpec, V12ContractError


def evaluate(case_id: str, spec: StrategySpec, parameters: ParameterSet,
             source: StrategyInput) -> Evaluation:
    if parameters not in spec.parameter_sets:
        raise V12ContractError("V12_PARAMETER_UNKNOWN", parameters.parameter_set_id)
    if spec.side is Side.SHORT:
        borrow = source.borrow
        if borrow is None or not borrow.eligible:
            return Evaluation(case_id=case_id, scenario=Scenario.MISSING,
                strategy_id=spec.strategy_id, parameter_set_id=parameters.parameter_set_id,
                candidate=None, result_code="SHORT_INELIGIBLE", feature_evaluated=False)
        cutoff = source.bars[-1].end
        if borrow.evaluated_at > cutoff:
            raise V12ContractError("V12_SHORT_BORROW_LOOKAHEAD", cutoff.isoformat())
        if borrow.effective_from > cutoff:
            raise V12ContractError("V12_SHORT_BORROW_NOT_EFFECTIVE", cutoff.isoformat())
        if cutoff >= borrow.effective_until:
            raise V12ContractError("V12_SHORT_BORROW_EXPIRED", cutoff.isoformat())
    computation = evaluate_gate(spec, parameters, source)
    if not computation.passed:
        return Evaluation(case_id=case_id, scenario=Scenario.NO_SIGNAL,
            strategy_id=spec.strategy_id, parameter_set_id=parameters.parameter_set_id,
            candidate=None, result_code="NO_SIGNAL", feature_evaluated=True)
    percentiles = tuple(percentile(source, name, value)
                        for name, value in computation.components.items())
    score = sum(percentiles, Decimal(0)) / Decimal(len(percentiles))
    if not Decimal(0) <= score <= Decimal(1) or not score.is_finite():
        raise V12ContractError("V12_SCORE_RANGE", str(score))
    feature_snapshot = snapshot(source, computation.features)
    identity: dict[str, JsonValue] = {"market": source.market.value, "symbol": source.symbol,
        "strategy_id": spec.strategy_id, "strategy_version": spec.version,
        "parameter_set_id": parameters.parameter_set_id,
        "cutoff": feature_snapshot.cutoff.isoformat()}
    candidate = Candidate(candidate_id=f"v12:candidate:{canonical_hash(identity)[7:]}",
        market=source.market, symbol=source.symbol, strategy_id=spec.strategy_id,
        strategy_version=spec.version, parameter_set_id=parameters.parameter_set_id,
        side=spec.side, signal_cutoff=feature_snapshot.cutoff,
        feature_snapshot_hash=feature_snapshot.input_hash, deterministic_score=score,
        entry_boundary="first_1m_after_decision", exit_policy="close_minus_5_or_forced",
        eligibility_refs=source.eligibility_refs, lifecycle="pre_portfolio_candidate")
    return Evaluation(case_id=case_id, scenario=Scenario.HAPPY,
        strategy_id=spec.strategy_id, parameter_set_id=parameters.parameter_set_id,
        candidate=candidate, result_code="CANDIDATE_EMITTED", feature_evaluated=True)
