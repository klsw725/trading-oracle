from __future__ import annotations

from src.v11.canonical import canonical_hash, decimal_value, model_json
from src.v11.replay import replay as replay_v11

from .activation import activation_request
from .approvals import verify_approval, verify_manual_approval_consumption
from .contract import V15Failure, V15FailureCode
from .effects import verify_paper_effects
from .incidents import verify_incident
from .liquidation import (
    LedgerInput,
    ScopeLevel,
    verify_execution,
    verify_execution_sources,
)
from .market_operation import build_market_operation
from .operation_fixture import verify_source
from .operation_models import OperationMaterial, ReplayResult, ReplayResultBody
from .operation_kills import build_kill_inventory
from .operation_reports import build_reports
from .paper_boundary import verify_paper_boundary
from .qualification import verify_orb_qualification
from .observability import verify_llm_ledger, verify_llm_report
from .recovery import recover
from .retirement import verify_registry
from .risk_monitor import PnlMark, evaluate_daily_loss
from .states import verify_chain
from .v11_mirror_ledger import verify_mirror_ledger


def replay(material: OperationMaterial) -> ReplayResult:
    verify_paper_boundary({"destination": material.source.destination})
    verify_source(material.source)
    if tuple(item.market for item in material.markets) != ("KR", "US"):
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "market_inventory")
    for approval, market in zip(material.approvals, material.markets, strict=True):
        request = activation_request(market, material.source, material.upstream)
        verify_approval(approval, request)
        if approval.approved_at != material.upstream.gate_available_at:
            raise V15Failure(V15FailureCode.APPROVAL_MISMATCH,
                approval.approval_hash)
    for market in material.markets:
        verify_orb_qualification(market.orb_qualification,
            market.schedule, material.upstream)
        for ledger in market.mirror_ledgers:
            verify_mirror_ledger(ledger)
    for mark, result in zip(material.pnl_marks,
            material.loss_results, strict=True):
        _verify_loss_mark(mark, material)
        if evaluate_daily_loss(mark) != result:
            raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "loss_result")
    if len(material.kill_executions) != len(material.incidents):
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "kill_inventory")
    ledger_inputs = tuple(LedgerInput(account=ledger.account,
        initial_cash=ledger.initial_cash, events=ledger.events,
        ledger_hash=ledger.ledger_hash) for market in material.markets
        for ledger in market.mirror_ledgers)
    for execution, incident in zip(material.kill_executions,
            material.incidents, strict=True):
        verify_execution(execution)
        verify_execution_sources(execution, ledger_inputs)
        verify_incident(incident, execution)
    _verify_recoveries(material)
    consumed = tuple(item for item in material.approvals if not item.automatic) \
        + tuple(item.approval for item in material.recoveries
            if item.approval is not None)
    verify_manual_approval_consumption(material.source.manual_approvals,
        consumed)
    verify_registry(material.retirement_registry)
    prior = material.source.prior_retirement_registry
    if material.retirement_registry.records[:len(prior.records)] != prior.records:
        raise V15Failure(V15FailureCode.CHAIN_MISMATCH, "retirement_history")
    for market in material.markets:
        record = next((item for item in material.retirement_registry.records
            if item.market == market.market
            and item.router_version == material.source.policy_version), None)
        rollback = market.performance_rollback
        if rollback is None and record is not None:
            raise V15Failure(V15FailureCode.VERSION_RETIRED, market.market)
        if rollback is not None and (record is None
                or record.evidence_hash != rollback.evidence_hash):
            raise V15Failure(V15FailureCode.VERSION_RETIRED, market.market)
    chain_hash = verify_chain(material.events)
    event_refs = {ref for event in material.events for ref in event.evidence_refs}
    required_refs = {item.approval_hash for item in material.approvals} \
        | {exception.evidence_hash for item in material.approvals
            for exception in item.data_exceptions} \
        | {item.orb_qualification.evidence_hash for item in material.markets} \
        | {item.orb_qualification.ledger.ledger_hash
            for item in material.markets} \
        | {item.execution_hash for item in material.kill_executions} \
        | {item.incident_hash for item in material.incidents} \
        | {item.recovery_hash for item in material.recoveries} \
        | {item.record_hash for item in material.retirement_registry.records[
            len(material.source.prior_retirement_registry.records):]} \
        | {item.router_winner.winner_hash for item in material.markets
            if item.router_winner is not None}
    if not required_refs <= event_refs:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "event_evidence")
    for ledger in material.llm_outcomes:
        verify_llm_ledger(ledger)
    rebuilt_reports = build_reports(material.markets, material.llm_outcomes,
        material.incidents, material.kill_executions, material.recoveries,
        material.upstream.policy.manifest_hash, material.source.policy_version)
    if rebuilt_reports != material.session_reports:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "reports")
    for report in material.session_reports:
        ledger = next(item for item in material.llm_outcomes
            if item.market == report.market)
        prefix = ledger.model_copy(update={"outcomes": tuple(item
            for item in ledger.outcomes if item.session == report.session)})
        verify_llm_report(report, prefix)
    baseline_markets = tuple(build_market_operation(material.source,
        timeline, material.upstream, material.source.prior_retirement_registry)
        for timeline in material.source.markets)
    baseline = (baseline_markets[0], baseline_markets[1])
    rebuilt_kills = build_kill_inventory(material.source, baseline,
        material.upstream)
    if rebuilt_kills.markets != material.markets \
            or rebuilt_kills.pnl_marks != material.pnl_marks \
            or rebuilt_kills.loss_results != material.loss_results \
            or rebuilt_kills.executions != material.kill_executions \
            or rebuilt_kills.incidents != material.incidents \
            or rebuilt_kills.recoveries != material.recoveries:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "market_operations")
    side_effects = verify_paper_effects(material.effects)
    report_hash = canonical_hash([model_json(item)
        for item in material.session_reports])
    kill_hash = canonical_hash([item.execution_hash
        for item in material.kill_executions])
    current_records = material.retirement_registry.records[len(
        material.source.prior_retirement_registry.records):]
    retired = tuple(f"{item.market}:{item.router_version}"
        for item in current_records)
    states = tuple("router_retired" if market.performance_rollback is not None
        else "router_primary" if market.router_winner is not None
        else "router_challenger" for market in material.markets)
    final_state = "router_retired" if all(item == "router_retired"
        for item in states) else "router_primary" if any(
            item == "router_primary" for item in states) else "router_challenger"
    body = ReplayResultBody(schema_version="v15.replay_result.2",
        operation_chain_hash=chain_hash,
        paired_series_hashes=(material.markets[0].paired_series.series_hash,
            material.markets[1].paired_series.series_hash),
        winner_hashes=(material.markets[0].initial_winner.winner_hash,
            material.markets[1].initial_winner.winner_hash),
        final_router_state=final_state, retired_versions=retired,
        report_inventory_hash=report_hash, kill_inventory_hash=kill_hash,
        effect_ledger_hash=material.effects.ledger_hash,
        side_effect_inventory=side_effects)
    return ReplayResult(schema_version=body.schema_version,
        operation_chain_hash=body.operation_chain_hash,
        paired_series_hashes=body.paired_series_hashes,
        winner_hashes=body.winner_hashes,
        final_router_state=body.final_router_state,
        retired_versions=body.retired_versions,
        report_inventory_hash=body.report_inventory_hash,
        kill_inventory_hash=body.kill_inventory_hash,
        effect_ledger_hash=body.effect_ledger_hash,
        side_effect_inventory=body.side_effect_inventory,
        replay_hash=canonical_hash(model_json(body)))


