from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json
from src.v11.models import CostPolicy

from .contract import V14ContractError
from .manifest_models import ExperimentPlanManifest
from .metrics import build_metrics
from .router_metric_models import (
    RouterComparisonArtifact,
    RouterComparisonBody,
    RouterRunDescriptors,
)
from .series import build_daily_series, generate_run


def build_router_comparison(
    plan: ExperimentPlanManifest,
    descriptors: RouterRunDescriptors,
    policy: CostPolicy,
) -> RouterComparisonArtifact:
    mixed_series = build_daily_series(plan,
        generate_run(plan, descriptors.mixed, policy))
    deterministic_series = build_daily_series(plan,
        generate_run(plan, descriptors.deterministic, policy))
    paired_series = build_daily_series(plan,
        generate_run(plan, descriptors.paired, policy))
    aligned = mixed_series.official_sessions == deterministic_series.official_sessions \
        == paired_series.official_sessions
    if not aligned:
        raise V14ContractError("V14_ROUTER_SERIES_ALIGNMENT", descriptors.market.value)
    mixed_metrics = build_metrics(plan, mixed_series)
    deterministic_metrics = build_metrics(plan, deterministic_series)
    paired_metrics = build_metrics(plan, paired_series)
    body = RouterComparisonBody(schema_version="v14.router_comparison.1",
        plan_manifest_hash=plan.manifest_hash, selection_hash=plan.selection_hash,
        market=descriptors.market, segment=descriptors.segment,
        selected_policy_id=descriptors.selected_policy_id,
        mixed_series=mixed_series, mixed_metrics=mixed_metrics,
        deterministic_series=deterministic_series,
        deterministic_metrics=deterministic_metrics,
        paired_series=paired_series, paired_metrics=paired_metrics)
    return RouterComparisonArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash,
        selection_hash=body.selection_hash, market=body.market,
        segment=body.segment, selected_policy_id=body.selected_policy_id,
        mixed_series=body.mixed_series, mixed_metrics=body.mixed_metrics,
        deterministic_series=body.deterministic_series,
        deterministic_metrics=body.deterministic_metrics,
        paired_series=body.paired_series, paired_metrics=body.paired_metrics,
        comparison_hash=canonical_hash(model_json(body)))
