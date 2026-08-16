from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from src.v11.models import EventType
from src.v11.replay import replay as replay_v11
from src.v4.models import JsonValue

from .acceptance_fixture import load_verified_bundle
from .acceptance_report import JsonRecord, MutationState, report
from .contract import V15Failure
from .operation_models import MarketOperation, OperationBundle, material_from_bundle
from .operation_build import build_operation_bundle
from .operation_replay import replay
from .paired import PairedSeries, pair_days
from .winner import WinnerVerdict


def _killed(action: Callable[[], PairedSeries | None]) -> MutationState:
    try:
        _ = action()
    except V15Failure:
        return "killed"
    return "survived"


def _all_killed(
    actions: tuple[Callable[[], PairedSeries | None], ...],
) -> MutationState:
    for action in actions:
        if _killed(action) != "killed":
            return "survived"
    return "killed"


def _replay(bundle: OperationBundle) -> None:
    _ = replay(material_from_bundle(bundle))


def _replace_market(
    bundle: OperationBundle, market_index: int, market: MarketOperation
) -> OperationBundle:
    markets = list(bundle.markets)
    markets[market_index] = market
    return bundle.model_copy(update={"markets": tuple(markets)})


def evaluate(bundle: OperationBundle) -> JsonRecord:
    kr = bundle.markets[0]
    orb, router = kr.mirror_ledgers
    shared_account = router.account.model_copy(update={
        "account_namespace": orb.account.account_namespace})
    shared_router = router.model_copy(update={"account": shared_account})
    shared_market = kr.model_copy(update={"mirror_ledgers": (orb, shared_router)})
    missing_series = kr.paired_series.model_copy(update={
        "points": kr.paired_series.points[:-1]})
    missing_market = kr.model_copy(update={"paired_series": missing_series})
    fill_index = next(index for index, event in enumerate(router.events)
        if event.event_type is EventType.FILL_COMPLETE)
    missing_fill = router.model_copy(update={"events": (
        *router.events[:fill_index], *router.events[fill_index + 1:])})
    fill_market = kr.model_copy(update={"mirror_ledgers": (orb, missing_fill)})
    drift_day = orb.days[0].model_copy(update={"evidence":
        orb.days[0].evidence.model_copy(update={"manifest_hash": "sha256:drift"})})
    drift_orb = orb.model_copy(update={"days": (drift_day, *orb.days[1:])})
    drift_market = kr.model_copy(update={"mirror_ledgers": (drift_orb, router)})
    bad_integrity = kr.integrity.model_copy(update={"evidence_hash": "sha256:bad"})
    integrity_market = kr.model_copy(update={"integrity": bad_integrity})
    orb_returns = bundle.source.returns.model_copy(update={
        "router_winner_period": Decimal("-0.003"),
        "router_gross": Decimal("-0.003")})
    orb_bundle = build_operation_bundle(bundle.source.model_copy(update={
        "returns": orb_returns}), bundle.upstream)
    tied_returns = bundle.source.returns.model_copy(update={
        "router_winner_period": bundle.source.returns.orb,
        "router_gross": bundle.source.returns.orb})
    tied_bundle = build_operation_bundle(bundle.source.model_copy(update={
        "returns": tied_returns}), bundle.upstream)
    mutations: dict[str, MutationState] = {
        "shared_account_namespace_e2e": _killed(lambda: _replay(
            _replace_market(bundle, 0, shared_market))),
        "paired_series_missing_official_session_e2e": _all_killed((
            lambda: _replay(_replace_market(bundle, 0, missing_market)),
            lambda: pair_days(kr.paired_series.plan,
                (*orb.days, orb.days[0]), router.days))),
        "winner_sample_below_300_replayed_ledger_e2e": _killed(lambda: _replay(
            _replace_market(bundle, 0, fill_market))),
        "mirror_day_evidence_drift_reaches_report_e2e": _killed(lambda: _replay(
            _replace_market(bundle, 0, drift_market))),
        "winner_integrity_forgery_e2e": _killed(lambda: _replay(
            _replace_market(bundle, 0, integrity_market))),
    }
    checks = {
        "four_isolated_mirror_accounts": len({ledger.account.account_namespace
            for market in bundle.markets for ledger in market.mirror_ledgers}) == 4,
        "both_market_v11_replay": all(replay_v11(ledger.events,
            ledger.initial_cash) == ledger.replay_state
            for market in bundle.markets for ledger in market.mirror_ledgers),
        "comparison_starts_at_challenger": all(market.paired_series.points[0].session
            == market.schedule.challenger_session for market in bundle.markets),
        "rolling_daily_after_60": all(market.rolling_winners[0].observation_count
            == 60 and market.rolling_winners[-1].observation_count == 80
            and len(market.rolling_winners) == 21 for market in bundle.markets),
        "winner_uses_challenger_data_only": all(
            market.initial_winner.evaluation_session
                == market.schedule.comparison_sessions[59]
            for market in bundle.markets),
        "winner_real_trade_counts": all(sum(point.router_completed_trades
            for point in market.paired_series.points[:60]) >= 300
            for market in bundle.markets),
        "both_markets_router_win": all(market.initial_winner.verdict
            is WinnerVerdict.ROUTER for market in bundle.markets),
        "orb_winner_remains_challenger": all(market.initial_winner.verdict
            is WinnerVerdict.ORB and market.router_winner is None
            and market.schedule.router_primary_session is None
            and market.performance_rollback is None for market in orb_bundle.markets)
            and orb_bundle.replay.final_router_state == "router_challenger"
            and not orb_bundle.retirement_registry.records,
        "inconclusive_remains_challenger": all(market.initial_winner.verdict
            is WinnerVerdict.INCONCLUSIVE and market.router_winner is None
            and market.schedule.router_primary_session is None
            and market.performance_rollback is None for market in tied_bundle.markets)
            and tied_bundle.replay.final_router_state == "router_challenger"
            and not tied_bundle.retirement_registry.records,
    }
    return report("v15.prd02_acceptance.3", checks, mutations,
        {"kr_paired_hash": kr.paired_series.series_hash,
            "us_paired_hash": bundle.markets[1].paired_series.series_hash,
            "kr_winner_hash": kr.initial_winner.winner_hash,
            "us_winner_hash": bundle.markets[1].initial_winner.winner_hash})


def run_acceptance() -> JsonValue:
    return evaluate(load_verified_bundle())
