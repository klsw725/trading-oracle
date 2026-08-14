from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from pydantic import ValidationError

from src.v4.models import canonical_json
from src.v11.models import Account, V11ContractError

from .artifacts import TradeAttribution
from .bundle import ArtifactBundle
from .borrow_cost_probes import run_borrow_cost_probes
from .candidate_probes import run_candidate_probes
from .integrity import verify_attribution
from .models import CohortFixture, V12ContractError
from .replay import replay
from src.v12.risk_kill_probes import fake_risk_kill, ignored_risk_kill, missing_risk_kill, wrong_risk_kill_time
from .semantic_probes import semantic_probe, verify_unused_future_binding_invariance
from .verifier import verify_bundle


Probe = tuple[str, str]


def _reject(probe_id: str, code: str, operation: Callable[[], None]) -> Probe:
    observed = "none"
    try:
        operation()
    except (V12ContractError, V11ContractError, ValidationError) as error:
        observed = error.code if isinstance(error, (V12ContractError, V11ContractError)) else "V12_MODEL_VALIDATION"
    if observed != code:
        raise V12ContractError("V12_PROBE_FAILED", f"{probe_id}:{observed}")
    return probe_id, code


def _pass(probe_id: str, operation: Callable[[], None]) -> Probe:
    operation()
    return probe_id, "PASS"


