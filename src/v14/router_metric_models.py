from __future__ import annotations

from typing import Literal

from .cohort_models import JsonMarket
from .contract import StrictModel
from .metric_models import MetricsArtifact
from .series_models import DailySeriesArtifact, JsonSegment, RunDescriptor


class RouterRunDescriptors(StrictModel):
    market: JsonMarket
    segment: JsonSegment
    selected_policy_id: str
    mixed: RunDescriptor
    deterministic: RunDescriptor
    paired: RunDescriptor


class RouterComparisonBody(StrictModel):
    schema_version: Literal["v14.router_comparison.1"]
    plan_manifest_hash: str
    selection_hash: str
    market: JsonMarket
    segment: JsonSegment
    selected_policy_id: str
    mixed_series: DailySeriesArtifact
    mixed_metrics: MetricsArtifact
    deterministic_series: DailySeriesArtifact
    deterministic_metrics: MetricsArtifact
    paired_series: DailySeriesArtifact
    paired_metrics: MetricsArtifact


class RouterComparisonArtifact(RouterComparisonBody):
    comparison_hash: str
