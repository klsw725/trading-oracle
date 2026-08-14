from __future__ import annotations

from pydantic import ValidationError

from src.v4.models import JsonValue
from src.v11.canonical import canonical_hash

from .adapters import verify_upstream
from .artifacts import EmissionState, Evaluation, RunArtifacts, TradeAttribution
from .bundle import seal_bundle
from .fixture_validation import validate_fixture_matrix
from .manifest import build_manifests, registry_hash
from .models import CohortFixture, Scenario, V12ContractError
from .registry import strategy, validate_registry
from .shadow import execute, make_execution_feasible
from .stream import evaluate_stream


def build_fixture(value: JsonValue) -> JsonValue:
    validate_registry()
    try:
        fixture = CohortFixture.model_validate(value)
    except ValidationError as error:
        raise V12ContractError("V12_FIXTURE_ERROR", str(error)) from error
    validate_fixture_matrix(fixture)
    upstream_hash = verify_upstream(fixture)
    source_hash = canonical_hash(value)
    manifests = build_manifests(fixture, source_hash)
    manifest_by_arm = {item.arm_id: item for item in manifests}
    evaluations: list[Evaluation] = []
    trades: list[TradeAttribution] = []
    emitted: set[str] = set()
    for case in fixture.cases:
        spec = strategy(case.strategy_id)
        for parameters in spec.parameter_sets:
            result, state = evaluate_stream(case, spec, parameters,
                EmissionState(emitted_keys=(), last_cutoffs={}, last_gate_states={}))
            _verify_expected(case.scenario, result)
            evaluations.append(result)
            if result.candidate is None:
                continue
            emitted.update(state.emitted_keys)
            arm = f"v12:arm:{spec.strategy_id}:{parameters.parameter_set_id}"
            if result.bound_input is None:
                raise V12ContractError("V12_EXECUTION_BINDING_MISSING", result.case_id)
            feasible, _, _ = make_execution_feasible(result.candidate, result.bound_input,
                                                      fixture.execution, manifest_by_arm[arm])
            trades.append(execute(feasible, result.bound_input, fixture.execution,
                                  manifest_by_arm[arm]))
    emission_state = EmissionState(emitted_keys=tuple(sorted(emitted)),
        last_cutoffs={item: next(trade.candidate.signal_cutoff for trade in trades
            if item.endswith(f":{trade.candidate.strategy_id}:{trade.candidate.strategy_version}:{trade.candidate.parameter_set_id}:{trade.candidate.side.value}"))
            for item in sorted(emitted)}, last_gate_states={item: True for item in emitted})
    run_body: dict[str, JsonValue] = {"manifests": [item.model_dump(mode="json") for item in manifests],
        "evaluations": [item.model_dump(mode="json") for item in evaluations],
        "emission_state": emission_state.model_dump(mode="json"),
        "trades": [item.model_dump(mode="json") for item in trades]}
    run = RunArtifacts(manifest_hash=canonical_hash(run_body), manifests=manifests,
        evaluations=tuple(evaluations), emission_state=emission_state, trades=tuple(trades))
    return seal_bundle(value, upstream_hash, registry_hash(), run)


def _verify_expected(scenario: Scenario, result: Evaluation) -> None:
    match scenario:  # noqa: MATCH_OK - Scenario enum is exhaustively covered
        case Scenario.HAPPY:
            valid = result.candidate is not None
        case Scenario.NO_SIGNAL:
            valid = result.candidate is None and result.result_code == "NO_SIGNAL"
        case Scenario.MISSING:
            valid = result.candidate is None and result.result_code.startswith("V12_")
    if not valid:
        raise V12ContractError("V12_CASE_RESULT", result.case_id)