def run_probes(payload: bytes) -> tuple[Probe, ...]:
    bundle = verify_bundle(payload)
    fixture = CohortFixture.model_validate(bundle.source_fixture)
    first = bundle.run.trades[0]
    long_risk_kill = next(item for item in bundle.run.trades
        if item.candidate.side.value == "long" and item.exit_reason == "risk_kill")
    short_risk_kill = next(item for item in bundle.run.trades
        if item.candidate.side.value == "short" and item.exit_reason == "risk_kill")
    recalled = next(item for item in bundle.run.trades
        if item.exit_reason == "short_recall")
    close = next(item for item in bundle.run.trades if item.exit_reason == "session_close")
    short_close = next(item for item in bundle.run.trades
        if item.candidate.side.value == "short" and item.exit_reason == "session_close")
    blockers = (
        _reject("fake_upstream_ref", "V12_UPSTREAM_SERIES_ORDER",
            lambda: _source_mutation(bundle, "fake_ref")),
        _reject("retained_ref_bar_body", "V12_UPSTREAM_BAR_BODY",
            lambda: _source_mutation(bundle, "bar_body")),
        _reject("retained_ref_observation", "V12_UPSTREAM_BAR_BODY",
            lambda: _source_mutation(bundle, "observation")),
        _reject("retained_ref_source", "V12_UPSTREAM_BAR_BODY",
            lambda: _source_mutation(bundle, "source_body")),
        _reject("retained_ref_adjustment", "V12_UPSTREAM_SERIES_BODY",
            lambda: _source_mutation(bundle, "adjustment")),
        _reject("retained_ref_benchmark", "V12_UPSTREAM_BAR_BODY",
            lambda: _source_mutation(bundle, "benchmark_body")),
        _reject("case_matrix_missing", "V12_CASE_MATRIX_COUNT",
            lambda: _source_mutation(bundle, "case_missing")),
        _reject("current_in_reference", "V12_UPSTREAM_HISTORY_BODY",
            lambda: _source_mutation(bundle, "p60_slot")),
        _reject("future_benchmark", "V12_BENCHMARK_POINT_IN_TIME",
            lambda: semantic_probe(fixture, "future_benchmark")),
        _reject("short_without_borrow", "V12_UPSTREAM_BORROW_BODY",
            lambda: _source_mutation(bundle, "borrow_missing")),
        _reject("short_borrow_observation_lookahead", "V12_SHORT_BORROW_LOOKAHEAD",
            lambda: semantic_probe(fixture, "borrow_lookahead")),
        _reject("short_borrow_not_yet_effective", "V12_SHORT_BORROW_NOT_EFFECTIVE",
            lambda: semantic_probe(fixture, "borrow_future")),
        _reject("short_borrow_expired", "V12_SHORT_BORROW_EXPIRED",
            lambda: semantic_probe(fixture, "borrow_expired")),
        _reject("future_causal_sizing", "V12_CAUSAL_LOOKAHEAD",
            lambda: semantic_probe(fixture, "causal_future")),
        _reject("duplicate_session_signal", "V12_DUPLICATE_SESSION",
            lambda: _duplicate(bundle)),
        _reject("ownership_transfer", "V12_ATTRIBUTION_OWNER",
            lambda: verify_attribution(first.model_copy(update={"manifest": first.manifest.model_copy(
                update={"owner_namespace": "shadow/KR/other/L15_A"})}), fixture.execution.account)),
        _reject("ledger_event_mutation", "V11_PAYLOAD_HASH",
            lambda: _event_mutation(first, fixture.execution.account)),
        _reject("cost_mutation", "V12_ATTRIBUTION_COST",
            lambda: verify_attribution(first.model_copy(update={"entry_costs": first.entry_costs.model_copy(
                update={"total": "999"})}), fixture.execution.account)),
        _reject("forced_exit_mutation", "V12_ATTRIBUTION_FORCED_EXIT",
            lambda: verify_attribution(close.model_copy(update={"exit_reason": "risk_kill"}),
                                       fixture.execution.account)),
        _reject("fake_recall_attribution", "V12_ATTRIBUTION_FORCED_EXIT",
            lambda: verify_attribution(short_close.model_copy(update={"exit_reason": "short_recall"}),
                                       fixture.execution.account)),
        _reject("ignored_recall", "V12_ATTRIBUTION_FORCED_EXIT",
            lambda: verify_attribution(recalled.model_copy(update={"exit_reason": "session_close"}),
                                       fixture.execution.account)),
        _reject("wrong_recall_timestamp", "V12_ATTRIBUTION_EXIT_TIMELINE",
            lambda: _wrong_recall_timestamp(recalled, fixture.execution.account)),
        _reject("fake_risk_kill", "V12_ATTRIBUTION_FORCED_EXIT",
            lambda: fake_risk_kill(close, fixture.execution.account)),
        _reject("ignored_risk_kill", "V12_ATTRIBUTION_FORCED_EXIT",
            lambda: ignored_risk_kill(short_risk_kill, fixture.execution.account)),
        _reject("missing_risk_kill", "V12_ATTRIBUTION_FORCED_EXIT",
            lambda: missing_risk_kill(long_risk_kill, fixture.execution.account)),
        _reject("wrong_risk_kill_time", "V12_ATTRIBUTION_EXIT_TIMELINE",
            lambda: wrong_risk_kill_time(long_risk_kill, fixture.execution.account)),
        _reject("coordinated_fill_rehash", "V12_ATTRIBUTION_ENTRY_EVENTS",
            lambda: _coordinated_fill_mutation(first, fixture.execution.account)),
        _reject("public_replay_tamper", "V12_DERIVED_FIELD_MISMATCH",
            lambda: _public_tamper(payload, first.manifest.strategy_id,
                                   first.manifest.active_parameter_set_id)),
    )
    normative = (
        _pass("unused_future_binding_invariance",
            lambda: verify_unused_future_binding_invariance(fixture)),
        _reject("wick_breakout", "NO_SIGNAL", lambda: semantic_probe(fixture, "wick")),
        _reject("late_orb", "NO_SIGNAL", lambda: semantic_probe(fixture, "late")),
        _reject("incomplete_feature", "V12_INCOMPLETE_FEATURE",
            lambda: semantic_probe(fixture, "incomplete")),
        _reject("grid_fifth", "V12_GRID_COUNT", _fifth_grid),
        _reject("market_grid_drift", "V12_SHARED_GRID", _grid_drift),
        _reject("hidden_stop", "V12_MODEL_VALIDATION", _hidden_stop),
        _reject("llm_signal_creation", "V12_IDENTITY_COLLISION",
            lambda: verify_attribution(first.model_copy(update={"candidate": first.candidate.model_copy(
                update={"candidate_id": "llm-created"})}), fixture.execution.account)),
    )
    return (*blockers, *run_candidate_probes(first, fixture.execution.account),
        *run_borrow_cost_probes(fixture, bundle.run.trades,
        fixture.execution.account),
        *normative)


