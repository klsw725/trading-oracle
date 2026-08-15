from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from src.v11.canonical import canonical_hash, model_json, money
from src.v11.costs import execution_costs
from src.v11.fills import simulate_fill, verify_fill
from src.v11.identity import intent_id
from src.v11.ledger import append_event, verify_chain
from src.v11.models import (
    Account,
    Decision,
    EventType,
    LedgerEvent,
    Market,
    OrderAction,
    Position,
    RiskResult,
    Side,
)
from src.v11.risk import check_risk
from src.v4.models import JsonValue
from src.v13.events import LegRecord, append_timeline, record_leg, record_rejected
from src.v13.models import V13ContractError
from src.v13.prd03_models import (
    IncumbentBinding,
    IncumbentSeed,
    SwitchExecution,
    SwitchResult,
    SwitchState,
    SwitchTimelineEvent,
)


def bind_incumbent(seed: IncumbentSeed) -> IncumbentBinding:
    position_hash = canonical_hash(model_json(seed.position))
    body: JsonValue = {"market": seed.regular_session_id.split(":", 1)[0],
        "regular_session_id": seed.regular_session_id, "position_hash": position_hash,
        "candidate_id": seed.candidate_id, "strategy_id": seed.strategy_id,
        "entry_at": seed.entry_at.isoformat(),
        "composite_score": money(seed.composite_score)}
    return IncumbentBinding(market=_market_for_session(seed.regular_session_id),
        regular_session_id=seed.regular_session_id, position_hash=position_hash,
        candidate_id=seed.candidate_id, strategy_id=seed.strategy_id,
        entry_at=seed.entry_at, composite_score=seed.composite_score,
        binding_hash=canonical_hash(body))


def following_minute(at: datetime) -> datetime:
    utc = at.astimezone(timezone.utc)
    return utc.replace(second=0, microsecond=0) + timedelta(minutes=1)


