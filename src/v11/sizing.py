from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from statistics import median

from .canonical import decimal_value, money
from .models import Account


def causal_quantity(
    account: Account, reference_price: str, historical_turnovers: tuple[str, ...]
) -> tuple[int, str]:
    if len(historical_turnovers) != 20:
        return 0, "0"
    target = decimal_value(account.prior_close_nav) * Decimal("0.02")
    liquidity_cap = median(decimal_value(item) for item in historical_turnovers) * Decimal("0.05")
    capped = min(target, liquidity_cap)
    quantity = int((capped / decimal_value(reference_price)).to_integral_value(rounding=ROUND_DOWN))
    return quantity, money(Decimal(quantity) * decimal_value(reference_price))
