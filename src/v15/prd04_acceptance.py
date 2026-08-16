from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue

from .acceptance_fixture import load_verified_bundle
from .acceptance_report import JsonRecord, MutationState, report
from .contract import V15Failure
from .effects import verify_paper_effects
from .observability import ExecutionMode
from .observability import LlmOutcomeKind, reduce_llm
from .operation_models import OperationBundle, material_from_bundle
from .operation_build import build_operation_bundle
from .operation_replay import replay
from .paper_boundary import verify_paper_boundary


def _killed(action: Callable[[], None]) -> MutationState:
    try:
        action()
    except V15Failure:
        return "killed"
    return "survived"


def _replay(bundle: OperationBundle) -> None:
    _ = replay(material_from_bundle(bundle))


def _all_killed(actions: tuple[Callable[[], None], ...]) -> MutationState:
    return "killed" if all(_killed(action) == "killed"
        for action in actions) else "survived"


def _build_with_prior_retirement(bundle: OperationBundle) -> None:
    record = bundle.retirement_registry.records[0]
    prior = bundle.source.prior_retirement_registry.model_copy(update={
        "records": (record,), "tail_hash": record.record_hash})
    _ = build_operation_bundle(bundle.source.model_copy(update={
        "prior_retirement_registry": prior}), bundle.upstream)


