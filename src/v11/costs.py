from __future__ import annotations

from decimal import Decimal

from src.v4.models import JsonValue
from .canonical import canonical_hash, decimal_value, money
from .models import CostBreakdown, CostPolicy, Market, OrderAction, V11ContractError


def freeze_policy(policy: CostPolicy, session: str) -> CostPolicy:
    if not policy.approved or policy.effective_session > session or not policy.reviewer:
        raise V11ContractError("V11_COST_POLICY_UNAPPROVED", policy.version)
    body: JsonValue = policy.model_dump(mode="json", exclude={"policy_hash"})
    expected = canonical_hash(body)
    if policy.policy_hash not in {"sha256:pending", expected}:
        raise V11ContractError("V11_COST_POLICY_HASH", policy.version)
    return policy.model_copy(update={"policy_hash": expected})


def execution_costs(policy: CostPolicy, market: Market, action: OrderAction,
                    notional: str, stress: bool = False) -> CostBreakdown:
    value = decimal_value(notional)
    variable_multiplier = Decimal(2) if stress else Decimal(1)
    commission = value * decimal_value(policy.commission_rate)
    tax = value * decimal_value(policy.kr_sell_tax_rate) if market is Market.KR and action is OrderAction.SELL else Decimal(0)
    spread = value * decimal_value(policy.spread_rate) * variable_multiplier
    slippage = value * decimal_value(policy.slippage_rate) * variable_multiplier
    participation = value * decimal_value(policy.participation_rate) * variable_multiplier
    borrow = value * decimal_value(policy.borrow_rate) * variable_multiplier if action is OrderAction.SHORT else Decimal(0)
    locate = value * decimal_value(policy.locate_rate) * variable_multiplier if action is OrderAction.SHORT else Decimal(0)
    total = commission + tax + spread + slippage + participation + borrow + locate
    return CostBreakdown(commission=money(commission), tax=money(tax), spread=money(spread),
        slippage=money(slippage), participation=money(participation), borrow=money(borrow),
        locate=money(locate), total=money(total))


def verify_stress(baseline: CostBreakdown, stressed: CostBreakdown) -> None:
    if baseline.commission != stressed.commission or baseline.tax != stressed.tax:
        raise V11ContractError("V11_FIXED_COST_STRESSED", "commission_or_tax")
    pairs = (("spread", baseline.spread, stressed.spread),
        ("slippage", baseline.slippage, stressed.slippage),
        ("participation", baseline.participation, stressed.participation),
        ("borrow", baseline.borrow, stressed.borrow), ("locate", baseline.locate, stressed.locate))
    for field, base_value, stressed_value in pairs:
        if decimal_value(stressed_value) != decimal_value(base_value) * 2:
            raise V11ContractError("V11_VARIABLE_COST_STRESS", field)
