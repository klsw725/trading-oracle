from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from src.v11.canonical import canonical_hash, model_json
from src.v4.models import JsonValue

from .acceptance_fixture import load_verified_bundle
from .acceptance_report import JsonRecord, MutationState, report
from .contract import V15Failure, V15FailureCode
from .liquidation import ScopeLevel
from .market_operation import build_market_operation
from .operation_models import OperationBundle, material_from_bundle
from .operation_replay import replay
from .recovery import KillKind
from .risk_monitor import evaluate_daily_loss, seal_mark
from .states import KillOverlay


def _killed(action: Callable[[], None]) -> MutationState:
    try:
        action()
    except V15Failure:
        return "killed"
    return "survived"


def _replay(bundle: OperationBundle) -> None:
    _ = replay(material_from_bundle(bundle))


def _replace_market(
    bundle: OperationBundle, market_index: int,
) -> OperationBundle:
    baseline = build_market_operation(bundle.source,
        bundle.source.markets[market_index], bundle.upstream,
        bundle.source.prior_retirement_registry)
    markets = list(bundle.markets)
    markets[market_index] = baseline
    return bundle.model_copy(update={"markets": tuple(markets)})


def _is_ordinary(account_namespace: str, event_entity: str) -> bool:
    suffix = event_entity.removeprefix(f"{account_namespace}:")
    return len(suffix) >= 11 and suffix[4] == "-" and suffix[7] == "-"


