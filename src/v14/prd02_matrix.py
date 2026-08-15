from __future__ import annotations

from decimal import Decimal
from typing import Final

from src.v12.models import Market
from src.v12.registry import REGISTRY

from .contract import V14ContractError
from .router_metric_models import RouterRunDescriptors
from .selection_models import DevelopmentSelection, MarketSelection
from .series_models import CostFixture, ResearchSegment, RunDescriptor


MIXED_ID: Final = "mixed_router_vs_no_trade"
DETERMINISTIC_ID: Final = "deterministic_router_vs_no_trade"
PAIRED_ID: Final = "mixed_router_vs_deterministic"


def _base_descriptor(
    fixture: CostFixture, market: Market, segment: ResearchSegment
) -> RunDescriptor:
    matches = tuple(item for item in fixture.descriptors
        if item.market is market and item.segment is segment)
    if len(matches) != 1:
        raise V14ContractError("V14_RUN_TEMPLATE", f"{market.value}:{segment.value}")
    return matches[0]


def _market_selection(
    selection: DevelopmentSelection, market: Market
) -> MarketSelection:
    matches = tuple(item for item in selection.markets if item.market is market)
    if len(matches) != 1:
        raise V14ContractError("V14_SELECTION_MARKET", market.value)
    return matches[0]


def strategy_descriptors(
    fixture: CostFixture, selection: DevelopmentSelection
) -> tuple[RunDescriptor, ...]:
    descriptors: list[RunDescriptor] = []
    for market in Market:
        selected = _market_selection(selection, market)
        by_id = {item.strategy_id: item.selected for item in selected.strategies}
        for segment in ResearchSegment:
            base = _base_descriptor(fixture, market, segment)
            for index, spec in enumerate(REGISTRY):
                config = by_id[spec.strategy_id]
                descriptors.append(base.model_copy(update={
                    "hypothesis_id": spec.strategy_id,
                    "configuration_id": config.canonical_id,
                    "gross_base": base.gross_base + Decimal(index) / Decimal("10000000"),
                }))
    return tuple(descriptors)


def router_descriptors(
    fixture: CostFixture, selection: DevelopmentSelection
) -> tuple[RouterRunDescriptors, ...]:
    result: list[RouterRunDescriptors] = []
    for market in Market:
        selected = _market_selection(selection, market)
        policy_id = selected.router_policy.canonical_id
        for segment in ResearchSegment:
            base = _base_descriptor(fixture, market, segment)
            mixed = base.model_copy(update={"hypothesis_id": MIXED_ID,
                "configuration_id": policy_id,
                "gross_base": base.gross_base + Decimal("0.0002")})
            deterministic = base.model_copy(update={"hypothesis_id": DETERMINISTIC_ID,
                "configuration_id": "deterministic_only",
                "gross_base": base.gross_base + Decimal("0.0001")})
            paired = base.model_copy(update={"hypothesis_id": PAIRED_ID,
                "configuration_id": f"{policy_id}-minus-deterministic_only",
                "gross_base": Decimal("0.0001"),
                "gross_wave": tuple(Decimal(0) for _ in base.gross_wave),
                "traded_notional": Decimal(0)})
            result.append(RouterRunDescriptors(market=market, segment=segment,
                selected_policy_id=policy_id, mixed=mixed,
                deterministic=deterministic, paired=paired))
    return tuple(result)