def evaluate(bundle: OperationBundle) -> JsonRecord:
    kr_llm = bundle.llm_outcomes[0]
    sticky_index = next(index for index, item in enumerate(kr_llm.outcomes)
        if item.execution_mode is ExecutionMode.QUANT_ONLY)
    breaker_session = kr_llm.outcomes[sticky_index].session
    sticky = kr_llm.outcomes[sticky_index].model_copy(update={
        "execution_mode": ExecutionMode.MIXED, "provider_called": True,
        "mixed_success": True, "quant_fallback": False})
    bad_llm = kr_llm.model_copy(update={"outcomes": (
        *kr_llm.outcomes[:sticky_index], sticky,
        *kr_llm.outcomes[sticky_index + 1:])})
    llm_bundle = bundle.model_copy(update={"llm_outcomes": (
        bad_llm, bundle.llm_outcomes[1])})
    retired_bundle = bundle.model_copy(update={"retirement_registry":
        bundle.retirement_registry.model_copy(update={"records":
            bundle.retirement_registry.records[1:]})})
    live_source = bundle.source.model_copy(update={"destination": "live"})
    live_bundle = bundle.model_copy(update={"source": live_source})
    contaminated_report = next(item for item in bundle.session_reports
        if item.data_health.active_incident_hashes)
    contaminated = contaminated_report.model_copy(update={"data_health":
        contaminated_report.data_health.model_copy(update={
            "active_incident_hashes": ()})})
    contaminated_bundle = bundle.model_copy(update={"session_reports": tuple(
        contaminated if item == contaminated_report else item
        for item in bundle.session_reports)})
    mutations: dict[str, MutationState] = {
        "llm_breaker_same_session_reset_e2e": _killed(
            lambda: _replay(llm_bundle)),
        "retirement_history_and_report_lineage_e2e": _all_killed((
            lambda: _replay(retired_bundle),
            lambda: _build_with_prior_retirement(bundle),
            lambda: _replay(contaminated_bundle))),
        "live_destination_e2e": _killed(lambda: _replay(live_bundle)),
    }
    hard_boundaries: dict[str, MutationState] = {
        "credential": _killed(lambda: verify_paper_boundary(
            {"destination": "paper", "credential": "secret"})),
        "raw_account_id": _killed(lambda: verify_paper_boundary(
            {"destination": "paper", "raw_account_id": "account"})),
        "portfolio_path": _killed(lambda: verify_paper_boundary(
            {"destination": "paper"}, Path("data/portfolio.json"))),
    }
    inventory = verify_paper_effects(bundle.effects)
    sticky_traces = tuple(outcome for ledger in bundle.llm_outcomes
        for outcome in ledger.outcomes if outcome.execution_mode
            is ExecutionMode.QUANT_ONLY)
    threshold_requested = tuple(LlmOutcomeKind.TIMEOUT
        if index in {0, 5, 10, 15} else LlmOutcomeKind.SUCCESS
        for index in range(20))
    threshold_session = bundle.markets[0].schedule.performance_sessions[0]
    threshold_trace = reduce_llm("KR",
        tuple(threshold_session for _ in threshold_requested),
        threshold_requested)
    same_session = tuple(item for item in kr_llm.outcomes[sticky_index:]
        if item.session == breaker_session)
    next_session = next(item.session for item in kr_llm.outcomes
        if item.session > breaker_session)
    reset = next(item for item in kr_llm.outcomes
        if item.session == next_session)
    reset_reports = tuple(item for item in bundle.session_reports
        if item.market == "KR" and item.session == next_session)
    checks = {
        "last_20_arbitrary_market_windows": all(len(
            market.performance_rollback.window_sessions) == 20
            and market.performance_rollback.window_sessions
                == market.schedule.comparison_sessions[-20:]
            for market in bundle.markets
            if market.performance_rollback is not None)
            and all(market.performance_rollback is not None
                for market in bundle.markets),
        "append_only_retirement_registry": len(
            bundle.retirement_registry.records) == 2
            and bundle.retirement_registry.tail_hash
                == bundle.retirement_registry.records[-1].record_hash,
        "retirement_consumed_by_replay": set(bundle.replay.retired_versions)
            == {f"{market.market}:{bundle.source.policy_version}"
                for market in bundle.markets},
        "same_session_breaker_suppresses_later_calls": bool(sticky_traces)
            and bool(same_session)
            and all(not item.provider_called and item.quant_fallback
                and not item.mixed_success
                and item.fallback_reason == "sticky_circuit_breaker"
                for item in same_session),
        "next_session_breaker_resets_to_mixed":
            reset.execution_mode is ExecutionMode.MIXED
            and reset.provider_called and reset.mixed_success
            and not reset.quant_fallback and not reset.breaker_open
            and len(reset_reports) == 2
            and all(not item.llm.circuit_open
                and item.llm.mixed_success_count == 1
                for item in reset_reports),
        "twenty_percent_window_opens_breaker":
            threshold_trace.outcomes[-1].breaker_open,
        "per_market_arm_session_reports": len(bundle.session_reports) == 320
            and {(item.market, item.arm) for item in bundle.session_reports}
                == {("KR", "orb"), ("KR", "router"),
                    ("US", "orb"), ("US", "router")},
        "reports_derive_activity_and_pnl": all(item.activity.orders > 0
            and item.paired.common_days > 0 for item in bundle.session_reports),
        "reports_expose_account_data_lineage": any(
            item.data_health.degraded
            and item.data_health.active_incident_hashes
            and not item.data_health.recovered_incident_hashes
            for item in bundle.session_reports) and any(
            not item.data_health.degraded and item.data_health.reconciled
            and item.data_health.recovered_incident_hashes
            and not item.data_health.active_incident_hashes
            for item in bundle.session_reports),
        "paper_effect_inventory_zero_live": inventory.network_calls == 0
            and inventory.provider_calls == 0 and inventory.broker_submits == 0
            and inventory.live_artifacts == 0,
        "serialized_replay_hashes": bundle.bundle_hash.startswith("sha256:")
            and bundle.replay.replay_hash.startswith("sha256:"),
        "hard_boundaries_pass": all(item == "killed"
            for item in hard_boundaries.values()),
    }
    result = report("v15.prd04_acceptance.3", checks, mutations,
        {"bundle_hash": bundle.bundle_hash,
            "replay_hash": bundle.replay.replay_hash,
            "retirement_tail_hash": bundle.retirement_registry.tail_hash,
            "report_inventory_hash": bundle.replay.report_inventory_hash})
    result["hard_boundaries"] = {key: value
        for key, value in hard_boundaries.items()}
    result["hard_boundary_count"] = len(hard_boundaries)
    result["report_hash"] = canonical_hash({key: value for key, value
        in result.items() if key != "report_hash"})
    return result


def run_acceptance() -> JsonValue:
    return evaluate(load_verified_bundle())