def execute_switch(execution: SwitchExecution) -> SwitchResult:
    _verify_binding(execution)
    challenger = execution.challenger
    if execution.evaluated_at - execution.binding.entry_at < timedelta(minutes=15):
        return _result(execution, "held", "HOLD_PERIOD", None, None,
            execution.incumbent, None, "0", "0", None, (), ())
    if challenger.composite_score - execution.binding.composite_score < Decimal("0.10"):
        return _result(execution, "held", "INSUFFICIENT_IMPROVEMENT", None, None,
            execution.incumbent, None, "0", "0", None, (), ())
    timeline = append_timeline((), SwitchState.INCUMBENT,
        execution.evaluated_at, "SWITCH_ELIGIBLE")
    exit_target = following_minute(execution.evaluated_at)
    timeline = append_timeline(timeline, SwitchState.EXIT_PENDING,
        execution.evaluated_at, "EXIT_SCHEDULED")
    if execution.exit_execution_at != exit_target:
        timeline = append_timeline(timeline, SwitchState.TERMINAL,
            exit_target, "EXIT_BOUNDARY_MISSED")
        return _result(execution, "residual_incumbent", "EXIT_BOUNDARY_MISSED",
            exit_target, None, execution.incumbent, None, "0", "0", None,
            timeline, ())
    exit_decision = _decision(execution, "exit", execution.incumbent.side,
        execution.binding.candidate_id, execution.binding.strategy_id, exit_target)
    exit_action = OrderAction.SELL if execution.incumbent.side is Side.LONG else OrderAction.COVER
    exit_fill = simulate_fill(intent_id(exit_decision), execution.account.market,
        execution.incumbent.side, execution.incumbent.quantity,
        execution.exit_target_volume, execution.incumbent.mark_price, exit_target,
        execution.cost_policy, exit_action)
    verify_fill(exit_fill, execution.exit_target_volume)
    residual_quantity = execution.incumbent.quantity - exit_fill.filled_quantity
    residual = execution.incumbent.model_copy(update={"quantity": residual_quantity}) \
        if residual_quantity else None
    ledger = record_leg(LegRecord(events=(), decision=exit_decision, fill=exit_fill,
        resulting_position=residual, recorded_at=exit_target,
        manifest_hash=execution.manifest_hash))
    if residual is not None:
        timeline = append_timeline(timeline, SwitchState.TERMINAL,
            exit_target, "EXIT_INCOMPLETE")
        verify_chain(ledger)
        return _result(execution, "residual_incumbent", "EXIT_INCOMPLETE",
            exit_target, None, residual, None, exit_fill.costs.total, "0", None,
            timeline, ledger)
    exit_entity = exit_fill.intent_id
    ledger = append_event(ledger, EventType.RECONCILED, exit_entity, exit_target,
        {"flat": True, "semantic_key": "switch_exit_reconciled"},
        execution.manifest_hash)
    timeline = append_timeline(timeline, SwitchState.EXIT_RECONCILED_FLAT,
        exit_target, "EXIT_RECONCILED")
    entry_target = following_minute(exit_target)
    timeline = append_timeline(timeline, SwitchState.ENTRY_PENDING,
        exit_target, "ENTRY_SCHEDULED")
    if execution.entry_execution_at != entry_target:
        timeline = append_timeline(timeline, SwitchState.TERMINAL,
            entry_target, "ENTRY_BOUNDARY_MISSED")
        verify_chain(ledger)
        return _result(execution, "flat", "ENTRY_BOUNDARY_MISSED", exit_target,
            entry_target, None, None, exit_fill.costs.total, "0", None,
            timeline, ledger)
    flat_account = _flat_account(execution, exit_fill.costs.total)
    entry_decision = _decision(execution, "entry", challenger.evidence.side,
        challenger.evidence.candidate_id, challenger.evidence.strategy_id, entry_target)
    entry_action = OrderAction.BUY if challenger.evidence.side is Side.LONG else OrderAction.SHORT
    expected = execution_costs(execution.cost_policy, execution.account.market,
        entry_action, money(Decimal(challenger.evidence.target_quantity)
            * challenger.evidence.reference_price))
    risk = check_risk(flat_account, entry_decision,
        challenger.evidence.target_quantity, money(challenger.evidence.reference_price),
        challenger.evidence.candidate_returns or None, execution.existing_returns,
        challenger.evidence.gates,
        expected.total)
    if risk.state == "blocked":
        ledger = record_rejected(ledger, entry_decision, entry_target,
            execution.manifest_hash)
        timeline = append_timeline(timeline, SwitchState.TERMINAL,
            entry_target, "ENTRY_RISK_REJECTED")
        verify_chain(ledger)
        return _result(execution, "flat", "ENTRY_RISK_REJECTED", exit_target,
            entry_target, None, None, exit_fill.costs.total, "0", risk,
            timeline, ledger)
    entry_fill = simulate_fill(intent_id(entry_decision), execution.account.market,
        challenger.evidence.side, challenger.evidence.target_quantity,
        execution.entry_target_volume, money(challenger.evidence.reference_price),
        entry_target, execution.cost_policy, entry_action)
    verify_fill(entry_fill, execution.entry_target_volume)
    if entry_fill.filled_quantity == 0:
        ledger = record_leg(LegRecord(events=ledger, decision=entry_decision,
            fill=entry_fill, resulting_position=None, recorded_at=entry_target,
            manifest_hash=execution.manifest_hash))
        timeline = append_timeline(timeline, SwitchState.TERMINAL,
            entry_target, "ENTRY_UNFILLED")
        verify_chain(ledger)
        return _result(execution, "flat", "ENTRY_UNFILLED", exit_target,
            entry_target, None, None, exit_fill.costs.total,
            entry_fill.costs.total, risk, timeline, ledger)
    position = Position(symbol=challenger.evidence.symbol,
        side=challenger.evidence.side, sector=challenger.evidence.sector,
        quantity=entry_fill.filled_quantity,
        mark_price=money(challenger.evidence.reference_price))
    ledger = record_leg(LegRecord(events=ledger, decision=entry_decision,
        fill=entry_fill, resulting_position=position, recorded_at=entry_target,
        manifest_hash=execution.manifest_hash))
    timeline = append_timeline(timeline, SwitchState.TERMINAL,
        entry_target, "SWITCH_COMPLETE")
    verify_chain(ledger)
    return _result(execution, "challenger", "SWITCH_COMPLETE", exit_target,
        entry_target, None, position, exit_fill.costs.total,
        entry_fill.costs.total, risk, timeline, ledger)


