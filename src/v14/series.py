from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.v11.canonical import canonical_hash, decimal_value, model_json
from src.v11.costs import freeze_policy
from src.v11.models import CostPolicy, OrderAction
from src.v12.models import Market

from .contract import V14ContractError
from .cost_stress import cost_pair
from .manifest_models import ExperimentPlanManifest, MarketPeriod
from .series_models import (
    CostReplayInput,
    DailyObservation,
    DailyRunInput,
    DailySeriesArtifact,
    DailySeriesBody,
    DailySeriesPoint,
    ResearchSegment,
    RunDescriptor,
)


def _period(
    plan: ExperimentPlanManifest, market: Market
) -> MarketPeriod:
    matches = tuple(item for item in plan.periods if item.market is market)
    if len(matches) != 1:
        raise V14ContractError("V14_PERIOD_MARKET", market.value)
    return matches[0]


def _bounds(
    plan: ExperimentPlanManifest,
    market: Market,
    segment: ResearchSegment,
) -> tuple[date, date]:
    period = _period(plan, market)
    return {
        ResearchSegment.VALIDATION: (
            period.validation_start, period.holdout_start
        ),
        ResearchSegment.HOLDOUT: (period.holdout_start, period.holdout_end),
    }[segment]


def _official_sessions(start: date, end: date) -> tuple[date, ...]:
    sessions: list[date] = []
    current = start
    while current < end:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def generate_run(
    plan: ExperimentPlanManifest,
    descriptor: RunDescriptor,
    policy: CostPolicy,
) -> DailyRunInput:
    start, end = _bounds(plan, descriptor.market, descriptor.segment)
    sessions = _official_sessions(start, end)
    observations: list[DailyObservation] = []
    for index, session in enumerate(sessions):
        signal = (index + 1) % descriptor.signal_skip_modulus != 0
        traded = signal and index % descriptor.trade_day_modulus == 0
        action = OrderAction.SELL if index % 2 == 0 else OrderAction.SHORT
        notional = descriptor.traded_notional if traded else Decimal(0)
        gross = (descriptor.gross_base
            + descriptor.gross_wave[index % len(descriptor.gross_wave)]
            if traded else Decimal(0))
        completed = descriptor.completed_trades_per_trade if traded else 0
        wins = min(descriptor.wins_per_trade, completed)
        observations.append(DailyObservation(session_date=session,
            revision_observed_at=session, action=action, nav=descriptor.nav,
            gross_excess_return=gross, traded_notional=notional,
            pre_portfolio_candidates=1 if signal else 0,
            completed_trades=completed, winning_trades=wins,
            turnover=notional / descriptor.nav, integrity_valid=True))
    frozen_policy = freeze_policy(policy, start.isoformat())
    calendar_hash = canonical_hash([session.isoformat() for session in sessions])
    return DailyRunInput(plan_manifest_hash=plan.manifest_hash,
        market=descriptor.market, segment=descriptor.segment,
        hypothesis_id=descriptor.hypothesis_id,
        configuration_id=descriptor.configuration_id, calendar_hash=calendar_hash,
        official_sessions=sessions, observations=tuple(observations),
        cost_policy=frozen_policy)


def build_daily_series(
    plan: ExperimentPlanManifest, run: DailyRunInput
) -> DailySeriesArtifact:
    if run.plan_manifest_hash != plan.manifest_hash:
        raise V14ContractError("V14_SERIES_PLAN", run.plan_manifest_hash)
    start, end = _bounds(plan, run.market, run.segment)
    if len(run.official_sessions) < plan.bootstrap.block_trading_days:
        raise V14ContractError("V14_SERIES_LENGTH", str(len(run.official_sessions)))
    if canonical_hash([day.isoformat() for day in run.official_sessions]) \
            != run.calendar_hash:
        raise V14ContractError("V14_MISSING_TRADING_DAY", run.market.value)
    if run.official_sessions != tuple(sorted(set(run.official_sessions))):
        raise V14ContractError("V14_CALENDAR_ORDER", run.market.value)
    if any(day < start or day >= end for day in run.official_sessions):
        raise V14ContractError("V14_CALENDAR_PERIOD", run.market.value)
    observed_dates = tuple(item.session_date for item in run.observations)
    if observed_dates != run.official_sessions:
        raise V14ContractError("V14_MISSING_TRADING_DAY", run.market.value)
    points: list[DailySeriesPoint] = []
    for item in run.observations:
        if item.revision_observed_at > item.session_date:
            raise V14ContractError("V14_FUTURE_REVISION", item.session_date.isoformat())
        baseline, stress = cost_pair(CostReplayInput(policy=run.cost_policy,
            market=run.market, action=item.action, notional=item.traded_notional))
        baseline_net = item.gross_excess_return - decimal_value(baseline.total) / item.nav
        stress_net = item.gross_excess_return - decimal_value(stress.total) / item.nav
        points.append(DailySeriesPoint(session_date=item.session_date,
            gross_excess_return=item.gross_excess_return,
            baseline_net_excess_return=baseline_net,
            stress_net_excess_return=stress_net, baseline_costs=baseline,
            stress_costs=stress, traded_notional=item.traded_notional,
            pre_portfolio_candidates=item.pre_portfolio_candidates,
            completed_trades=item.completed_trades,
            winning_trades=item.winning_trades, turnover=item.turnover,
            integrity_valid=item.integrity_valid))
    body = DailySeriesBody(schema_version="v14.daily_series.1",
        plan_manifest_hash=plan.manifest_hash, market=run.market,
        segment=run.segment, hypothesis_id=run.hypothesis_id,
        configuration_id=run.configuration_id,
        calendar_hash=run.calendar_hash, official_sessions=run.official_sessions,
        points=tuple(points))
    return DailySeriesArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash, market=body.market,
        segment=body.segment, hypothesis_id=body.hypothesis_id,
        configuration_id=body.configuration_id,
        calendar_hash=body.calendar_hash,
        official_sessions=body.official_sessions, points=body.points,
        series_hash=canonical_hash(model_json(body)))
