from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.v4.models import JsonValue

from .ledger import append_event, register_intent
from .costs import execution_costs
from .models import CostPolicy, Decision, EventType, Fill, LedgerEvent, Market, OrderAction, Position, Side


def record_fill(events: tuple[LedgerEvent, ...], decision: Decision, fill: Fill,
                position: Position, at: datetime, manifest: str) -> tuple[LedgerEvent, ...]:
    events, _ = register_intent(events, decision, at, manifest)
    entity = fill.intent_id
    events = append_event(events, EventType.RISK_CHECKED, entity, at,
        {"accepted": True, "semantic_key": "risk"}, manifest)
    if fill.filled_quantity == 0:
        return append_event(events, EventType.ORDER_CANCELLED, entity, at,
            {"quantity": fill.cancelled_quantity, "semantic_key": "zero_fill_cancel"}, manifest)
    sequence: tuple[tuple[EventType, dict[str, JsonValue]], ...] = (
        (EventType.ORDER_ACCEPTED, {"quantity": fill.requested_quantity, "semantic_key": "accepted"}),
        (EventType.FILL_PARTIAL if fill.cancelled_quantity else EventType.FILL_COMPLETE,
         {"quantity": fill.filled_quantity, "semantic_key": "fill"}),
        (EventType.POSITION_UPDATED, {"cash_delta": _cash_delta(fill), "symbol": position.symbol,
            "side": position.side.value, "sector": position.sector, "quantity": position.quantity,
            "mark_price": position.mark_price, "semantic_key": "position"}),
        (EventType.COST_ACCRUED, {"total": fill.costs.total, "semantic_key": "cost"}))
    for kind, payload in sequence:
        events = append_event(events, kind, entity, at, payload, manifest)
    if fill.cancelled_quantity:
        events = append_event(events, EventType.ORDER_CANCELLED, entity, at,
            {"quantity": fill.cancelled_quantity, "semantic_key": "remainder_cancel"}, manifest)
    return events


def record_forced_exit(events: tuple[LedgerEvent, ...], entity: str, position: Position,
                       at: datetime, reason: str, manifest: str, policy: CostPolicy,
                       market: Market, borrow_fee: str = "0") -> tuple[LedgerEvent, ...]:
    events = append_event(events, EventType.SIGNAL_OBSERVED, entity, at,
        {"reason": reason, "semantic_key": f"{reason}_signal"}, manifest)
    events = append_event(events, EventType.ORDER_INTENDED, entity, at,
        {"forced_exit": True, "semantic_key": f"{reason}_intent"}, manifest)
    events = append_event(events, EventType.RISK_CHECKED, entity, at,
        {"risk_reducing": True, "semantic_key": f"{reason}_risk"}, manifest)
    events = append_event(events, EventType.ORDER_ACCEPTED, entity, at,
        {"quantity": position.quantity, "semantic_key": f"{reason}_accepted"}, manifest)
    events = append_event(events, EventType.FILL_COMPLETE, entity, at,
        {"quantity": position.quantity, "semantic_key": f"{reason}_fill"}, manifest)
    notional = Decimal(position.quantity) * Decimal(position.mark_price)
    action = OrderAction.SELL if position.side is Side.LONG else OrderAction.COVER
    cash_delta = notional if action is OrderAction.SELL else -notional
    costs = execution_costs(policy, market, action, str(notional))
    events = append_event(events, EventType.POSITION_UPDATED, entity, at,
        {"cash_delta": str(cash_delta), "symbol": position.symbol, "side": position.side.value,
         "sector": position.sector, "quantity": 0, "mark_price": position.mark_price,
         "semantic_key": f"{reason}_position"}, manifest)
    total_cost = Decimal(costs.total) + Decimal(borrow_fee)
    events = append_event(events, EventType.COST_ACCRUED, entity, at,
        {"total": str(total_cost), "borrow_fee": borrow_fee, "action": action.value,
         "semantic_key": f"{reason}_cost"}, manifest)
    events = append_event(events, EventType.RECONCILED, entity, at,
        {"halted": reason == "daily_loss", "halt_kind": "daily_loss" if reason == "daily_loss" else "none",
         "semantic_key": f"{reason}_reconciled"}, manifest)
    return events


def _cash_delta(fill: Fill) -> str:
    value = Decimal(fill.filled_quantity) * Decimal(fill.price)
    return str(-value if fill.side.value == "long" else value)
