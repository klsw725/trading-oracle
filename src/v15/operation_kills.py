from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from src.v11.canonical import canonical_hash, decimal_value, model_json
from src.v11.replay import replay as replay_v11

from .canonical_ledgers import finalize_canonical_ledgers, splice_kill_recovery
from .approvals import (
    ApprovalPurpose,
    ApprovalRequest,
    consume_manual_approval,
)
from .contract import StrictModel
from .incidents import IncidentBody, IncidentRecord, build_incident
from .kill_switch import TriggerKind, classify_trigger
from .liquidation import (
    ExecutionCommand,
    ExecutionScope,
    KillExecution,
    LedgerInput,
    ScopeLevel,
    execute_kill,
)
from .operation_fixture import OperationSourceFixture
from .operation_models import MarketOperation, MirrorLedger
from .market_operation import rebuild_market_operation
from .recovery import (
    KillKind,
    RecoveryEvidence,
    build_account_recoveries,
    recovery_replay_hash,
)
from .risk_monitor import LossResult, PnlMark, evaluate_daily_loss, seal_mark
from .upstream import UpstreamEvidence


class KillInventory(StrictModel):
    markets: Annotated[tuple[MarketOperation, MarketOperation],
        Field(strict=False)]
    pnl_marks: Annotated[tuple[PnlMark, ...], Field(strict=False)]
    loss_results: Annotated[tuple[LossResult, ...], Field(strict=False)]
    executions: Annotated[tuple[KillExecution, ...], Field(strict=False)]
    incidents: Annotated[tuple[IncidentRecord, ...], Field(strict=False)]
    recoveries: Annotated[tuple[RecoveryEvidence, ...], Field(strict=False)]


def build_kill_inventory(
    source: OperationSourceFixture,
    markets: tuple[MarketOperation, MarketOperation],
    upstream: UpstreamEvidence,
) -> KillInventory:
    kr, us = markets
    all_ledgers = tuple(ledger for market in markets
        for ledger in market.mirror_ledgers)
    all_accounts = tuple(ledger.account for ledger in all_ledgers)
    kr_orb = kr.mirror_ledgers[0]
    arm_scope = _scope(ScopeLevel.ARM, "KR", "orb", None,
        (kr_orb.account.account_namespace,))
    kr_accounts = tuple(ledger.account.account_namespace
        for ledger in kr.mirror_ledgers)
    symbol_scope = _scope(ScopeLevel.SYMBOL, "KR", None, "005930",
        kr_accounts)
    us_accounts = tuple(ledger.account.account_namespace
        for ledger in us.mirror_ledgers)
    market_scope = _scope(ScopeLevel.MARKET, "US", None, None, us_accounts)
    global_scope = _scope(ScopeLevel.GLOBAL, None, None, None,
        tuple(item.account_namespace for item in all_accounts))
    specs = ((symbol_scope, TriggerKind.SYMBOL_DATA,
            kr.schedule.comparison_sessions[10], canonical_hash({"symbol": "005930"})),
        (arm_scope, TriggerKind.ARM_DAILY_LOSS, kr.schedule.loss_kill_session,
            None),
        (market_scope, TriggerKind.MARKET_SOURCE,
            us.schedule.comparison_sessions[65], canonical_hash({"market": "US"})),
        (global_scope, TriggerKind.GLOBAL_HASH_CHAIN,
            _common_session(markets, 67), canonical_hash({"scope": "global"})))
    executions: list[KillExecution] = []
    incidents: list[IncidentRecord] = []
    recoveries: list[RecoveryEvidence] = []
    marks: list[PnlMark] = []
    losses: list[LossResult] = []
    canonical_markets = markets
    for scope, trigger, session, input_hash in specs:
        all_ledgers = tuple(ledger for market in canonical_markets
            for ledger in market.mirror_ledgers)
        if input_hash is None:
            affected = next(ledger for ledger in all_ledgers
                if ledger.account.account_namespace == scope.affected_accounts[0])
            mark, loss = _loss_mark(scope, affected, session)
            marks.append(mark)
            losses.append(loss)
            input_hash = loss.decision_hash
        execution = execute_kill(ExecutionCommand(scope=scope,
            incident_input_hash=input_hash, boundary_at=_at(session, 10, 0),
            ledgers=tuple(LedgerInput(account=ledger.account,
                initial_cash=ledger.initial_cash, events=ledger.events,
                ledger_hash=ledger.ledger_hash) for ledger in all_ledgers)))
        body = IncidentBody(schema_version="v15.incident.2", trigger=trigger,
            overlay=classify_trigger(trigger), scope=execution.scope,
            session=session, input_hash=input_hash,
            manifest_hash=upstream.policy.manifest_hash,
            affected_accounts=execution.scope.affected_accounts,
            execution_hash=execution.execution_hash,
            critical_codes=(trigger.value,))
        executions.append(execution)
        incident = build_incident(body, execution)
        incidents.append(incident)
        match scope.level:  # noqa: MATCH_OK - ScopeLevel exhaustively covered
            case ScopeLevel.SYMBOL:
                recovery = _recovery(KillKind.OPERATION, incident, execution,
                    canonical_markets[0], source, upstream, "symbol recovery")
            case ScopeLevel.ARM:
                recovery = _recovery(KillKind.LOSS, incident, execution,
                    canonical_markets[0], source, upstream, None)
            case ScopeLevel.MARKET:
                recovery = _recovery(KillKind.OPERATION, incident, execution,
                    canonical_markets[1], source, upstream, "market recovery")
            case ScopeLevel.GLOBAL:
                recovery = _global_recovery(incident, execution,
                    canonical_markets, source, upstream)
        recoveries.append(recovery)
        canonical_markets = splice_kill_recovery(canonical_markets,
            execution, recovery)
    finalized = finalize_canonical_ledgers(canonical_markets)
    rebuilt = tuple(rebuild_market_operation(market, source)
        for market in finalized)
    canonical = (rebuilt[0], rebuilt[1])
    return KillInventory(markets=canonical,
        pnl_marks=tuple(marks), loss_results=tuple(losses),
        executions=tuple(executions), incidents=tuple(incidents),
        recoveries=tuple(recoveries))