def evaluate(bundle: OperationBundle) -> JsonRecord:
    bad_loss = bundle.loss_results[0].model_copy(update={
        "net_pnl": Decimal("-1000"), "loss_fraction": Decimal("0.01"),
        "triggered": False})
    loss_bundle = bundle.model_copy(update={"loss_results": (bad_loss,)})
    mark = bundle.pnl_marks[0]
    unrelated_tail = bundle.markets[1].mirror_ledgers[0].events[0].event_hash
    stale_mark = seal_mark(mark.model_copy(update={
        "ledger_tail_hash": str(unrelated_tail)}))
    stale_mark_bundle = bundle.model_copy(update={
        "pnl_marks": (stale_mark,),
        "loss_results": (evaluate_daily_loss(stale_mark),)})
    economic_ledger = bundle.markets[0].mirror_ledgers[0]
    economic_day = economic_ledger.days[0]
    stale_day = economic_day.model_copy(update={
        "net_return": economic_day.net_return + Decimal("0.001")})
    stale_ledger = economic_ledger.model_copy(update={"days": (
        stale_day, *economic_ledger.days[1:]), "ledger_hash": ""})
    stale_ledger = stale_ledger.model_copy(update={"ledger_hash": canonical_hash({
        "account": model_json(stale_ledger.account),
        "initial_cash": stale_ledger.initial_cash,
        "events": [model_json(event) for event in stale_ledger.events],
        "replay_state": model_json(stale_ledger.replay_state),
        "days": [model_json(day) for day in stale_ledger.days]})})
    economic_market = bundle.markets[0].model_copy(update={"mirror_ledgers": (
        stale_ledger, bundle.markets[0].mirror_ledgers[1])})
    economic_bundle = bundle.model_copy(update={"markets": (
        economic_market, bundle.markets[1])})
    arm_execution = next(item for item in bundle.kill_executions
        if item.scope.level is ScopeLevel.ARM)
    arm_index = bundle.kill_executions.index(arm_execution)
    account = arm_execution.accounts[0]
    truncated_account = account.model_copy(update={"events":
        account.events[:account.before_event_count]})
    truncated_execution = arm_execution.model_copy(update={
        "accounts": (truncated_account,)})
    executions = list(bundle.kill_executions)
    executions[arm_index] = truncated_execution
    flatten_bundle = bundle.model_copy(update={"kill_executions": tuple(executions)})
    operation_recovery = next(item for item in bundle.recoveries
        if item.kind is KillKind.OPERATION and item.approval is not None)
    approval = operation_recovery.approval
    if approval is None:
        raise V15Failure(V15FailureCode.RECOVERY_BLOCKED, "missing approval")
    forged_approval = approval.model_copy(
        update={"approval_hash": "sha256:forged"})
    forged_recovery = operation_recovery.model_copy(update={"approval": forged_approval})
    recoveries = tuple(forged_recovery if item == operation_recovery else item
        for item in bundle.recoveries)
    approval_bundle = bundle.model_copy(update={"recoveries": recoveries})
    symbol_execution = next(item for item in bundle.kill_executions
        if item.scope.level is ScopeLevel.SYMBOL)
    escalated = symbol_execution.model_copy(update={"scope":
        symbol_execution.scope.model_copy(update={"level": ScopeLevel.MARKET})})
    escalated_items = tuple(escalated if item == symbol_execution else item
        for item in bundle.kill_executions)
    scope_bundle = bundle.model_copy(update={"kill_executions": escalated_items})
    recovery = bundle.recoveries[0]
    recovery_account = recovery.accounts[0]
    truncated_recovery = recovery_account.model_copy(update={"events":
        recovery_account.events[:-1]})
    bad_recovery = recovery.model_copy(update={"accounts": (
        truncated_recovery, *recovery.accounts[1:])})
    recovery_bundle = bundle.model_copy(update={"recoveries": (
        bad_recovery, *bundle.recoveries[1:])})
    mutations: dict[str, MutationState] = {
        "daily_economics_and_loss_mark_lineage_e2e": "killed" if all(
            _killed(action) == "killed" for action in (
                lambda: _replay(loss_bundle),
                lambda: _replay(stale_mark_bundle),
                lambda: _replay(economic_bundle))) else "survived",
        "kill_and_recovery_chain_truncation_e2e": "killed" if all(
            _killed(action) == "killed" for action in (
                lambda: _replay(flatten_bundle),
                lambda: _replay(recovery_bundle),
                lambda: _replay(_replace_market(bundle, 0)))) else "survived",
        "operation_recovery_approval_forgery_e2e": _killed(
            lambda: _replay(approval_bundle)),
        "isolated_symbol_escalates_market_e2e": _killed(
            lambda: _replay(scope_bundle)),
    }
    symbol_accounts = symbol_execution.accounts
    scoped = {item.scope.level: item for item in bundle.kill_executions}
    checks = {
        "net_mtm_loss_binds_incident": bundle.loss_results[0].loss_fraction
            == Decimal("0.021") and bundle.loss_results[0].triggered
            and bundle.loss_results[0].decision_hash
                == scoped[ScopeLevel.ARM].incident_input_hash
            and bundle.pnl_marks[0].ledger_tail_hash in {
                str(event.event_hash) for event in bundle.markets[0]
                    .mirror_ledgers[0].events},
        "actual_cancel_and_next_minute_flatten": all(item.flatten_at
            > item.boundary_at and all(account.cancelled_intents
                and account.flattened_symbols for account in item.accounts)
            for item in bundle.kill_executions),
        "arm_market_global_replay_flat": all(not account.after_state.positions
            and not account.after_state.open_intents
            for level in (ScopeLevel.ARM, ScopeLevel.MARKET, ScopeLevel.GLOBAL)
            for account in scoped[level].accounts),
        "same_session_entries_blocked": all(item.entries_blocked
            and item.same_session_reentry_blocked
            for item in bundle.kill_executions),
        "symbol_scope_both_arms_target_only": len(symbol_accounts) == 2
            and {item.account_namespace for item in symbol_accounts}
                == set(symbol_execution.scope.affected_accounts)
            and all({position.symbol for position in item.before_state.positions}
                    == {"005930", f"KR:{arm}:NORMAL"}
                and {position.symbol for position in item.after_state.positions}
                    == {f"KR:{arm}:NORMAL"}
                and item.flattened_symbols == ("005930",)
                for item, arm in zip(symbol_accounts,
                    ("orb", "router"), strict=True)),
        "scope_account_counts": len(scoped[ScopeLevel.SYMBOL].accounts) == 2
            and len(scoped[ScopeLevel.ARM].accounts) == 1
            and len(scoped[ScopeLevel.MARKET].accounts) == 2
            and len(scoped[ScopeLevel.GLOBAL].accounts) == 4,
        "recovery_exact_next_sessions": all(item.recovery_session
            > item.incident_session for item in bundle.recoveries),
        "operation_recovery_real_approval": all(item.approval is not None
            and not item.approval.automatic for item in bundle.recoveries
            if item.kind is KillKind.OPERATION),
        "kill_chains_extend_real_mirror_prefixes": all(
            account.events[:account.source_prefix_event_count]
                == next(ledger.events[:account.source_prefix_event_count]
                    for market in bundle.markets
                    for ledger in market.mirror_ledgers
                    if ledger.account.account_namespace
                        == account.account_namespace)
            for execution in bundle.kill_executions
            for account in execution.accounts),
        "recovery_replays_flat_unhalted_clear": all(
            account.events[:len(killed.events)] == killed.events
            and not account.post_recovery_state.halted
            and not account.post_recovery_state.positions
            and not account.post_recovery_state.open_intents
            and account.reset_event_hash == str(account.events[-6].event_hash)
            and account.reconciliation_event_hash == str(
                account.events[-1].event_hash)
            for recovery in bundle.recoveries
            for account, killed in zip(recovery.accounts,
                next(item.accounts for item in bundle.kill_executions
                    if item.execution_hash == recovery.execution_hash), strict=True)),
        "canonical_ledgers_splice_kill_recovery_and_resume": all(
            (recovery := next((item for item in bundle.recoveries
                if item.execution_hash == execution.execution_hash), None))
                is not None
            and all((ledger := next(item for market in bundle.markets
                    for item in market.mirror_ledgers
                    if item.account.account_namespace
                        == account.account_namespace)).events[:len(account.events)]
                    == account.events
                and (recovered := next(item for item in recovery.accounts
                    if item.account_namespace == account.account_namespace))
                    .events[:len(account.events)] == account.events
                and ledger.events[:len(recovered.events)] == recovered.events
                and not any(_is_ordinary(account.account_namespace,
                    event.entity_id) for event in ledger.events
                    if execution.boundary_at < event.occurred_at
                    < next(item.occurred_at for item in ledger.events
                        if str(item.event_hash)
                            == recovered.reconciliation_event_hash))
                and next(event for event in ledger.events
                    if event.event_index == len(recovered.events))
                    .previous_event_hash == ledger.events[
                        len(recovered.events) - 1].event_hash
                for account in execution.accounts)
            for execution in bundle.kill_executions),
        "kill_overlays_cover_scopes": {item.overlay for item in bundle.incidents}
            >= {KillOverlay.SYMBOL_BLOCKED, KillOverlay.ARM_LOSS_KILLED,
                KillOverlay.MARKET_OPERATION_KILLED,
                KillOverlay.GLOBAL_OPERATION_KILLED},
    }
    return report("v15.prd03_acceptance.3", checks, mutations,
        {"loss_decision_hash": bundle.loss_results[0].decision_hash,
            "symbol_execution_hash": scoped[ScopeLevel.SYMBOL].execution_hash,
            "arm_execution_hash": scoped[ScopeLevel.ARM].execution_hash,
            "market_execution_hash": scoped[ScopeLevel.MARKET].execution_hash,
            "global_execution_hash": scoped[ScopeLevel.GLOBAL].execution_hash})


def run_acceptance() -> JsonValue:
    return evaluate(load_verified_bundle())