def _verify_recoveries(material: OperationMaterial) -> None:
    expected_hashes = {item.execution_hash for item in material.kill_executions}
    observed_hashes = tuple(item.execution_hash for item in material.recoveries)
    if set(observed_hashes) != expected_hashes \
            or len(observed_hashes) != len(expected_hashes) \
            or len({item.incident_hash for item in material.recoveries}) \
                != len(material.recoveries):
        raise V15Failure(V15FailureCode.RECOVERY_BLOCKED,
            "recovery_inventory")
    executions = {item.execution_hash: item for item in material.kill_executions}
    incidents = {item.incident_hash: item for item in material.incidents}
    for evidence in material.recoveries:
        execution = executions.get(evidence.execution_hash)
        incident = incidents.get(evidence.incident_hash)
        if execution is None or incident is None:
            raise V15Failure(V15FailureCode.RECOVERY_BLOCKED,
                "recovery_lineage")
        if execution.scope.level is ScopeLevel.GLOBAL:
            common = sorted(set(material.markets[0].schedule.comparison_sessions)
                & set(material.markets[1].schedule.comparison_sessions))
            expected = next((item for item in common
                if item > incident.session), None)
        else:
            market = next((item for item in material.markets
                if item.market == execution.scope.market), None)
            if market is None:
                raise V15Failure(V15FailureCode.RECOVERY_BLOCKED,
                    "recovery_market")
            sessions = market.schedule.comparison_sessions
            try:
                expected = sessions[sessions.index(incident.session) + 1]
            except (ValueError, IndexError) as error:
                raise V15Failure(V15FailureCode.RECOVERY_BLOCKED,
                    "recovery_session") from error
        if expected is None:
            raise V15Failure(V15FailureCode.RECOVERY_BLOCKED,
                "recovery_session")
        _ = recover(evidence, expected, execution)


def _verify_loss_mark(mark: PnlMark, material: OperationMaterial) -> None:
    ledger = next((ledger for market in material.markets
        for ledger in market.mirror_ledgers
        if ledger.account.account_namespace == mark.account_namespace), None)
    if ledger is None:
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE, "loss_mark_account")
    prefix = tuple(event for event in ledger.events
        if event.occurred_at < mark.boundary_at)
    state = replay_v11(prefix, ledger.initial_cash)
    if not prefix or mark.account_namespace not in mark.scope.affected_accounts \
            or mark.ledger_tail_hash != str(prefix[-1].event_hash) \
            or mark.account_state_hash != canonical_hash(model_json(state)) \
            or mark.prior_close_nav != decimal_value(state.cash):
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE, "loss_mark_lineage")
