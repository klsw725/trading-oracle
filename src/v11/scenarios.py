from __future__ import annotations

from pathlib import Path

from src.v4.models import JsonValue

from .canonical import model_json
from .daily_loss import evaluate_daily_loss
from .fixture_models import Prd01Fixture, Prd02Fixture, Prd03Fixture, Prd04Fixture
from .halt import integrity_halt
from .identity import intent_id
from .ledger import append_event, register_intent
from .market_inputs import load_v10_market_input
from .models import EventType, ExecutionLedger, Market, V11ContractError
from .paper_boundary import verify_paper_input
from .reconciliation import reconcile
from .replay import checkpoint, replay
from .batches import evaluate_batches

def build_prd01(fixture: Prd01Fixture) -> tuple[JsonValue, ...]:
    market_input = load_v10_market_input(fixture.v10_fixtures)
    first_kr = next(item for item in fixture.cases if item.decision.market is Market.KR)
    if first_kr.decision.symbol != market_input.symbol:
        raise V11ContractError("V11_V10_INPUT_MISMATCH", first_kr.decision.decision_id)
    cases = tuple(item.model_copy(update={"decision": item.decision.model_copy(
        update={"market_input_hash": market_input.input_hash})
        if item.decision.market is Market.KR else item.decision,
        "reference_price": market_input.reference_price if item.decision.market is Market.KR
        else item.reference_price,
        "gates": item.gates.model_copy(update={"eligible": market_input.eligible})
        if item.decision.symbol == market_input.symbol else item.gates}) for item in fixture.cases)
    accounts, risk_results = evaluate_batches(cases)
    halt_request = evaluate_daily_loss(accounts[Market.KR], fixture.daily_loss_inputs)
    if halt_request is None:
        raise V11ContractError("V11_DAILY_LOSS_NOT_TRIGGERED", fixture.daily_loss_inputs.realized_pnl)
    return (model_json(accounts[Market.KR]), model_json(accounts[Market.US]),
            [model_json(item) for item in risk_results], model_json(halt_request), model_json(market_input))

def build_prd03(fixture: Prd03Fixture) -> tuple[JsonValue, ...]:
    from .models import Decision
    decision = Decision.model_validate({"decision_id": "ledger-decision", "candidate_id": "candidate",
        "router_decision_id": "router", "strategy_id": "strategy", "strategy_version": "1",
        "market": "US", "symbol": "AAPL", "sector": "technology", "side": "long",
        "action": "open", "cutoff": fixture.event_at, "watermark_at": fixture.event_at,
        "decision_ready_at": fixture.event_at, "deterministic_score": "1"})
    events, receipt = register_intent((), decision, fixture.event_at, fixture.manifest_hash)
    entity = intent_id(decision)
    sequence: tuple[tuple[EventType, dict[str, JsonValue]], ...] = (
        (EventType.RISK_CHECKED, {"accepted": True, "semantic_key": "risk"}),
        (EventType.ORDER_ACCEPTED, {"quantity": 10}),
        (EventType.FILL_PARTIAL, {"quantity": 5}),
        (EventType.POSITION_UPDATED, {"cash_delta": "-500", "symbol": "AAPL", "side": "long",
            "sector": "technology", "quantity": 5, "mark_price": "100"}),
        (EventType.COST_ACCRUED, {"total": "1"}),
        (EventType.ORDER_CANCELLED, {"quantity": 5}),
        (EventType.RECONCILED, {"halted": False}))
    for kind, payload in sequence:
        events = append_event(events, kind, entity, fixture.event_at, payload, fixture.manifest_hash)
    pending = decision.model_copy(update={"decision_id": "pending-decision",
        "candidate_id": "pending-candidate", "symbol": "MSFT"})
    events, _ = register_intent(events, pending, fixture.event_at, fixture.manifest_hash)
    saved = checkpoint(events, fixture.initial_cash, fixture.checkpoint_after)
    state = replay(events, fixture.initial_cash, saved)
    source = state.model_copy(update={"cash": fixture.source_cash})
    reconciliation = reconcile(state, source)
    halt = integrity_halt(fixture.event_at.date()) if reconciliation.execution_halt else None
    if reconciliation.execution_halt:
        for open_intent in state.open_intents:
            events = append_event(events, EventType.ORDER_CANCELLED, open_intent, fixture.event_at,
                {"reason": "reconciliation_mismatch", "semantic_key": "halt_cancel"}, fixture.manifest_hash)
        events = append_event(events, EventType.SIGNAL_OBSERVED, "execution_halt", fixture.event_at,
            {"halted": True, "halt_kind": "integrity", "semantic_key": "integrity_halt"},
            fixture.manifest_hash)
    retried, retry_receipt = register_intent(events, decision, fixture.event_at, fixture.manifest_hash)
    ledger = ExecutionLedger(initial_cash=fixture.initial_cash, checkpoint=saved, events=events,
                             source_snapshot=source)
    return (model_json(ledger), model_json(state), model_json(reconciliation),
        model_json(halt) if halt else None,
        {"first_receipt": model_json(receipt), "retry_receipt": model_json(retry_receipt),
         "retry_event_count": len(retried)})


def build_prd04(fixture: Prd04Fixture) -> tuple[JsonValue, ...]:
    from .canonical import parse_json
    from .prd02_scenario import build_prd02
    from src.v10.acceptance import build_path as build_v10_path
    from src.v10.verifier import verify_bundle as verify_v10_bundle
    from src.v4.models import canonical_json
    value: JsonValue = fixture.model_dump(mode="json")
    verify_paper_input(value)
    root = Path(__file__).resolve().parents[2]
    artifacts: list[JsonValue] = []
    prd01 = Prd01Fixture.model_validate(parse_json((root / fixture.prd01_fixture).read_bytes()))
    prd02 = Prd02Fixture.model_validate(parse_json((root / fixture.prd02_fixture).read_bytes()))
    prd03 = Prd03Fixture.model_validate(parse_json((root / fixture.prd03_fixture).read_bytes()))
    prd01_artifacts = build_prd01(prd01)
    artifacts.extend(([*prd01_artifacts], [*build_prd02(prd02, prd01_artifacts)],
                      [*build_prd03(prd03)]))
    v10_hashes: list[JsonValue] = [
        verify_v10_bundle(canonical_json(build_v10_path(root / path))).bundle_hash
        for path in fixture.v10_fixtures
    ]
    boundary: dict[str, JsonValue] = {"destination": fixture.destination, "orchestrated_prds": artifacts,
        "v10_fixture_hashes": v10_hashes,
        "broker_submit_count": 0, "live_artifact_count": 0,
        "portfolio_mutation_count": 0, "v12_plus_import_count": 0}
    return (boundary,)
