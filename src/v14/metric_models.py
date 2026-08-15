from __future__ import annotations

from typing import Literal

from .bootstrap_models import BootstrapArtifact, JsonSeriesKind
from .cohort_models import JsonMarket
from .contract import StrictModel
from .selection_models import JsonDecimal
from .series_models import JsonSegment


class SampleReportBody(StrictModel):
    schema_version: Literal["v14.sample_report.1"]
    market: JsonMarket
    segment: JsonSegment
    independent_signal_days: int
    completed_trades: int
    required_signal_days: int
    required_completed_trades: int
    sufficient: bool


class SampleReport(SampleReportBody):
    sample_hash: str


class PrimaryMetrics(StrictModel):
    series_kind: JsonSeriesKind
    mean_daily_net_excess_return: JsonDecimal
    cumulative_net_excess_return: JsonDecimal
    bootstrap: BootstrapArtifact


class SecondaryMetrics(StrictModel):
    completed_trades: int
    win_rate: JsonDecimal
    annualized_sharpe: JsonDecimal
    maximum_drawdown: JsonDecimal
    turnover: JsonDecimal


class MetricsBody(StrictModel):
    schema_version: Literal["v14.metrics.1"]
    plan_manifest_hash: str
    series_hash: str
    market: JsonMarket
    segment: JsonSegment
    hypothesis_id: str
    configuration_id: str
    sample: SampleReport
    baseline: PrimaryMetrics
    stress: PrimaryMetrics
    secondary: SecondaryMetrics


class MetricsArtifact(MetricsBody):
    metrics_hash: str
