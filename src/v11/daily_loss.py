from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from src.v4.models import JsonValue

from .canonical import canonical_hash, decimal_value, money
from .models import Account, Market, StrictModel


class DailyLossHaltRequest(StrictModel):
    market: Annotated[Market, Field(strict=False)]
    loss: str
    threshold: str
    input_hash: str
    cancel_pending: bool
    liquidate_at_next_minute: bool
    observed_at: Annotated[datetime, Field(strict=False)]


class DailyLossInputs(StrictModel):
    observed_at: Annotated[datetime, Field(strict=False)]
    realized_pnl: str
    unrealized_pnl: str
    commission: str
    tax: str
    spread: str
    slippage: str
    borrow: str


def evaluate_daily_loss(account: Account, inputs: DailyLossInputs) -> DailyLossHaltRequest | None:
    prior = decimal_value(account.prior_close_nav)
    pnl = decimal_value(inputs.realized_pnl) + decimal_value(inputs.unrealized_pnl)
    costs = sum((decimal_value(item) for item in (inputs.commission, inputs.tax, inputs.spread,
                inputs.slippage, inputs.borrow)), Decimal(0))
    marked_nav = prior + pnl - costs
    loss = prior - marked_nav
    threshold = prior * Decimal("0.02")
    if loss < threshold:
        return None
    body: JsonValue = {"market": account.market.value, "prior_close_nav": account.prior_close_nav,
        "marked_nav": money(marked_nav), "inputs": inputs.model_dump(mode="json")}
    return DailyLossHaltRequest(market=account.market, loss=money(loss),
        threshold=money(threshold), input_hash=canonical_hash(body), cancel_pending=True,
        liquidate_at_next_minute=True, observed_at=inputs.observed_at)
