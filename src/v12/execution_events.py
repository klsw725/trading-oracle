from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from src.v11.costs import execution_costs
from src.v11.ledger import append_event
from src.v11.models import CostPolicy, EventType, LedgerEvent, Market, OrderAction, Position, Side


def record_close_exit(events: tuple[LedgerEvent, ...], entity: str, position: Position,
                      signal_at: datetime, fill_at: datetime, reason: str,
                      manifest: str, policy: CostPolicy, market: Market,
                      borrow_fee: str) -> tuple[LedgerEvent, ...]:
    events = append_event(events, EventType.SIGNAL_OBSERVED, entity, signal_at,
        {"reason": reason, "semantic_key": f"{reason}_signal"}, manifest)
    events = append_event(events, EventType.ORDER_INTENDED, entity, signal_at,
        {"forced_exit": True, "semantic_key": f"{reason}_intent"}, manifest)
    events = append_event(events, EventType.RISK_CHECKED, entity, fill_at,
        {"risk_reducing": True, "semantic_key": f"{reason}_risk"}, manifest)
    events = append_event(events, EventType.ORDER_ACCEPTED, entity, fill_at,
        {"quantity": position.quantity, "semantic_key": f"{reason}_accepted"}, manifest)
    events = append_event(events, EventType.FILL_COMPLETE, entity, fill_at,
        {"quantity": position.quantity, "price": position.mark_price,
         "semantic_key": f"{reason}_fill"}, manifest)
    notional = Decimal(position.quantity) * Decimal(position.mark_price)
    action = OrderAction.SELL if position.side is Side.LONG else OrderAction.COVER
    cash_delta = notional if action is OrderAction.SELL else -notional
    events = append_event(events, EventType.POSITION_UPDATED, entity, fill_at,
        {"cash_delta": str(cash_delta), "symbol": position.symbol,
         "side": position.side.value, "sector": position.sector, "quantity": 0,
         "mark_price": position.mark_price, "semantic_key": f"{reason}_position"}, manifest)
    costs = execution_costs(policy, market, action, str(notional))
    total = Decimal(costs.total) + Decimal(borrow_fee)
    cost_at = fill_at + timedelta(seconds=1)
    events = append_event(events, EventType.COST_ACCRUED, entity, cost_at,
        {"total": str(total), "borrow_fee": borrow_fee, "action": action.value,
         "semantic_key": f"{reason}_cost"}, manifest)
    return append_event(events, EventType.RECONCILED, entity, cost_at + timedelta(seconds=1),
        {"halted": False, "halt_kind": "none",
         "semantic_key": f"{reason}_reconciled"}, manifest)
