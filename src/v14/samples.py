from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json

from .metric_models import SampleReport, SampleReportBody
from .series_models import DailySeriesArtifact, ResearchSegment


def sample_thresholds(segment: ResearchSegment) -> tuple[int, int]:
    return {
        ResearchSegment.VALIDATION: (60, 150),
        ResearchSegment.HOLDOUT: (100, 300),
    }[segment]


def sample_sufficient(
    segment: ResearchSegment, signal_days: int, completed_trades: int
) -> bool:
    required_days, required_trades = sample_thresholds(segment)
    return signal_days >= required_days and completed_trades >= required_trades


def build_sample_report(series: DailySeriesArtifact) -> SampleReport:
    signal_days = sum(point.integrity_valid
        and point.pre_portfolio_candidates > 0 for point in series.points)
    completed = sum(point.completed_trades for point in series.points
        if point.integrity_valid)
    required_days, required_trades = sample_thresholds(series.segment)
    body = SampleReportBody(schema_version="v14.sample_report.1",
        market=series.market, segment=series.segment,
        independent_signal_days=signal_days, completed_trades=completed,
        required_signal_days=required_days,
        required_completed_trades=required_trades,
        sufficient=sample_sufficient(series.segment, signal_days, completed))
    return SampleReport(schema_version=body.schema_version, market=body.market,
        segment=body.segment, independent_signal_days=body.independent_signal_days,
        completed_trades=body.completed_trades,
        required_signal_days=body.required_signal_days,
        required_completed_trades=body.required_completed_trades,
        sufficient=body.sufficient, sample_hash=canonical_hash(model_json(body)))
