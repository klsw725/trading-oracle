from __future__ import annotations

from decimal import Decimal
from src.v11.canonical import canonical_hash, model_json

from .bootstrap import bootstrap_series
from .bootstrap_models import SeriesKind
from .manifest_models import ExperimentPlanManifest
from .metric_models import (
    MetricsArtifact,
    MetricsBody,
    PrimaryMetrics,
    SecondaryMetrics,
)
from .samples import build_sample_report
from .series_models import DailySeriesArtifact


def _values(
    series: DailySeriesArtifact, kind: SeriesKind
) -> tuple[Decimal, ...]:
    return {
        SeriesKind.BASELINE: tuple(
            point.baseline_net_excess_return for point in series.points
        ),
        SeriesKind.STRESS: tuple(
            point.stress_net_excess_return for point in series.points
        ),
    }[kind]


def _primary(
    plan: ExperimentPlanManifest,
    series: DailySeriesArtifact,
    kind: SeriesKind,
) -> PrimaryMetrics:
    values = _values(series, kind)
    total = sum(values, Decimal(0))
    return PrimaryMetrics(series_kind=kind,
        mean_daily_net_excess_return=total / len(values),
        cumulative_net_excess_return=total,
        bootstrap=bootstrap_series(plan, series, kind))


def _secondary(series: DailySeriesArtifact) -> SecondaryMetrics:
    values = _values(series, SeriesKind.BASELINE)
    mean = sum(values, Decimal(0)) / len(values)
    variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) \
        / Decimal(len(values) - 1)
    deviation = variance.sqrt()
    sharpe = Decimal(0) if deviation == 0 else mean / deviation * Decimal(252).sqrt()
    valid_points = tuple(point for point in series.points if point.integrity_valid)
    completed = sum(point.completed_trades for point in valid_points)
    wins = sum(point.winning_trades for point in valid_points)
    cumulative = Decimal(0)
    peak = Decimal(0)
    drawdown = Decimal(0)
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return SecondaryMetrics(completed_trades=completed,
        win_rate=Decimal(0) if completed == 0 else Decimal(wins) / completed,
        annualized_sharpe=sharpe, maximum_drawdown=drawdown,
        turnover=sum((point.turnover for point in valid_points), Decimal(0)))


def build_metrics(
    plan: ExperimentPlanManifest, series: DailySeriesArtifact
) -> MetricsArtifact:
    body = MetricsBody(schema_version="v14.metrics.1",
        plan_manifest_hash=plan.manifest_hash, series_hash=series.series_hash,
        market=series.market, segment=series.segment,
        hypothesis_id=series.hypothesis_id,
        configuration_id=series.configuration_id,
        sample=build_sample_report(series),
        baseline=_primary(plan, series, SeriesKind.BASELINE),
        stress=_primary(plan, series, SeriesKind.STRESS),
        secondary=_secondary(series))
    return MetricsArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash, series_hash=body.series_hash,
        market=body.market, segment=body.segment,
        hypothesis_id=body.hypothesis_id,
        configuration_id=body.configuration_id, sample=body.sample,
        baseline=body.baseline, stress=body.stress, secondary=body.secondary,
        metrics_hash=canonical_hash(model_json(body)))
