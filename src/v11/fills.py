from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .canonical import money
from .costs import execution_costs
from .liquidity import fill_cap
from .models import CostPolicy, Fill, IntentId, Market, OrderAction, Side, V11ContractError


def simulate_fill(intent_id: IntentId, market: Market, side: Side, requested: int,
                  target_volume: int, price: str, target_at: datetime, policy: CostPolicy,
                  action: OrderAction) -> Fill:
    maximum = fill_cap(target_volume)
    filled = min(requested, maximum)
    cancelled = requested - filled
    if filled == 0:
        state = "cancelled"
    elif cancelled:
        state = "partial"
    else:
        state = "complete"
    notional = money(Decimal(filled) * Decimal(price))
    return Fill(intent_id=intent_id, target_at=target_at, side=side, action=action,
        requested_quantity=requested, filled_quantity=filled, cancelled_quantity=cancelled,
        price=price, state=state, costs=execution_costs(policy, market, action, notional))


def verify_fill(fill: Fill, target_volume: int, carried: bool = False) -> None:
    if fill.filled_quantity > fill_cap(target_volume):
        raise V11ContractError("V11_PARTICIPATION_LIMIT", fill.intent_id)
    if carried:
        raise V11ContractError("V11_STALE_EXECUTION", fill.intent_id)
