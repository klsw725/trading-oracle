from __future__ import annotations

from functools import cache
from typing import Annotated

from pydantic import Field

from .contract import StrictModel, V14ContractError
from .fixture import load_fixture
from .manifest_models import ExperimentPlanManifest
from .metric_models import MetricsArtifact
from .metrics import build_metrics
from .pipeline import build_prd01
from .prd02_matrix import router_descriptors, strategy_descriptors
from .prd02_fixture import load_prd02_fixture
from .router_metric_models import RouterComparisonArtifact
from .router_metrics import build_router_comparison
from .selection_models import DevelopmentSelection
from .series import build_daily_series, generate_run
from .series_models import CostFixture, DailySeriesArtifact, ResearchSegment


class Prd02Artifacts(StrictModel):
    series: Annotated[tuple[DailySeriesArtifact, ...], Field(strict=False)]
    metrics: Annotated[tuple[MetricsArtifact, ...], Field(strict=False)]
    router_comparisons: Annotated[
        tuple[RouterComparisonArtifact, ...], Field(strict=False)
    ]


def build_prd02_segment_from(
    plan: ExperimentPlanManifest,
    selection: DevelopmentSelection,
    fixture: CostFixture,
    segment: ResearchSegment,
) -> Prd02Artifacts:
    if fixture.policy.version != plan.costs.baseline \
            or fixture.stress_model_id != plan.costs.stress_2x_variable:
        raise V14ContractError("V14_COST_MODEL_MISMATCH", fixture.policy.version)
    descriptors = tuple(item for item in strategy_descriptors(fixture, selection)
        if item.segment is segment)
    router = tuple(item for item in router_descriptors(fixture, selection)
        if item.segment is segment)
    series = tuple(build_daily_series(plan,
        generate_run(plan, descriptor, fixture.policy)) for descriptor in descriptors)
    metrics = tuple(build_metrics(plan, item) for item in series)
    comparisons = tuple(build_router_comparison(plan, item, fixture.policy)
        for item in router)
    return Prd02Artifacts(series=series, metrics=metrics,
        router_comparisons=comparisons)


def build_prd02_validation_from(
    plan: ExperimentPlanManifest,
    selection: DevelopmentSelection,
    fixture: CostFixture,
) -> Prd02Artifacts:
    return build_prd02_segment_from(
        plan, selection, fixture, ResearchSegment.VALIDATION)


def build_prd02_holdout_from(
    plan: ExperimentPlanManifest,
    selection: DevelopmentSelection,
    fixture: CostFixture,
) -> Prd02Artifacts:
    return build_prd02_segment_from(
        plan, selection, fixture, ResearchSegment.HOLDOUT)


def build_prd02_from(
    plan: ExperimentPlanManifest,
    selection: DevelopmentSelection,
    fixture: CostFixture,
) -> Prd02Artifacts:
    if fixture.policy.version != plan.costs.baseline \
            or fixture.stress_model_id != plan.costs.stress_2x_variable:
        raise V14ContractError("V14_COST_MODEL_MISMATCH", fixture.policy.version)
    descriptors = strategy_descriptors(fixture, selection)
    series = tuple(build_daily_series(plan,
        generate_run(plan, descriptor, fixture.policy)) for descriptor in descriptors)
    metrics = tuple(build_metrics(plan, item) for item in series)
    comparisons = tuple(build_router_comparison(plan, item, fixture.policy)
        for item in router_descriptors(fixture, selection))
    return Prd02Artifacts(series=series, metrics=metrics,
        router_comparisons=comparisons)


@cache
def build_prd02() -> Prd02Artifacts:
    prd01 = build_prd01(load_fixture())
    return build_prd02_from(prd01.plan, prd01.selection, load_prd02_fixture())
