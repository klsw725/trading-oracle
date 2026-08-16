from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from src.v11.canonical import canonical_hash, model_json
from src.v11.replay import replay as replay_v11
from src.v4.models import JsonValue

from .acceptance_fixture import load_verified_bundle
from .acceptance_report import JsonRecord, MutationState, report
from .approvals import (
    Approval,
    ApprovalBody,
    ChangeKind,
    seal_data_exception,
    verify_manual_approval_consumption,
)
from .contract import V15Failure
from .operation_fixture import official_sessions, verify_calendar
from .operation_models import (
    MarketOperation,
    OperationBundle,
    OrbQualificationEvidence,
    material_from_bundle,
)
from .operation_replay import replay
from .states import LifecycleState, verify_chain
from .v11_mirror_ledger import MirrorBuildContext, build_mirror_ledger


def _killed(action: Callable[[], JsonValue | None]) -> MutationState:
    try:
        _ = action()
    except V15Failure:
        return "killed"
    return "survived"


def _all_killed(
    actions: tuple[Callable[[], JsonValue | None], ...],
) -> MutationState:
    for action in actions:
        if _killed(action) != "killed":
            return "survived"
    return "killed"


def _replay(bundle: OperationBundle) -> None:
    _ = replay(material_from_bundle(bundle))


def _replace_market(
    bundle: OperationBundle,
    market_index: int,
    market: MarketOperation,
) -> OperationBundle:
    markets = list(bundle.markets)
    markets[market_index] = market
    return bundle.model_copy(update={"markets": tuple(markets)})


def _seal_approval(approval: Approval) -> Approval:
    body = ApprovalBody.model_validate(approval.model_dump(
        exclude={"approval_hash"}))
    return approval.model_copy(update={"approval_hash": canonical_hash(
        model_json(body))})