def _source_mutation(bundle: ArtifactBundle, kind: str) -> None:
    fixture = CohortFixture.model_validate(bundle.source_fixture)
    cases = list(fixture.cases)
    if kind == "case_missing":
        changed = fixture.model_copy(update={"cases": tuple(cases[:-1])})
    else:
        if kind == "borrow_missing":
            case = next(item for item in cases if item.strategy_id == "short_orb_15m"
                        and item.scenario.value == "happy")
        elif kind == "benchmark_future":
            case = next(item for item in cases if item.strategy_id == "long_relative_strength"
                        and item.scenario.value == "happy")
        else:
            case = cases[0]
        source = case.input
        if kind == "fake_ref":
            ref = source.bars[0].ref.model_copy(update={"artifact_id": "fake"})
            source = source.model_copy(update={"bars": (source.bars[0].model_copy(update={"ref": ref}), *source.bars[1:])})
        elif kind == "bar_body":
            changed_bar = source.bars[0].model_copy(update={"close": source.bars[0].close + 1})
            source = source.model_copy(update={"bars": (changed_bar, *source.bars[1:])})
        elif kind == "observation":
            changed_bar = source.bars[0].model_copy(
                update={"observed_at": source.bars[0].observed_at + timedelta(seconds=1)})
            source = source.model_copy(update={"bars": (changed_bar, *source.bars[1:])})
        elif kind == "source_body":
            ref = source.bars[0].source_ref.model_copy(update={"artifact_id": "fake-source"})
            changed_bar = source.bars[0].model_copy(update={"source_ref": ref})
            source = source.model_copy(update={"bars": (changed_bar, *source.bars[1:])})
        elif kind == "adjustment":
            source = source.model_copy(update={"adjustment_factor": source.adjustment_factor + 1})
        elif kind == "benchmark_body":
            changed_bar = source.benchmark_bars[0].model_copy(
                update={"volume": source.benchmark_bars[0].volume + 1})
            source = source.model_copy(update={"benchmark_bars":
                (changed_bar, *source.benchmark_bars[1:])})
        elif kind == "p60_slot":
            history = {key: tuple(item.model_copy(update={"minute_slot": 999}) for item in values)
                       for key, values in source.historical.items()}
            source = source.model_copy(update={"historical": history})
        elif kind == "benchmark_future":
            future = source.benchmark_bars[-1].model_copy(update={"end": source.bars[-1].end
                + timedelta(minutes=5)})
            source = source.model_copy(update={"benchmark_bars": (*source.benchmark_bars[:-1], future)})
        else:
            source = source.model_copy(update={"borrow": None})
        index = cases.index(case)
        cases[index] = case.model_copy(update={"input": source})
        changed = fixture.model_copy(update={"cases": tuple(cases)})
    from .build import build_fixture
    _ = build_fixture(changed.model_dump(mode="json"))


def _fifth_grid() -> None:
    from .models import ParameterSet
    from .registry import REGISTRY, validate_registry
    first = REGISTRY[0]
    fifth = ParameterSet(parameter_set_id="L15_E", values={"b": Decimal(0), "r": Decimal(1)})
    validate_registry((first.model_copy(update={"parameter_sets": (*first.parameter_sets, fifth)}),
                       *REGISTRY[1:]))


