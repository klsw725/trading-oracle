from __future__ import annotations

from datetime import timedelta

from src.v4.models import canonical_json
from src.v11.canonical import model_json

from .artifacts import EmissionState
from .models import Bar, CohortFixture, Scenario, V12ContractError
from .registry import strategy
from .strategy_input_fixture import bind_cases, build_source_fixture
from .stream import evaluate_stream


def semantic_probe(fixture: CohortFixture, kind: str) -> None:
    cases = list(fixture.cases)
    strategy_id = ("long_relative_strength" if kind == "future_benchmark"
        else "short_orb_15m" if kind in {"borrow_lookahead", "borrow_future", "borrow_expired"}
        else "long_orb_15m")
    case = next(item for item in cases if item.strategy_id == strategy_id
                and item.scenario is Scenario.HAPPY)
    source = case.input
    if kind == "causal_future":
        future = tuple(item.model_copy(update={"causal_sizing": item.causal_sizing.model_copy(
            update={"observed_at": item.cutoff + timedelta(minutes=1)})})
            for item in source.execution_bindings)
        source = source.model_copy(update={"execution_bindings": future})
    if kind in {"borrow_lookahead", "borrow_future", "borrow_expired"}:
        borrow = source.borrow
        if borrow is None:
            raise V12ContractError("V12_PROBE_FAILED", f"{kind}:missing")
        if kind == "borrow_lookahead":
            source = source.model_copy(update={"borrow": borrow.model_copy(update={
                "evaluated_at": source.bars[-1].end + timedelta(minutes=1)})})
        elif kind == "borrow_future":
            effective_from = source.bars[-1].end + timedelta(minutes=1)
            effective_until = effective_from + timedelta(days=1)
            source = source.model_copy(update={"borrow": borrow.model_copy(update={
                "effective_from": effective_from, "effective_until": effective_until})})
        else:
            effective_from = source.regular_open - timedelta(days=1)
            effective_until = source.bars[0].end
            source = source.model_copy(update={"borrow": borrow.model_copy(update={
                "effective_from": effective_from, "effective_until": effective_until,
                "recalled_at": None})})
    match kind:  # noqa: MATCH_OK - unknown probe kinds fail with a typed contract error
        case "causal_future" | "borrow_lookahead" | "borrow_future" | "borrow_expired":
            pass
        case "wick":
            high = max(item.high for item in source.bars[:3])
            later = tuple(item.model_copy(update={"open": high, "high": high,
                "low": high - 1, "close": high, "volume": 100}) for item in source.bars[3:])
            current = later[-1].model_copy(update={"high": high + 1})
            source = source.model_copy(update={"bars": (*source.bars[:3], *later[:-1], current)})
        case "late":
            high = max(item.high for item in source.bars[:3])
            flat = tuple(item.model_copy(update={"open": high, "high": high,
                "low": high - 1, "close": high, "volume": 100}) for item in source.bars[3:])
            prior = flat[-1]
            late = _next_bar(prior).model_copy(update={"open": high, "high": high + 2,
                "low": high - 1, "close": high + 1})
            prior_binding = source.execution_bindings[-1]
            late_binding = prior_binding.model_copy(update={"cutoff": late.end,
                "causal_sizing": prior_binding.causal_sizing.model_copy(update={
                    "observed_at": late.end, "close": late.close}),
                "execution_snapshot": prior_binding.execution_snapshot.model_copy(update={
                    "target_at": late.end + timedelta(minutes=1)})})
            source = source.model_copy(update={"bars": (*source.bars[:3], *flat, late),
                "benchmark_bars": (*source.benchmark_bars, _next_bar(source.benchmark_bars[-1])),
                "watermark_at": late.end + timedelta(seconds=10),
                "execution_bindings": (*source.execution_bindings, late_binding)})
        case "incomplete":
            current = source.bars[-1].model_copy(update={"complete": False})
            source = source.model_copy(update={"bars": (*source.bars[:-1], current)})
        case "future_benchmark":
            future = tuple(item.model_copy(update={"start": item.start + timedelta(minutes=5),
                "end": item.end + timedelta(minutes=5),
                "observed_at": item.observed_at + timedelta(minutes=5),
                "watermark_at": item.watermark_at + timedelta(minutes=5)})
                for item in source.benchmark_bars)
            source = source.model_copy(update={"benchmark_bars": future})
        case _:
            raise V12ContractError("V12_PROBE_FAILED", kind)
    case_index = cases.index(case)
    cases[case_index] = case.model_copy(update={"input": source})
    raw_cases = tuple(cases)
    source_fixture = build_source_fixture(tuple(
        (f"{item.strategy_id}:{item.scenario.value}", item.input) for item in raw_cases))
    bound_cases, _ = bind_cases(raw_cases, source_fixture)
    changed = bound_cases[case_index]
    spec = strategy(changed.strategy_id)
    result, _ = evaluate_stream(changed, spec, spec.parameter_sets[0],
        EmissionState(emitted_keys=(), last_cutoffs={}, last_gate_states={}))
    if kind == "causal_future" and result.candidate is not None and result.bound_input is not None:
        from .shadow import verify_causal_timing
        verify_causal_timing(result.candidate, result.bound_input)
    if result.candidate is None:
        raise V12ContractError(result.result_code, kind)
    raise V12ContractError("V12_PROBE_UNEXPECTED_CANDIDATE", kind)