def evaluate(bundle: OperationBundle) -> JsonRecord:
    forged = bundle.model_copy(update={"approvals": (
        bundle.approvals[0].model_copy(update={"approval_hash": "sha256:forged"}),
        bundle.approvals[1])})
    kr = bundle.markets[0]
    qualification = kr.orb_qualification
    short_ledger = build_mirror_ledger(MirrorBuildContext(
        mirror=qualification.ledger.account, schedule=kr.schedule,
        sessions=kr.schedule.qualification_sessions[:-1],
        initial_nav=bundle.source.initial_nav,
        completed_trades_per_trade_day=1, returns=bundle.source.returns,
        manifest_hash=bundle.upstream.policy.manifest_hash))
    short_draft = OrbQualificationEvidence(
        schema_version="v15.orb_qualification.1", ledger=short_ledger,
        official_sessions=len(short_ledger.days),
        completed_trades=sum(day.completed_trades for day in short_ledger.days),
        critical_incident_hashes=(), evidence_hash="")
    short = short_draft.model_copy(update={"evidence_hash": canonical_hash(
        model_json(short_draft))})
    early = _replace_market(bundle, 0, kr.model_copy(update={
        "orb_qualification": short}))
    skipped_timeline = bundle.source.markets[0].model_copy(update={
        "qualification_start": kr.schedule.qualification_sessions[1]})
    skipped = bundle.model_copy(update={"source": bundle.source.model_copy(
        update={"markets": (skipped_timeline, bundle.source.markets[1])})})
    data_approval = bundle.approvals[0]
    automatic_data = _seal_approval(data_approval.model_copy(update={
        "reviewer": "automation", "automatic": True}))
    bad_exception = data_approval.data_exceptions[0].model_copy(update={
        "detail_hash": "sha256:mutated"})
    unhashed_data = _seal_approval(data_approval.model_copy(update={
        "data_exceptions": (bad_exception,)}))
    us_approval = bundle.approvals[1]
    changed_identity = us_approval.current_identity.model_copy(update={
        "risk_version": "risk-v15-mutated"})
    automatic_policy = _seal_approval(us_approval.model_copy(update={
        "current_identity": changed_identity,
        "reviewer": "automation", "automatic": True}))
    data_bundle = bundle.model_copy(update={"approvals": (
        automatic_data, bundle.approvals[1])})
    unhashed_bundle = bundle.model_copy(update={"approvals": (
        unhashed_data, bundle.approvals[1])})
    policy_bundle = bundle.model_copy(update={"approvals": (
        bundle.approvals[0], automatic_policy)})
    missing_manual = bundle.model_copy(update={"source":
        bundle.source.model_copy(update={"manual_approvals": ()})})
    calendar = bundle.source.markets[0].calendar
    changed_calendar = calendar.model_copy(update={"holidays": (
        *calendar.holidays, bundle.source.markets[0].qualification_start)})
    changed_body = changed_calendar.model_copy(update={"calendar_hash": ""})
    changed_calendar = changed_calendar.model_copy(update={"calendar_hash":
        canonical_hash(model_json(changed_body))})
    changed_timeline = bundle.source.markets[0].model_copy(update={
        "calendar": changed_calendar})
    mutations: dict[str, MutationState] = {
        "approval_hash_forgery_e2e": _killed(lambda: _replay(forged)),
        "orb_qualification_early_promotion_e2e": _all_killed((
            lambda: _replay(early), lambda: _replay(skipped),
            lambda: verify_calendar(changed_timeline))),
        "policy_data_auto_approval_e2e": _all_killed((
            lambda: _replay(data_bundle), lambda: _replay(unhashed_bundle),
            lambda: _replay(policy_bundle), lambda: _replay(missing_manual),
            lambda: verify_manual_approval_consumption(
                bundle.source.manual_approvals,
                (*bundle.source.manual_approvals,
                    bundle.source.manual_approvals[0])))),
    }
    lifecycle = tuple(event for event in bundle.events
        if event.event_type.value == "lifecycle")
    checks = {
        "first_post_gate_session_enforced": all(
            market.schedule.qualification_sessions[0] == official_sessions(
                timeline.calendar,
                bundle.upstream.gate_available_at.date() + timedelta(days=1), 1)[0]
            for market, timeline in zip(bundle.markets,
                bundle.source.markets, strict=True)),
        "qualification_v11_replay_20_30_0": all(
            market.orb_qualification.official_sessions == 20
            and market.orb_qualification.completed_trades >= 30
            and not market.orb_qualification.critical_incident_hashes
            and replay_v11(market.orb_qualification.ledger.events,
                market.orb_qualification.ledger.initial_cash)
                == market.orb_qualification.ledger.replay_state
            for market in bundle.markets),
        "official_calendars_market_specific": bundle.source.markets[0]
            .calendar.calendar_id != bundle.source.markets[1].calendar.calendar_id
            and bundle.source.markets[0].calendar.timezone
                != bundle.source.markets[1].calendar.timezone,
        "challenger_is_comparison_epoch": all(
            item.schedule.challenger_session
                == item.paired_series.plan.comparison_epoch_start
            for item in bundle.markets),
        "orb_qualification_separate": all(item.orb_qualification.ledger.days[-1]
            .session < item.schedule.challenger_session for item in bundle.markets),
        "both_market_lifecycle": {event.market for event in lifecycle
            if event.lifecycle_after is LifecycleState.ROUTER_CHALLENGER}
                == {"KR", "US"},
        "approval_hashes_bound_to_events": all(approval.approval_hash
            in {ref for event in bundle.events for ref in event.evidence_refs}
            for approval in bundle.approvals),
        "qualification_hashes_bound_to_activation": all(
            market.orb_qualification.evidence_hash in {
                ref for event in bundle.events
                if event.market == market.market
                and event.lifecycle_after in {LifecycleState.STRATEGIES_SHADOW,
                    LifecycleState.ROUTER_SHADOW,
                    LifecycleState.ROUTER_CHALLENGER}
                for ref in event.evidence_refs}
            and market.orb_qualification.ledger.ledger_hash in {
                ref for event in bundle.events
                if event.market == market.market
                and event.lifecycle_after is LifecycleState.ROUTER_CHALLENGER
                for ref in event.evidence_refs}
            for market in bundle.markets),
        "data_exception_requires_manual_approval":
            bundle.approvals[0].change_kind is ChangeKind.DATA_EXCEPTION
            and not bundle.approvals[0].automatic
            and all(seal_data_exception(item) == item
                for item in bundle.approvals[0].data_exceptions)
            and bundle.approvals[1].change_kind is ChangeKind.ROUTINE
            and bundle.approvals[1].automatic,
        "data_exception_hash_bound_to_activation": all(
            item.evidence_hash in {ref for event in bundle.events
                if event.market == "KR"
                and event.lifecycle_after is LifecycleState.ORB_PAPER
                for ref in event.evidence_refs}
            for item in bundle.approvals[0].data_exceptions),
        "legal_lifecycle_chain": verify_chain(bundle.events)
            == bundle.replay.operation_chain_hash,
    }
    return report("v15.prd01_acceptance.3", checks, mutations,
        {"v14_approval_hash": bundle.upstream.v14_approval_hash,
            "operation_chain_hash": bundle.replay.operation_chain_hash,
            "kr_calendar_hash": bundle.markets[0].schedule.calendar_hash,
            "us_calendar_hash": bundle.markets[1].schedule.calendar_hash,
            "kr_qualification_hash": bundle.markets[0].orb_qualification.evidence_hash,
            "us_qualification_hash": bundle.markets[1].orb_qualification.evidence_hash,
            "data_exception_hash": bundle.approvals[0].data_exceptions[0]
                .evidence_hash})


def run_acceptance() -> JsonValue:
    return evaluate(load_verified_bundle())