def _loss_mark(
    scope: ExecutionScope, ledger: MirrorLedger, session: date,
) -> tuple[PnlMark, LossResult]:
    boundary = _at(session, 10, 0)
    prefix = tuple(event for event in ledger.events
        if event.occurred_at < boundary)
    state = replay_v11(prefix, ledger.initial_cash)
    prior_nav = decimal_value(state.cash)
    unit_cost = prior_nav * Decimal("0.0005")
    mark = seal_mark(PnlMark(schema_version="v15.pnl_mark.3",
        scope=scope, account_namespace=ledger.account.account_namespace,
        account_state_hash=canonical_hash(model_json(state)),
        session=session, boundary_at=boundary,
        ledger_tail_hash=str(prefix[-1].event_hash),
        prior_close_nav=prior_nav,
        realized_pnl=-prior_nav * Decimal("0.01"),
        unrealized_pnl=-prior_nav * Decimal("0.007"),
        commission=unit_cost, tax=unit_cost, spread=unit_cost,
        slippage=unit_cost, participation=unit_cost,
        borrow=unit_cost, locate=unit_cost,
        other_execution_cost=unit_cost, mark_hash=""))
    return mark, evaluate_daily_loss(mark)


def _recovery(
    kind: KillKind, incident: IncidentRecord, execution: KillExecution,
    market: MarketOperation, source: OperationSourceFixture,
    upstream: UpstreamEvidence, reason: str | None,
) -> RecoveryEvidence:
    sessions = market.schedule.comparison_sessions
    recovery_session = sessions[sessions.index(incident.session) + 1]
    approval = None
    if reason is not None:
        request = ApprovalRequest(schema_version="v15.approval_request.3",
            previous_identity=upstream.policy, current_identity=upstream.policy,
            effective_session=recovery_session,
            purpose=ApprovalPurpose.RECOVERY, reason=reason,
            data_exceptions=())
        approval = consume_manual_approval(source.manual_approvals, request)
    accounts = build_account_recoveries(execution, recovery_session)
    draft = RecoveryEvidence(schema_version="v15.recovery_evidence.4",
        kind=kind, incident_hash=incident.incident_hash,
        incident_session=incident.session, recovery_session=recovery_session,
        calendar_hash=market.schedule.calendar_hash,
        original_identity=upstream.policy, current_identity=upstream.policy,
        execution_hash=execution.execution_hash,
        actual_replay_hash=recovery_replay_hash(accounts), accounts=accounts,
        approval=approval, recovery_hash="")
    return draft.model_copy(update={"recovery_hash": canonical_hash(
        model_json(draft))})


def _global_recovery(
    incident: IncidentRecord, execution: KillExecution,
    markets: tuple[MarketOperation, MarketOperation],
    source: OperationSourceFixture, upstream: UpstreamEvidence,
) -> RecoveryEvidence:
    common = sorted(set(markets[0].schedule.comparison_sessions)
        & set(markets[1].schedule.comparison_sessions))
    recovery = next(session for session in common if session > incident.session)
    request = ApprovalRequest(schema_version="v15.approval_request.3",
        previous_identity=upstream.policy, current_identity=upstream.policy,
        effective_session=recovery, purpose=ApprovalPurpose.RECOVERY,
        reason="global recovery", data_exceptions=())
    approval = consume_manual_approval(source.manual_approvals, request)
    accounts = build_account_recoveries(execution, recovery)
    draft = RecoveryEvidence(schema_version="v15.recovery_evidence.4",
        kind=KillKind.OPERATION, incident_hash=incident.incident_hash,
        incident_session=incident.session, recovery_session=recovery,
        calendar_hash=canonical_hash([item.schedule.calendar_hash
            for item in markets]), original_identity=upstream.policy,
        current_identity=upstream.policy,
        execution_hash=execution.execution_hash,
        actual_replay_hash=recovery_replay_hash(accounts), accounts=accounts,
        approval=approval, recovery_hash="")
    return draft.model_copy(update={"recovery_hash": canonical_hash(
        model_json(draft))})


def _scope(
    level: ScopeLevel, market: Literal["KR", "US"] | None,
    arm: Literal["orb", "router"] | None,
    symbol: str | None, accounts: tuple[str, ...],
) -> ExecutionScope:
    return ExecutionScope(schema_version="v15.execution_scope.1",
        level=level, market=market, arm=arm, symbol=symbol,
        affected_accounts=accounts, scope_hash="")


def _common_session(
    markets: tuple[MarketOperation, MarketOperation], minimum_index: int
) -> date:
    common = sorted(set(markets[0].schedule.comparison_sessions[minimum_index:])
        & set(markets[1].schedule.comparison_sessions[minimum_index:]))
    return common[0]


def _at(session: date, hour: int, minute: int) -> datetime:
    return datetime.combine(session, time(hour=hour, minute=minute), UTC)
