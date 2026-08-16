from __future__ import annotations

from datetime import UTC, date, datetime, time

from .approvals import Approval
from .incidents import IncidentRecord
from .liquidation import KillExecution
from .operation_models import EventSpec, MarketOperation
from .recovery import RecoveryEvidence
from .retirement import RetirementRegistry
from .states import (
    GENESIS_HASH,
    KillOverlay,
    LifecycleState,
    OperationEvent,
    OperationEventBody,
    OperationEventType,
    append_event,
)


def build_events(
    markets: tuple[MarketOperation, MarketOperation],
    approvals: tuple[Approval, Approval],
    executions: tuple[KillExecution, ...],
    incidents: tuple[IncidentRecord, ...],
    recoveries: tuple[RecoveryEvidence, ...],
    registry: RetirementRegistry,
    manifest_hash: str,
) -> tuple[OperationEvent, ...]:
    specs: list[EventSpec] = []
    for market, approval in zip(markets, approvals, strict=True):
        specs.extend(_market_specs(market, approval, registry))
    for execution, incident in zip(executions, incidents, strict=True):
        specs.extend(_kill_specs(execution, incident, recoveries))
    specs.sort(key=lambda item: (item.occurred_at, item.market or "", item.arm or ""))
    events: tuple[OperationEvent, ...] = ()
    for spec in specs:
        body = OperationEventBody(schema_version="v15.operation_event.2",
            sequence=len(events) + 1, event_type=spec.event_type,
            market=spec.market, arm=spec.arm, symbol=spec.symbol,
            session=spec.session, occurred_at=spec.occurred_at,
            manifest_hash=manifest_hash, evidence_refs=spec.evidence_refs,
            detail_hash=spec.detail_hash,
            lifecycle_before=spec.lifecycle_before,
            lifecycle_after=spec.lifecycle_after,
            kill_before=spec.kill_before, kill_after=spec.kill_after,
            previous_hash=events[-1].event_hash if events else GENESIS_HASH)
        events = append_event(events, body)
    return events


def _market_specs(
    market: MarketOperation, approval: Approval,
    registry: RetirementRegistry,
) -> tuple[EventSpec, ...]:
    schedule = market.schedule
    qualification_session = schedule.qualification_sessions[0]
    challenger = schedule.challenger_session
    primary = schedule.router_primary_session
    final = schedule.comparison_sessions[-1]
    qualification = market.orb_qualification
    qualification_refs = (qualification.evidence_hash,
        qualification.ledger.ledger_hash)
    approval_refs = (approval.approval_hash,
        *(item.evidence_hash for item in approval.data_exceptions))
    seeds = [
        ("orb", qualification_session, 9, 0, LifecycleState.ORB_CANDIDATE,
            LifecycleState.ORB_HOLDOUT_PASSED, approval.approval_hash,
            approval_refs),
        ("orb", qualification_session, 9, 1, LifecycleState.ORB_HOLDOUT_PASSED,
            LifecycleState.ORB_PAPER, approval.approval_hash,
            approval_refs),
        ("strategies", challenger, 9, 0,
            LifecycleState.STRATEGIES_CANDIDATE,
            LifecycleState.STRATEGIES_SHADOW,
            qualification.evidence_hash, qualification_refs),
        ("router", challenger, 9, 1, LifecycleState.ROUTER_CANDIDATE,
            LifecycleState.ROUTER_SHADOW,
            qualification.evidence_hash, qualification_refs),
        ("router", challenger, 9, 2, LifecycleState.ROUTER_SHADOW,
            LifecycleState.ROUTER_CHALLENGER,
            qualification.evidence_hash, qualification_refs)]
    winner = market.router_winner
    if primary is not None and winner is not None:
        seeds.append(("router", primary, 9, 0,
            LifecycleState.ROUTER_CHALLENGER,
            LifecycleState.ROUTER_PRIMARY, winner.winner_hash,
            (winner.winner_hash,)))
    rollback = market.performance_rollback
    if rollback is not None:
        retirement = next(item for item in registry.records
            if item.market == market.market
            and item.router_version == rollback.router_version)
        seeds.extend((("router", final, 16, 0,
            LifecycleState.ROUTER_PRIMARY,
            LifecycleState.ROUTER_PERFORMANCE_ROLLBACK,
            rollback.evidence_hash, (rollback.evidence_hash,)),
            ("router", final, 16, 1,
                LifecycleState.ROUTER_PERFORMANCE_ROLLBACK,
                LifecycleState.ROUTER_RETIRED, retirement.record_hash,
                (retirement.record_hash,))))
    return tuple(EventSpec(event_type=OperationEventType.LIFECYCLE,
        market=market.market, arm=arm, symbol=None, session=session,
        occurred_at=_at(session, hour, minute), evidence_refs=refs,
        detail_hash=detail, lifecycle_before=before, lifecycle_after=after,
        kill_before=KillOverlay.CLEAR, kill_after=KillOverlay.CLEAR)
        for arm, session, hour, minute, before, after, detail, refs in seeds)


