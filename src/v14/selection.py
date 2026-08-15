from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market
from src.v12.registry import REGISTRY, strategy
from src.v13.policy import policy_grid

from .contract import V14ContractError
from .selection_models import (
    DevelopmentGrid,
    DevelopmentSelection,
    DevelopmentSelectionBody,
    MarketSelection,
    MarketScoreDescriptor,
    ScoreTemplate,
    SelectionInputs,
    SelectedConfig,
    SelectionCandidate,
    StrategySelection,
)
from .tiebreak import choose


def _candidate(canonical_id: str, template: ScoreTemplate) -> SelectionCandidate:
    return SelectionCandidate(canonical_id=canonical_id,
        fold_oos_net_excess_returns=template.fold_returns,
        turnover=template.turnover)


def select_strategy(strategy_id: str, grid: DevelopmentGrid) -> SelectedConfig:
    if len(grid.candidates) > 4:
        raise V14ContractError("V14_GRID_OVERFLOW", str(len(grid.candidates)))
    allowed = {item.parameter_set_id for item in strategy(strategy_id).parameter_sets}
    observed = {item.canonical_id for item in grid.candidates}
    if not observed.issubset(allowed):
        raise V14ContractError("V14_STRATEGY_GRID_ID", str(sorted(observed - allowed)))
    return choose(grid.candidates, 4)


def select_router(grid: DevelopmentGrid) -> SelectedConfig:
    if len(grid.candidates) > 6:
        raise V14ContractError("V14_GRID_OVERFLOW", str(len(grid.candidates)))
    allowed = {item.policy_hash for item in policy_grid()}
    observed = {item.canonical_id for item in grid.candidates}
    if not observed.issubset(allowed):
        raise V14ContractError("V14_ROUTER_POLICY_ID", str(sorted(observed - allowed)))
    return choose(grid.candidates, 6)


def _market_selection(
    market: Market,
    strategy_templates: tuple[ScoreTemplate, ...],
    router_templates: tuple[ScoreTemplate, ...],
) -> MarketSelection:
    if len(strategy_templates) != 4 or len(router_templates) != 6:
        raise V14ContractError("V14_TEMPLATE_COUNT",
            f"{len(strategy_templates)}:{len(router_templates)}")
    selections = tuple(
        StrategySelection(strategy_id=spec.strategy_id, selected=select_strategy(
            spec.strategy_id, DevelopmentGrid(segment="development", candidates=tuple(
                _candidate(item.parameter_set_id, template)
                for item, template in zip(
                    spec.parameter_sets, strategy_templates, strict=True
                )
            ))))
        for spec in REGISTRY
    )
    router_candidates = tuple(
        _candidate(policy.policy_hash, template)
        for policy, template in zip(policy_grid(), router_templates, strict=True)
    )
    return MarketSelection(market=market, strategies=selections,
        router_policy=select_router(DevelopmentGrid(
            segment="development", candidates=router_candidates)))


def _scores(inputs: SelectionInputs, market: Market) -> MarketScoreDescriptor:
    matches = tuple(item for item in inputs.markets if item.market is market)
    if len(matches) != 1:
        raise V14ContractError("V14_MARKET_ISOLATION", market.value)
    return matches[0]


def build_development_selection(
    cohort_hash: str, inputs: SelectionInputs
) -> DevelopmentSelection:
    kr = _scores(inputs, Market.KR)
    us = _scores(inputs, Market.US)
    markets = (
        _market_selection(Market.KR, kr.strategy_templates, kr.router_templates),
        _market_selection(Market.US, us.strategy_templates, us.router_templates),
    )
    body = DevelopmentSelectionBody(schema_version="v14.development_selection.1",
        cohort_hash=cohort_hash, markets=markets)
    return DevelopmentSelection(schema_version=body.schema_version,
        cohort_hash=body.cohort_hash, markets=body.markets,
        selection_hash=canonical_hash(model_json(body)))
