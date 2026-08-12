from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.v4.models import JsonValue

from .canonical import canonical_hash, model_json
from .costs import freeze_policy
from .daily_loss import DailyLossHaltRequest
from .decisions import target_minute, verify_intent_timing
from .execution_ledger import record_fill, record_forced_exit
from .execution_snapshots import load_snapshot_approval, verify_snapshot
from .fills import simulate_fill
from .fixture_models import Prd02Fixture
from .identity import intent_id
from .ledger import append_event, register_intent
from .market_inputs import load_v10_market_input
from .models import Account, EventType, LedgerEvent, Market, OrderAction, Position, Side, V11ContractError
from .replay import replay
from .reservations import release
from .session_exit import entry_allowed, overnight
from .shorts import BorrowSnapshot, borrow_cost, recall_exit, short_eligible


def build_prd02(fixture: Prd02Fixture, prd01: tuple[JsonValue, ...]) -> tuple[JsonValue, ...]:
    accounts = {Market.KR: Account.model_validate(prd01[0]),
                Market.US: Account.model_validate(prd01[1])}
    market_input = load_v10_market_input(fixture.v10_fixtures)
    halt_request = DailyLossHaltRequest.model_validate(prd01[3])
    if not halt_request.cancel_pending:
        raise V11ContractError("V11_DAILY_LOSS_REQUEST_MISSING", fixture.prd01_fixture)
    policy = freeze_policy(fixture.cost_policy, fixture.executions[0].decision.cutoff.date().isoformat())
    borrow = BorrowSnapshot.model_validate(fixture.borrow.model_dump())
    approval = load_snapshot_approval()
    executions: list[JsonValue] = []
    fills: list[JsonValue] = []
    forced_exits: list[JsonValue] = []
    ledgers: dict[Market, tuple[LedgerEvent, ...]] = {Market.KR: (), Market.US: ()}
    manifest = canonical_hash({"policy": model_json(policy), "market_input": model_json(market_input),
                               "snapshot_approval_hash": approval.artifact_hash})
    for item in sorted(fixture.executions, key=lambda execution: target_minute(execution.decision)):
        decision = item.decision
        target_at = target_minute(decision)
        verify_snapshot(item.snapshot, set(market_input.provenance_refs), approval)
        if (item.snapshot.market is not decision.market or item.snapshot.symbol != decision.symbol
                or item.snapshot.interval_start != target_at):
            raise V11ContractError("V11_TARGET_SNAPSHOT_MISSING", decision.decision_id)
        if decision.market is Market.KR and decision.symbol == market_input.symbol:
            decision = decision.model_copy(update={"market_input_hash": market_input.input_hash})
        try:
            verify_intent_timing(decision, item.intent_recorded_at, target_at)
            timely = True
        except V11ContractError:
            timely = False
        is_halt_market = decision.market is halt_request.market
        pending_at_halt = is_halt_market and item.intent_recorded_at < halt_request.observed_at <= target_at
        halted = is_halt_market and item.intent_recorded_at >= halt_request.observed_at
        if pending_at_halt:
            events, _ = register_intent(ledgers[decision.market], decision,
                                        item.intent_recorded_at, manifest)
            entity = intent_id(decision)
            events = append_event(events, EventType.RISK_CHECKED, entity, item.intent_recorded_at,
                                  {"accepted": True, "semantic_key": "risk"}, manifest)
            events = append_event(events, EventType.ORDER_ACCEPTED, entity, item.intent_recorded_at,
                                  {"quantity": item.requested_quantity,
                                   "semantic_key": "accepted"}, manifest)
            events = _activate_halt(events, halt_request, manifest)
            ledgers[decision.market] = append_event(events, EventType.ORDER_CANCELLED, entity,
                halt_request.observed_at, {"reason": "daily_loss_halt",
                "semantic_key": "daily_halt_cancel"}, manifest)
            executions.append({"decision_id": decision.decision_id, "state": "cancelled",
                               "reason": "daily_loss_halt", "target_at": target_at.isoformat()})
            continue
        if halted:
            ledgers[decision.market] = _activate_halt(ledgers[decision.market], halt_request, manifest)
            try:
                _, _ = register_intent(ledgers[decision.market], decision,
                                       item.intent_recorded_at, manifest)
            except V11ContractError as error:
                if error.code != "V11_EXECUTION_HALTED":
                    raise
            else:
                raise V11ContractError("V11_DAILY_LOSS_HALT_NOT_ENFORCED", decision.decision_id)
            executions.append({"decision_id": decision.decision_id, "state": "blocked",
                               "reason": "daily_loss_halt"})
            continue
        allowed = entry_allowed(target_at, item.regular_close)
        short_allowed = decision.side is Side.LONG or short_eligible(
            borrow, target_at, decision.market, decision.symbol)
        if timely and allowed and short_allowed:
            fill = simulate_fill(intent_id(decision), decision.market, decision.side,
                item.requested_quantity, item.snapshot.volume, item.snapshot.open, target_at, policy,
                OrderAction.BUY if decision.side is Side.LONG else OrderAction.SHORT)
            fills.append(model_json(fill))
            position = Position(symbol=decision.symbol, side=decision.side, sector=decision.sector,
                quantity=fill.filled_quantity, mark_price=fill.price)
            ledgers[decision.market] = record_fill(ledgers[decision.market], decision, fill,
                                                   position, target_at, manifest)
            executions.append({"decision_id": decision.decision_id, "state": fill.state,
                               "target_at": target_at.isoformat()})
        else:
            executions.append({"decision_id": decision.decision_id, "state": "cancelled",
                "reason": "stale" if not timely else "market_or_short_block"})
    ledgers[halt_request.market] = _activate_halt(ledgers[halt_request.market], halt_request, manifest)
    short_execution = next(item for item in fixture.executions if item.decision.side is Side.SHORT)
    recall_at = recall_exit(borrow, short_execution.decision.watermark_at, short_execution.regular_close)
    if recall_at:
        short_state = replay(ledgers[Market.US], "100000")
        matching = tuple(item for item in short_state.positions if item.symbol == borrow.symbol)
        if matching:
            short_position = matching[0]
            holding_days = max(1, (recall_at.date() - short_execution.snapshot.interval_start.date()).days)
            accrued_borrow = borrow_cost(str(Decimal(short_position.quantity) *
                Decimal(short_position.mark_price)), borrow.annual_fee, holding_days)
            ledgers[Market.US] = record_forced_exit(ledgers[Market.US], "forced:recall", short_position,
                recall_at, "borrow_recall", manifest, policy, Market.US, accrued_borrow)
            forced_exits.append({"reason": "borrow_recall", "target_at": recall_at.isoformat(),
                "borrow_cost": accrued_borrow, "quantity": short_position.quantity})
    kr_state = replay(ledgers[Market.KR], "100000000")
    daily_position = next(iter(kr_state.positions))
    daily_entity = f"forced:daily:{daily_position.symbol}"
    ledgers[Market.KR] = record_forced_exit(ledgers[Market.KR], daily_entity, daily_position,
        fixture.daily_loss_exit_at, "daily_loss", manifest, policy, Market.KR)
    ledgers[Market.KR] = append_event(ledgers[Market.KR], EventType.SESSION_CLOSED, daily_entity,
        fixture.daily_loss_exit_at + timedelta(days=1),
        {"reset": True, "semantic_key": "daily_loss_closed"}, manifest)
    forced_exits.append({"reason": "daily_loss", "target_at": fixture.daily_loss_exit_at.isoformat(),
        "symbol": daily_position.symbol, "quantity": daily_position.quantity})
    close_at = short_execution.regular_close - timedelta(minutes=4)
    for close_position in replay(ledgers[Market.US], "100000").positions:
        ledgers[Market.US] = record_forced_exit(ledgers[Market.US],
            f"forced:close:{close_position.symbol}", close_position, close_at,
            "market_close", manifest, policy, Market.US)
        forced_exits.append({"reason": "market_close", "target_at": close_at.isoformat(),
                             "symbol": close_position.symbol, "quantity": close_position.quantity})
    close = max(item.regular_close for item in fixture.executions)
    remaining = 0 if forced_exits else sum(item.quantity for item in fixture.daily_loss_positions)
    if overnight(remaining, close, fixture.daily_loss_exit_at):
        raise V11ContractError("V11_OVERNIGHT_POSITION", str(remaining))
    states = {Market.KR: replay(ledgers[Market.KR], "100000000"),
              Market.US: replay(ledgers[Market.US], "100000")}
    if states[Market.KR].positions or states[Market.US].positions:
        raise V11ContractError("V11_OVERNIGHT_POSITION", "market state")
    for account_market, account in tuple(accounts.items()):
        for reservation in account.reservations:
            accounts[account_market] = release(accounts[account_market], reservation.intent_id,
                                               ledgers[account_market])
    ledger_json: JsonValue = {market.value: [model_json(item) for item in ledgers[market]] for market in Market}
    state_json: JsonValue = {market.value: model_json(states[market]) for market in Market}
    return (executions, fills, forced_exits, ledger_json, state_json,
            {"short_eligible": short_eligible(borrow, fixture.borrow.observed_at),
             "overnight_quantity": remaining, "cost_policy_hash": policy.policy_hash,
             "snapshot_approval_hash": approval.artifact_hash,
             "daily_loss_observed_at": halt_request.observed_at.isoformat(),
             "market_input": model_json(market_input),
             "released_accounts": [model_json(accounts[Market.KR]), model_json(accounts[Market.US])]})


def _activate_halt(events: tuple[LedgerEvent, ...], request: DailyLossHaltRequest,
                   manifest: str) -> tuple[LedgerEvent, ...]:
    if any(event.entity_id == "daily_loss_halt" for event in events):
        return events
    return append_event(events, EventType.SIGNAL_OBSERVED, "daily_loss_halt", request.observed_at,
        {"halted": True, "halt_kind": "daily_loss", "semantic_key": "daily_loss_halt"}, manifest)