def _kill_specs(
    execution: KillExecution, incident: IncidentRecord,
    recoveries: tuple[RecoveryEvidence, ...],
) -> tuple[EventSpec, ...]:
    scope = execution.scope
    arm = f"scope:{scope.scope_hash[-12:]}"
    market = scope.market
    session = incident.session
    event_type = OperationEventType.LOSS_KILL \
        if incident.overlay is KillOverlay.ARM_LOSS_KILLED \
        else OperationEventType.OPERATION_KILL
    base = (EventSpec(event_type=event_type, market=market, arm=arm,
        symbol=scope.symbol, session=session,
        occurred_at=execution.boundary_at,
        evidence_refs=(incident.incident_hash, execution.execution_hash),
        detail_hash=incident.incident_hash,
        lifecycle_before=LifecycleState.ORB_PAPER,
        lifecycle_after=LifecycleState.ORB_PAPER,
        kill_before=KillOverlay.CLEAR, kill_after=incident.overlay),
        EventSpec(event_type=OperationEventType.CANCEL, market=market, arm=arm,
            symbol=scope.symbol, session=session,
            occurred_at=execution.boundary_at,
            evidence_refs=(execution.execution_hash,),
            detail_hash=execution.execution_hash,
            lifecycle_before=LifecycleState.ORB_PAPER,
            lifecycle_after=LifecycleState.ORB_PAPER,
            kill_before=incident.overlay, kill_after=incident.overlay),
        EventSpec(event_type=OperationEventType.FLATTEN, market=market, arm=arm,
            symbol=scope.symbol, session=session,
            occurred_at=execution.flatten_at,
            evidence_refs=(execution.execution_hash,),
            detail_hash=execution.execution_hash,
            lifecycle_before=LifecycleState.ORB_PAPER,
            lifecycle_after=LifecycleState.ORB_PAPER,
            kill_before=incident.overlay, kill_after=incident.overlay))
    recovery = next((item for item in recoveries
        if item.incident_hash == incident.incident_hash), None)
    if recovery is None:
        return base
    return (*base, EventSpec(event_type=OperationEventType.RECOVERY,
        market=market, arm=arm, symbol=scope.symbol,
        session=recovery.recovery_session,
        occurred_at=_at(recovery.recovery_session, 9, 0),
        evidence_refs=(recovery.recovery_hash,),
        detail_hash=recovery.recovery_hash,
        lifecycle_before=LifecycleState.ORB_PAPER,
        lifecycle_after=LifecycleState.ORB_PAPER,
        kill_before=incident.overlay, kill_after=KillOverlay.CLEAR))


def _at(session: date, hour: int, minute: int) -> datetime:
    return datetime.combine(session, time(hour=hour, minute=minute), UTC)