def verify_unused_future_binding_invariance(fixture: CohortFixture) -> None:
    cases = list(fixture.cases)
    case = next(item for item in cases if item.strategy_id == "long_orb_15m"
                and item.scenario is Scenario.HAPPY)
    spec = strategy(case.strategy_id)
    parameters = spec.parameter_sets[0]
    empty_state = EmissionState(emitted_keys=(), last_cutoffs={}, last_gate_states={})
    baseline, _ = evaluate_stream(case, spec, parameters, empty_state)
    if baseline.candidate is None or baseline.bound_input is None:
        raise V12ContractError("V12_PROBE_FAILED", "unused_future_binding:baseline")
    future = next(item for item in case.input.execution_bindings
                  if item.cutoff > baseline.candidate.signal_cutoff)
    mutated = future.model_copy(update={"causal_sizing": future.causal_sizing.model_copy(
        update={"close": future.causal_sizing.close + 1})})
    bindings = tuple(mutated if item.cutoff == future.cutoff else item
                     for item in case.input.execution_bindings)
    case_index = cases.index(case)
    cases[case_index] = case.model_copy(update={"input": case.input.model_copy(
        update={"execution_bindings": bindings})})
    source_fixture = build_source_fixture(tuple(
        (f"{item.strategy_id}:{item.scenario.value}", item.input) for item in cases))
    resealed_cases, _ = bind_cases(tuple(cases), source_fixture)
    resealed_future = next(item for item in resealed_cases[case_index].input.execution_bindings
                           if item.cutoff == future.cutoff)
    trusted_bindings = tuple(resealed_future if item.cutoff == future.cutoff else item
                             for item in case.input.execution_bindings)
    changed = case.model_copy(update={"input": case.input.model_copy(
        update={"execution_bindings": trusted_bindings})})
    observed, _ = evaluate_stream(changed, spec, parameters, empty_state)
    if observed.candidate is None or observed.bound_input is None:
        raise V12ContractError("V12_PROBE_FAILED", "unused_future_binding:observed")
    candidate_bytes = canonical_json(model_json(baseline.candidate))
    observed_bytes = canonical_json(model_json(observed.candidate))
    same_target = baseline.bound_input.execution_snapshot == observed.bound_input.execution_snapshot
    if (candidate_bytes != observed_bytes
            or baseline.candidate.feature_snapshot_hash != observed.candidate.feature_snapshot_hash
            or baseline.candidate.deterministic_score != observed.candidate.deterministic_score
            or not same_target):
        raise V12ContractError("V12_PROBE_FAILED", "unused_future_binding:changed")


def _next_bar(bar: Bar) -> Bar:
    return bar.model_copy(update={"start": bar.end,
        "end": bar.end + timedelta(minutes=5),
        "observed_at": bar.end + timedelta(minutes=5, seconds=5),
        "watermark_at": bar.end + timedelta(minutes=5, seconds=10)})