def _grid_drift() -> None:
    from .registry import REGISTRY, validate_registry
    first = REGISTRY[0]
    changed = first.parameter_sets[0].model_copy(update={"values": {"b": 1, "r": 1}})
    validate_registry((first.model_copy(update={"parameter_sets": (changed, *first.parameter_sets[1:])}),
                       *REGISTRY[1:]))


def _hidden_stop() -> None:
    from .models import StrategySpec
    from .registry import REGISTRY
    _ = StrategySpec.model_validate({**REGISTRY[0].model_dump(mode="python"), "hidden_stop": "1"})


def _duplicate(bundle: ArtifactBundle) -> None:
    if len(bundle.run.emission_state.emitted_keys) != 60:
        raise V12ContractError("V12_DUPLICATE_SESSION", "emission inventory")
    trade = bundle.run.trades[0]
    fixture = CohortFixture.model_validate(bundle.source_fixture)
    case = next(item for item in fixture.cases
                if item.strategy_id == trade.candidate.strategy_id
                and item.scenario.value == "happy")
    from .registry import strategy
    spec = strategy(trade.candidate.strategy_id)
    parameters = next(item for item in spec.parameter_sets
                      if item.parameter_set_id == trade.candidate.parameter_set_id)
    from .stream import evaluate_stream
    result, state = evaluate_stream(case, spec, parameters, bundle.run.emission_state)
    if result.result_code != "DUPLICATE_SESSION_NO_OP" or state != bundle.run.emission_state:
        raise V12ContractError("V12_PROBE_FAILED", "stored emission replay")
    raise V12ContractError("V12_DUPLICATE_SESSION", "stored emission no-op")


def _event_mutation(trade: TradeAttribution, account: Account) -> None:
    first = trade.events[0]
    events = (first.model_copy(update={"payload": {**first.payload, "decision_id": "mutated"}}),
              *trade.events[1:])
    verify_attribution(trade.model_copy(update={"events": events}), account)


def _wrong_recall_timestamp(trade: TradeAttribution, account: Account) -> None:
    recalled_at = trade.borrow.recalled_at
    if recalled_at is None:
        raise V12ContractError("V12_PROBE_FAILED", "recall missing")
    changed = trade.model_copy(update={"borrow": trade.borrow.model_copy(
        update={"recalled_at": recalled_at + timedelta(minutes=1)})})
    verify_attribution(changed, account)


def _coordinated_fill_mutation(trade: TradeAttribution, account: Account) -> None:
    from src.v11.ledger import append_event
    events = ()
    for event in trade.events:
        payload = dict(event.payload)
        if payload.get("semantic_key") == "fill":
            payload["quantity"] = trade.fill.filled_quantity + 1
        events = append_event(events, event.event_type, event.entity_id, event.occurred_at,
            payload, event.experiment_manifest_hash)
    from src.v11.canonical import canonical_hash, model_json
    event_hash = canonical_hash(canonical_json([model_json(item) for item in events]).decode())
    changed = trade.model_copy(update={"events": events, "event_bytes_hash": event_hash,
        "ledger_hash": "sha256:pending"})
    changed = changed.model_copy(update={"ledger_hash": canonical_hash(
        changed.model_dump(mode="json", exclude={"ledger_hash"}))})
    verify_attribution(changed, account)


def _public_tamper(payload: bytes, strategy_id: str, parameter_set_id: str) -> None:
    from src.v11.canonical import model_json
    value = model_json(verify_bundle(payload))
    match value:  # noqa: MATCH_OK - malformed JSON is rejected as a typed contract error
        case {"run": {"trades": [dict() as first, *_]}}:
            first["ledger_hash"] = "sha256:tampered"
        case _:
            raise V12ContractError("V12_BUNDLE_MALFORMED", "trade")
    from src.v11.canonical import canonical_hash
    value["bundle_hash"] = canonical_hash({key: item for key, item in value.items() if key != "bundle_hash"})
    _ = replay(canonical_json(value), strategy_id, parameter_set_id)