def _verify_binding(execution: SwitchExecution) -> None:
    expected = bind_incumbent(IncumbentSeed(position=execution.incumbent,
        regular_session_id=execution.regular_session_id,
        candidate_id=execution.binding.candidate_id,
        strategy_id=execution.binding.strategy_id,
        entry_at=execution.binding.entry_at,
        composite_score=execution.binding.composite_score))
    reservation_ids = {str(item.intent_id) for item in execution.account.reservations}
    released_ids = set(execution.released_reservation_ids)
    if (expected != execution.binding
            or execution.account.market is not execution.binding.market
            or execution.account.positions.count(execution.incumbent) != 1
            or len(released_ids) != len(execution.released_reservation_ids)
            or not released_ids <= reservation_ids):
        raise V13ContractError("V13_INCUMBENT_BINDING", execution.incumbent.symbol)


def _market_for_session(session_id: str) -> Market:
    try:
        return Market(session_id.split(":", 1)[0])
    except ValueError as error:
        raise V13ContractError("V13_SESSION_ID", session_id) from error


def _decision(execution: SwitchExecution, leg: str, side: Side,
              candidate_id: str, strategy_id: str, at: datetime) -> Decision:
    evidence = execution.challenger.evidence
    return Decision(decision_id=f"v13:switch:{leg}:{execution.binding.binding_hash[7:27]}",
        candidate_id=candidate_id, router_decision_id=execution.manifest_hash,
        strategy_id=strategy_id, strategy_version=evidence.strategy_version,
        market=execution.account.market, symbol=evidence.symbol, sector=evidence.sector,
        side=side, action="open", cutoff=at, watermark_at=at,
        decision_ready_at=at, deterministic_score=money(evidence.deterministic_score))


def _flat_account(execution: SwitchExecution, exit_cost: str) -> Account:
    proceeds = Decimal(execution.incumbent.quantity) * Decimal(execution.incumbent.mark_price)
    cash = Decimal(execution.account.cash)
    cash += proceeds if execution.incumbent.side is Side.LONG else -proceeds
    positions = tuple(item for item in execution.account.positions
        if item != execution.incumbent)
    released_ids = set(execution.released_reservation_ids)
    reservations = tuple(item for item in execution.account.reservations
        if str(item.intent_id) not in released_ids)
    return execution.account.model_copy(update={"cash": money(cash - Decimal(exit_cost)),
        "positions": positions, "reservations": reservations})


def _result(
    execution: SwitchExecution,
    state: Literal["held", "residual_incumbent", "flat", "challenger"],
    reason: str,
    exit_target: datetime | None,
    entry_target: datetime | None,
    residual: Position | None,
    challenger: Position | None,
    exit_cost: str,
    entry_cost: str,
    risk: RiskResult | None,
    timeline: tuple[SwitchTimelineEvent, ...],
    ledger: tuple[LedgerEvent, ...],
) -> SwitchResult:
    body: JsonValue = {"binding_hash": execution.binding.binding_hash, "state": state,
        "reason_code": reason, "timeline": [model_json(item) for item in timeline],
        "ledger_tail": ledger[-1].event_hash if ledger else None}
    return SwitchResult(state=state, reason_code=reason,
        binding_hash=execution.binding.binding_hash, exit_target_at=exit_target,
        entry_target_at=entry_target, residual_incumbent=residual,
        challenger_position=challenger, exit_cost=exit_cost, entry_cost=entry_cost,
        entry_risk=risk, timeline=timeline, ledger_events=ledger,
        result_hash=canonical_hash(body))
