from __future__ import annotations

from src.v11.canonical import money
from src.v11.costs import execution_costs, verify_stress
from src.v11.models import CostBreakdown, Market as V11Market
from src.v12.models import Market

from .series_models import CostReplayInput


def _v11_market(market: Market) -> V11Market:
    return V11Market(market.value)


def cost_pair(
    request: CostReplayInput,
) -> tuple[CostBreakdown, CostBreakdown]:
    baseline = execution_costs(request.policy, _v11_market(request.market),
        request.action, money(request.notional))
    stress = execution_costs(
        request.policy, _v11_market(request.market), request.action,
        money(request.notional), stress=True
    )
    verify_stress(baseline, stress)
    return baseline, stress
