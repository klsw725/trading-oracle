from __future__ import annotations

from datetime import timedelta

from .artifacts import EmissionState, Evaluation
from .candidates import evaluate
from .models import FixtureCase, ParameterSet, Scenario, StrategySpec, V12ContractError


def emission_key(spec: StrategySpec, parameters: ParameterSet, case: FixtureCase) -> str:
    source = case.input
    return ":".join((source.market.value, source.symbol, source.session_date.isoformat(),
        spec.strategy_id, spec.version, parameters.parameter_set_id, spec.side.value))


def evaluate_stream(case: FixtureCase, spec: StrategySpec, parameters: ParameterSet,
                    state: EmissionState) -> tuple[Evaluation, EmissionState]:
    key = emission_key(spec, parameters, case)
    if key in state.emitted_keys:
        result = Evaluation(case_id=f"{case.strategy_id}:{case.scenario.value}",
            scenario=Scenario.NO_SIGNAL, strategy_id=spec.strategy_id,
            parameter_set_id=parameters.parameter_set_id, candidate=None,
            result_code="DUPLICATE_SESSION_NO_OP", feature_evaluated=False)
        return result, state
    if any(not bar.complete for bar in (*case.input.prior_bars, *case.input.bars)):
        if case.scenario is Scenario.MISSING:
            result = Evaluation(case_id=f"{case.strategy_id}:{case.scenario.value}",
                scenario=Scenario.MISSING, strategy_id=spec.strategy_id,
                parameter_set_id=parameters.parameter_set_id, candidate=None,
                result_code="V12_INCOMPLETE_FEATURE", feature_evaluated=False)
            return result, state
        raise V12ContractError("V12_INCOMPLETE_FEATURE", case.strategy_id)
    observed_true = state.last_gate_states.get(key, False)
    prior_cutoff = state.last_cutoffs.get(key)
    last_result: Evaluation | None = None
    for index in range(1, len(case.input.bars) + 1):
        cutoff = case.input.bars[index - 1].end
        binding = next((item for item in case.input.execution_bindings
                        if item.cutoff == cutoff), None)
        if binding is None:
            raise V12ContractError("V12_EXECUTION_BINDING_MISSING", cutoff.isoformat())
        source = case.input.model_copy(update={"bars": case.input.bars[:index],
            "benchmark_bars": case.input.benchmark_bars[:index],
            "watermark_at": cutoff.replace(microsecond=0) + timedelta(seconds=10),
            "causal_sizing": binding.causal_sizing,
            "execution_snapshot": binding.execution_snapshot,
            "execution_bindings": (binding,)})
        if prior_cutoff is not None and cutoff <= prior_cutoff:
            raise V12ContractError("V12_STREAM_TIME_ORDER", key)
        prior_cutoff = cutoff
        try:
            current = evaluate(f"{case.strategy_id}:{case.scenario.value}", spec, parameters, source)
        except V12ContractError as error:
            if error.code in {"V12_FEATURE_MISSING", "V12_P60_HISTORY",
                              "V12_BENCHMARK_MISSING"}:
                continue
            raise
        passed = current.candidate is not None
        if passed and not observed_true:
            current = current.model_copy(update={"bound_input": source})
            cutoffs = {**state.last_cutoffs, key: cutoff}
            gates = {**state.last_gate_states, key: True}
            emitted = EmissionState(emitted_keys=tuple(sorted((*state.emitted_keys, key))),
                last_cutoffs=cutoffs, last_gate_states=gates)
            return current, emitted
        observed_true = passed
        last_result = current
    if last_result is None:
        last_result = Evaluation(case_id=f"{case.strategy_id}:{case.scenario.value}",
            scenario=Scenario.NO_SIGNAL, strategy_id=spec.strategy_id,
            parameter_set_id=parameters.parameter_set_id, candidate=None,
            result_code="NO_SIGNAL", feature_evaluated=True)
    return last_result, state.model_copy(update={"last_cutoffs": {**state.last_cutoffs,
        **({key: prior_cutoff} if prior_cutoff is not None else {})},
        "last_gate_states": {**state.last_gate_states, key: observed_true}})
