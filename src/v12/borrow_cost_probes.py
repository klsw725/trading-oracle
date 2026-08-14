from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from src.v4.models import canonical_json
from src.v11.canonical import canonical_hash, model_json
from src.v11.ledger import append_event
from src.v11.models import Account

from .artifacts import TradeAttribution
from .artifacts import EmissionState
from .integrity import verify_attribution
from .models import CohortFixture, Scenario, V12ContractError
from .registry import strategy
from .shadow import execute, make_execution_feasible
from .strategy_input_fixture import bind_cases, build_source_fixture
from .stream import evaluate_stream


type Probe = tuple[str, str]


def run_borrow_cost_probes(fixture: CohortFixture, trades: tuple[TradeAttribution, ...],
                           account: Account) -> tuple[Probe, ...]:
    short_trade = require_short_trade(trades)
    short_risk = next(item for item in trades
        if item.candidate.side.value == "short" and item.exit_reason == "risk_kill")
    baseline = _borrow_fee(short_risk)
    return ((_changed("borrow_annual_fee_resealed", baseline, fixture, short_risk, "annual_fee")),
        _changed("borrow_notional_resealed", baseline, fixture, short_risk, "notional"),
        _changed("borrow_holding_period_resealed", baseline, fixture, short_risk, "holding"),
        _reject("borrow_annual_fee_tamper", "V12_ATTRIBUTION_BORROW_COST",
        lambda: tamper_annual_fee(short_trade, account)),
        _reject("borrow_holding_period_tamper", "V12_ATTRIBUTION_FORCED_EXIT",
            lambda: tamper_holding_period(short_risk, account)),
        _reject("borrow_output_tamper", "V12_ATTRIBUTION_BORROW_COST",
            lambda: tamper_borrow_output(short_trade, account)))


def _changed(probe_id: str, baseline: str, fixture: CohortFixture,
             baseline_trade: TradeAttribution, kind: str) -> Probe:
    cases = list(fixture.cases)
    case = next(item for item in cases if item.strategy_id == "short_orb_15m"
        and item.scenario is Scenario.HAPPY)
    case_index = cases.index(case)
    source = case.input
    if source.borrow is None:
        raise V12ContractError("V12_PROBE_FAILED", f"{probe_id}:borrow")
    if kind == "annual_fee":
        source = source.model_copy(update={"borrow": source.borrow.model_copy(
            update={"annual_fee": source.borrow.annual_fee * Decimal(2)})})
    elif kind == "notional":
        bindings = tuple(binding.model_copy(update={"execution_snapshot":
            binding.execution_snapshot.model_copy(update={
                "volume": binding.execution_snapshot.volume * 2})})
            for binding in source.execution_bindings)
        source = source.model_copy(update={"execution_bindings": bindings})
    else:
        source = source.model_copy(update={"risk_kill_at": source.risk_kill_at + timedelta(days=2)
            if source.risk_kill_at is not None else None,
            "regular_close": source.regular_close + timedelta(days=3),
            "borrow": source.borrow.model_copy(update={
                "effective_until": source.borrow.effective_until + timedelta(days=4)})})
    cases[case_index] = case.model_copy(update={"input": source})
    raw_cases = tuple(cases)
    source_fixture = build_source_fixture(tuple(
        (f"{item.strategy_id}:{item.scenario.value}", item.input) for item in raw_cases))
    bound, _ = bind_cases(raw_cases, source_fixture)
    changed_case = bound[case_index]
    spec = strategy(changed_case.strategy_id)
    parameters = next(item for item in spec.parameter_sets
        if item.parameter_set_id == baseline_trade.candidate.parameter_set_id)
    result, _ = evaluate_stream(changed_case, spec, parameters,
        EmissionState(emitted_keys=(), last_cutoffs={}, last_gate_states={}))
    if result.candidate is None or result.bound_input is None:
        raise V12ContractError("V12_PROBE_FAILED", f"{probe_id}:candidate")
    feasible, _, _ = make_execution_feasible(result.candidate, result.bound_input,
        fixture.execution, baseline_trade.manifest)
    observed = _borrow_fee(execute(feasible, result.bound_input, fixture.execution,
        baseline_trade.manifest))
    if observed == baseline:
        raise V12ContractError("V12_PROBE_FAILED", f"{probe_id}:unchanged")
    return probe_id, observed


def _borrow_fee(trade: TradeAttribution) -> str:
    event = next(item for item in trade.events
        if item.payload.get("semantic_key") == f"{trade.exit_reason}_cost")
    value = event.payload.get("borrow_fee")
    if not isinstance(value, str):
        raise V12ContractError("V12_PROBE_FAILED", "borrow fee missing")
    return value


def _reject(probe_id: str, code: str, operation: Callable[[], None]) -> Probe:
    observed = "none"
    try:
        operation()
    except V12ContractError as error:
        observed = error.code
    if observed != code:
        raise V12ContractError("V12_PROBE_FAILED", f"{probe_id}:{observed}")
    return probe_id, code


def tamper_annual_fee(trade: TradeAttribution, account: Account) -> None:
    changed = trade.model_copy(update={"borrow": trade.borrow.model_copy(
        update={"annual_fee": trade.borrow.annual_fee * Decimal(2)})})
    verify_attribution(changed, account)


def tamper_holding_period(trade: TradeAttribution, account: Account) -> None:
    verify_attribution(trade.model_copy(update={
        "risk_kill_at": trade.risk_kill_at + timedelta(days=1)
            if trade.risk_kill_at is not None else None}), account)


def tamper_borrow_output(trade: TradeAttribution, account: Account) -> None:
    events = ()
    for event in trade.events:
        payload = dict(event.payload)
        if payload.get("semantic_key") == f"{trade.exit_reason}_cost":
            payload["borrow_fee"] = "999"
        events = append_event(events, event.event_type, event.entity_id, event.occurred_at,
            payload, event.experiment_manifest_hash)
    event_hash = canonical_hash(canonical_json([model_json(item) for item in events]).decode())
    changed = trade.model_copy(update={"events": events, "event_bytes_hash": event_hash,
        "ledger_hash": "sha256:pending"})
    changed = changed.model_copy(update={"ledger_hash": canonical_hash(
        changed.model_dump(mode="json", exclude={"ledger_hash"}))})
    verify_attribution(changed, account)


def require_short_trade(trades: tuple[TradeAttribution, ...]) -> TradeAttribution:
    try:
        return next(item for item in trades if item.candidate.side.value == "short")
    except StopIteration as error:
        raise V12ContractError("V12_PROBE_FAILED", "short trade missing") from error
