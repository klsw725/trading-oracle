from __future__ import annotations

from typing import TypedDict

from src.v12.models import Market
from src.v12.registry import REGISTRY

from .prd02_pipeline import Prd02Artifacts
from .selection_models import DevelopmentSelection
from .series_models import ResearchSegment


class InventoryChecks(TypedDict):
    strategy_metrics_exact_60: bool
    router_comparisons_exact_4: bool
    selected_configuration_lineage: bool
    strategy_scope_inventory: bool
    router_arm_lineage: bool


def inventory_checks(
    artifacts: Prd02Artifacts, selection: DevelopmentSelection
) -> InventoryChecks:
    expected = {(market, segment, spec.strategy_id)
        for market in Market for segment in ResearchSegment for spec in REGISTRY}
    observed = {(item.market, item.segment, item.hypothesis_id)
        for item in artifacts.metrics}
    selected = {(market.market, item.strategy_id): item.selected.canonical_id
        for market in selection.markets for item in market.strategies}
    configuration_lineage = all(item.configuration_id
        == selected[(item.market, item.hypothesis_id)] for item in artifacts.metrics)
    scopes = {(market, segment) for market in Market
        for segment in ResearchSegment}
    comparisons = artifacts.router_comparisons
    arm_lineage = all(item.plan_manifest_hash == item.mixed_metrics.plan_manifest_hash
        == item.deterministic_metrics.plan_manifest_hash
        == item.paired_metrics.plan_manifest_hash
        and item.mixed_metrics.metrics_hash != item.deterministic_metrics.metrics_hash
        and item.paired_metrics.metrics_hash not in {
            item.mixed_metrics.metrics_hash, item.deterministic_metrics.metrics_hash}
        and item.mixed_series.official_sessions
            == item.deterministic_series.official_sessions
            == item.paired_series.official_sessions
        and all(paired.baseline_net_excess_return
                == mixed.baseline_net_excess_return
                    - deterministic.baseline_net_excess_return
            and paired.stress_net_excess_return
                == mixed.stress_net_excess_return
                    - deterministic.stress_net_excess_return
            for mixed, deterministic, paired in zip(item.mixed_series.points,
                item.deterministic_series.points, item.paired_series.points,
                strict=True))
        and item.mixed_metrics.baseline.cumulative_net_excess_return > 0
        and item.mixed_metrics.stress.cumulative_net_excess_return > 0
        and item.selected_policy_id == next(market.router_policy.canonical_id
            for market in selection.markets if market.market is item.market)
        for item in comparisons)
    return InventoryChecks(strategy_metrics_exact_60=len(artifacts.metrics) == 60
            and len(artifacts.series) == 60,
        router_comparisons_exact_4=len(comparisons) == 4,
        selected_configuration_lineage=configuration_lineage,
        strategy_scope_inventory=observed == expected,
        router_arm_lineage=arm_lineage
            and {(item.market, item.segment) for item in comparisons} == scopes)
