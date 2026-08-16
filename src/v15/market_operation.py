from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .contract import V15Failure, V15FailureCode
from .challenger import promote_winner
from .mirrors import MirrorAccount, create_mirrors
from .operation_fixture import (
    MarketTimeline,
    MarketSchedule,
    OperationSourceFixture,
    build_schedule,
)
from .operation_models import MarketOperation, MirrorLedger
from .paired import ComparisonPlan, PairedSeries, pair_days
from .promotion import require_orb_paper, require_router_challenger
from .qualification import build_orb_qualification, verify_orb_qualification
from .retirement import RetirementRegistry
from .rollback import RouterVersion, performance_rollback
from .upstream import UpstreamEvidence
from .v11_mirror_ledger import MirrorBuildContext, build_mirror_ledger
from .winner import (
    IntegrityEvidence,
    WinnerArtifact,
    WinnerVerdict,
    rolling_winners,
    seal_integrity,
)


@dataclass(frozen=True, slots=True)
class ComparisonBuild:
    source: OperationSourceFixture
    schedule: MarketSchedule
    upstream: UpstreamEvidence
    mirrors: tuple[MirrorAccount, MirrorAccount]


@dataclass(frozen=True, slots=True)
class ComparisonArtifacts:
    ledgers: tuple[MirrorLedger, MirrorLedger]
    paired: PairedSeries
    integrity: IntegrityEvidence
    winners: tuple[WinnerArtifact, ...]


def build_market_operation(
    source: OperationSourceFixture,
    timeline: MarketTimeline,
    upstream: UpstreamEvidence,
    prior_registry: RetirementRegistry,
) -> MarketOperation:
    schedule = build_schedule(timeline, upstream.gate_available_at)
    _ = require_orb_paper(upstream, timeline.market)
    qualification = build_orb_qualification(source, schedule, upstream)
    verify_orb_qualification(qualification, schedule, upstream)
    _ = require_router_challenger(upstream, timeline.market,
        qualification.evidence_hash, prior_registry, source.policy_version)
    policy = upstream.policy
    mirrors = create_mirrors((timeline.market, schedule.challenger_session),
        source.initial_nav, (upstream.v14_bundle_hash,
            upstream.v14_result_manifest_hash, policy.risk_version,
            policy.cost_model))
    artifacts = _comparison(ComparisonBuild(source=source, schedule=schedule,
        upstream=upstream, mirrors=mirrors))
    winners = artifacts.winners
    if not winners or winners[0].observation_count != 60:
        raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT, timeline.market)
    first_router = next((item for item in winners
        if item.verdict is WinnerVerdict.ROUTER), None)
    primary = None
    if first_router is not None:
        primary = _next_session(schedule.comparison_sessions,
            first_router.evaluation_session)
    if primary is not None and first_router is not None:
        _ = promote_winner(first_router, prior_registry, source.policy_version)
        primary_index = schedule.comparison_sessions.index(primary)
        schedule = schedule.model_copy(update={"router_primary_session": primary,
            "performance_sessions": schedule.comparison_sessions[primary_index:]})
        artifacts = _comparison(ComparisonBuild(source=source,
            schedule=schedule, upstream=upstream, mirrors=mirrors))
        winners = artifacts.winners
        first_router = next(item for item in winners
            if item.verdict is WinnerVerdict.ROUTER)
        _ = promote_winner(first_router, prior_registry, source.policy_version)
    version = RouterVersion(market=timeline.market,
        version=source.policy_version, manifest_hash=policy.manifest_hash)
    rollback = performance_rollback(artifacts.paired, version,
        artifacts.integrity) \
        if len(schedule.performance_sessions) >= 20 else None
    return MarketOperation(market=timeline.market, schedule=schedule,
        orb_qualification=qualification,
        mirror_ledgers=artifacts.ledgers, paired_series=artifacts.paired,
        integrity=artifacts.integrity, rolling_winners=winners,
        initial_winner=winners[0], router_winner=first_router,
        performance_rollback=rollback)


def _next_session(
    sessions: tuple[date, ...], winner_session: date,
) -> date | None:
    index = sessions.index(winner_session) + 1
    return sessions[index] if index < len(sessions) else None


def _comparison(context: ComparisonBuild) -> ComparisonArtifacts:
    schedule = context.schedule
    ledgers = tuple(build_mirror_ledger(MirrorBuildContext(mirror=mirror,
        schedule=schedule, sessions=schedule.comparison_sessions,
        initial_nav=context.source.initial_nav,
        completed_trades_per_trade_day=context.source.completed_trades_per_trade_day,
        returns=context.source.returns,
        manifest_hash=context.upstream.policy.manifest_hash))
        for mirror in context.mirrors)
    typed_ledgers = (ledgers[0], ledgers[1])
    plan = ComparisonPlan(schema_version="v15.comparison_plan.1",
        market=schedule.market,
        comparison_epoch_start=schedule.challenger_session,
        router_primary_session=schedule.router_primary_session,
        expected_official_sessions=schedule.comparison_sessions,
        bootstrap=context.upstream.bootstrap)
    paired = pair_days(plan, typed_ledgers[0].days, typed_ledgers[1].days)
    integrity = seal_integrity(IntegrityEvidence(
        schema_version="v15.integrity_evidence.1", market=schedule.market,
        ledger_hashes=(typed_ledgers[0].ledger_hash,
            typed_ledgers[1].ledger_hash), critical_incident_hashes=(),
        evidence_hash=""))
    return ComparisonArtifacts(ledgers=typed_ledgers, paired=paired,
        integrity=integrity, winners=rolling_winners(paired, integrity))


def rebuild_market_operation(
    market: MarketOperation, source: OperationSourceFixture,
) -> MarketOperation:
    orb, router = market.mirror_ledgers
    plan = market.paired_series.plan
    paired = pair_days(plan, orb.days, router.days)
    integrity = seal_integrity(IntegrityEvidence(
        schema_version="v15.integrity_evidence.1", market=market.market,
        ledger_hashes=(orb.ledger_hash, router.ledger_hash),
        critical_incident_hashes=(), evidence_hash=""))
    winners = rolling_winners(paired, integrity)
    first_router = next((item for item in winners
        if item.verdict is WinnerVerdict.ROUTER), None)
    expected_primary = _next_session(market.schedule.comparison_sessions,
        first_router.evaluation_session) if first_router is not None else None
    if expected_primary != market.schedule.router_primary_session:
        if not winners:
            trade_counts = ":".join(str(value) for value in (
                sum(day.completed_trades for day in orb.days[:60]),
                sum(day.completed_trades for day in router.days[:60])))
            raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT,
                f"canonical_trades:{market.market}:{trade_counts}")
        first = winners[0]
        evidence = ":".join(str(value) for value in (
            first.verdict, first.ci_lower, first.ci_upper,
            first.router_stress_net_return))
        detail = f"canonical_winner:{market.market}:{expected_primary}:"
        detail += f"{market.schedule.router_primary_session}:{evidence}"
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED,
            detail)
    version = RouterVersion(market=market.market,
        version=source.policy_version,
        manifest_hash=orb.days[0].evidence.manifest_hash)
    rollback = performance_rollback(paired, version, integrity) \
        if len(market.schedule.performance_sessions) >= 20 else None
    return market.model_copy(update={"mirror_ledgers": (orb, router),
        "paired_series": paired, "integrity": integrity,
        "rolling_winners": winners, "initial_winner": winners[0],
        "router_winner": first_router, "performance_rollback": rollback})
