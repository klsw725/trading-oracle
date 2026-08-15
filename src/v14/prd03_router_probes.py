from __future__ import annotations

from decimal import Decimal

from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market

from .contract import V14ContractError
from .metric_models import MetricsArtifact, MetricsBody
from .observed_models import (
    ObservedStrategyVerdictArtifact,
    ObservedStrategyVerdictBody,
)
from .prd02_pipeline import Prd02Artifacts
from .prd03_pipeline import Prd03Artifacts
from .prd03_router import build_router_segment
from .router_metric_models import RouterComparisonArtifact, RouterComparisonBody
from .series_models import DailySeriesArtifact, DailySeriesBody, ResearchSegment
from .verdict_models import HoldoutVerdict


def _seal_metrics(value: MetricsArtifact) -> MetricsArtifact:
    body = MetricsBody.model_validate(value.model_dump(exclude={"metrics_hash"}))
    return value.model_copy(update={"metrics_hash": canonical_hash(model_json(body))})


def _seal_series(value: DailySeriesArtifact) -> DailySeriesArtifact:
    body = DailySeriesBody.model_validate(value.model_dump(exclude={"series_hash"}))
    return value.model_copy(update={"series_hash": canonical_hash(model_json(body))})


def _seal_comparison(
    value: RouterComparisonArtifact,
) -> RouterComparisonArtifact:
    body = RouterComparisonBody.model_validate(
        value.model_dump(exclude={"comparison_hash"}))
    return value.model_copy(update={
        "comparison_hash": canonical_hash(model_json(body))})


def _seal_strategy(
    value: ObservedStrategyVerdictArtifact,
) -> ObservedStrategyVerdictArtifact:
    body = ObservedStrategyVerdictBody.model_validate(
        value.model_dump(exclude={"verdict_hash"}))
    return value.model_copy(update={"verdict_hash": canonical_hash(model_json(body))})


def _holdout_comparisons(
    artifacts: Prd02Artifacts,
) -> tuple[RouterComparisonArtifact, RouterComparisonArtifact]:
    return (next(item for item in artifacts.router_comparisons
        if item.market is Market.KR and item.segment is ResearchSegment.HOLDOUT),
        next(item for item in artifacts.router_comparisons
        if item.market is Market.US and item.segment is ResearchSegment.HOLDOUT))


def router_scenario_results(
    artifacts: Prd03Artifacts,
    prd02: Prd02Artifacts,
) -> dict[str, HoldoutVerdict]:
    kr, us = _holdout_comparisons(prd02)
    no_edge = _seal_comparison(kr.model_copy(update={"mixed_metrics":
        _seal_metrics(kr.mixed_metrics.model_copy(update={"baseline":
            kr.mixed_metrics.baseline.model_copy(update={"bootstrap":
                kr.mixed_metrics.baseline.bootstrap.model_copy(
                    update={"ci_upper": Decimal(0)})})}))}))
    cost_fragile = _seal_comparison(kr.model_copy(update={"paired_metrics":
        _seal_metrics(kr.paired_metrics.model_copy(update={"stress":
            kr.paired_metrics.stress.model_copy(
                update={"cumulative_net_excess_return": Decimal(0)})}))}))
    insufficient = _seal_comparison(kr.model_copy(update={"paired_metrics":
        _seal_metrics(kr.paired_metrics.model_copy(update={"sample":
            kr.paired_metrics.sample.model_copy(update={"independent_signal_days": 99,
                "sufficient": False})}))}))
    inconclusive = _seal_comparison(kr.model_copy(update={"mixed_metrics":
        _seal_metrics(kr.mixed_metrics.model_copy(update={"baseline":
            kr.mixed_metrics.baseline.model_copy(update={"bootstrap":
                kr.mixed_metrics.baseline.bootstrap.model_copy(
                    update={"ci_lower": Decimal(0)})})}))}))
    paired_points = (kr.paired_series.points[0].model_copy(
        update={"integrity_valid": False}), *kr.paired_series.points[1:])
    invalid = _seal_comparison(kr.model_copy(update={"paired_series":
        _seal_series(kr.paired_series.model_copy(update={"points": paired_points}))}))
    blocked = next(item for item in artifacts.observed_strategy_verdicts
        if item.market is Market.KR and item.segment is ResearchSegment.HOLDOUT
        and item.hypothesis_id != artifacts.registry.primary.hypothesis_id)
    blocked = _seal_strategy(blocked.model_copy(
        update={"verdict": HoldoutVerdict.MULTIPLE_TESTING}))
    blocked_strategies = tuple(blocked if item.market is Market.KR
        and item.segment is ResearchSegment.HOLDOUT
        and item.hypothesis_id == blocked.hypothesis_id else item
        for item in artifacts.observed_strategy_verdicts)

    def verdict(comparison: RouterComparisonArtifact,
            strategies: tuple[ObservedStrategyVerdictArtifact, ...]
            = artifacts.observed_strategy_verdicts) -> HoldoutVerdict:
        result = build_router_segment(artifacts.registry, (comparison, us),
            strategies, ResearchSegment.HOLDOUT).verdicts[0].verdict
        if not isinstance(result, HoldoutVerdict):
            raise V14ContractError("V14_ROUTER_VERDICT_TYPE", "probe")
        return result

    return {"no_edge": verdict(no_edge), "cost_fragile": verdict(cost_fragile),
        "insufficient": verdict(insufficient), "inconclusive": verdict(inconclusive),
        "invalid": verdict(invalid), "multiple_testing": verdict(kr, blocked_strategies)}
