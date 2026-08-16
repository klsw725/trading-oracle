from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Literal

from src.v11.canonical import canonical_hash, model_json, money
from src.v11.ledger import verify_chain
from src.v11.models import EventType, LedgerEvent, V11ContractError
from src.v11.replay import replay as replay_v11
from src.v4.models import JsonValue

from .contract import V15Failure, V15FailureCode
from .canonical_ledgers import replay_day_economics
from .mirrors import MirrorAccount
from .operation_fixture import MarketSchedule, ReturnPolicy
from .operation_models import MirrorLedger
from .paired import ArmDay, DayKind, V11ExecutionEvidence
from .v11_event_writer import LedgerWriter


@dataclass(frozen=True, slots=True)
class MirrorBuildContext:
    mirror: MirrorAccount
    schedule: MarketSchedule
    sessions: tuple[date, ...]
    initial_nav: Decimal
    completed_trades_per_trade_day: int
    returns: ReturnPolicy
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class TradeSpec:
    entity_id: str
    occurred_at: datetime
    cash_delta: Decimal
    cost: Decimal
    halted: bool


def build_mirror_ledger(context: MirrorBuildContext) -> MirrorLedger:
    writer = LedgerWriter(context.manifest_hash)
    days: list[ArmDay] = []
    nav = context.initial_nav
    reset_entity: str | None = None
    for session in context.sessions:
        start = len(writer)
        if reset_entity is not None:
            writer.append(EventType.SESSION_CLOSED, reset_entity,
                _at(session, 9, 0), {"reset": True,
                    "semantic_key": "next_session_reset"})
            reset_entity = None
        kind = _day_kind(context.schedule, context.mirror.arm, session)
        completed = 0 if kind is DayKind.NO_TRADE \
            else context.completed_trades_per_trade_day
        net_return = _net_return(context, session, kind)
        execution_cost = Decimal(0) if kind is DayKind.NO_TRADE \
            else context.returns.router_execution_cost
        prior_nav = nav
        target_nav = prior_nav * (Decimal(1) + net_return)
        total_cost = Decimal(0)
        if kind is DayKind.NO_TRADE:
            entity = f"{context.mirror.account_namespace}:{session}:no-trade"
            writer.append(EventType.SIGNAL_OBSERVED, entity,
                _at(session, 10, 0), {"decision_id": entity,
                    "semantic_key": "no_trade"})
        else:
            total_cost = prior_nav * execution_cost
            final_cash_delta = target_nav - prior_nav + total_cost
            for index in range(completed):
                final = index == completed - 1
                entity = f"{context.mirror.account_namespace}:{session}:{index}"
                spec = TradeSpec(entity_id=entity,
                    occurred_at=_at(session, 10, index),
                    cash_delta=final_cash_delta
                        if final else Decimal(0),
                    cost=total_cost if final else Decimal(0),
                    halted=kind is DayKind.LOSS_KILL and final)
                _append_trade(writer, spec)
                if spec.halted:
                    reset_entity = entity
            nav = prior_nav + final_cash_delta - total_cost
        actual_net_return = (nav - prior_nav) / prior_nav
        actual_execution_cost = Decimal(0) if kind is DayKind.NO_TRADE \
            else total_cost / prior_nav
        day_events = _session_events(writer.since(start), session)
        first_event = day_events[0]
        last_event = day_events[-1]
        account = context.mirror.initial_account.model_copy(update={
            "prior_close_nav": money(nav), "cash": money(nav),
            "halted": kind is DayKind.LOSS_KILL})
        evidence = V11ExecutionEvidence(arm=context.mirror.arm,
            account_snapshot=account,
            account_hash=canonical_hash(model_json(account)),
            previous_event_hash=str(first_event.previous_event_hash),
            ledger_tail_hash=str(last_event.event_hash),
            event_hashes=tuple(str(event.event_hash) for event in day_events),
            fill_hashes=tuple(str(event.event_hash) for event in day_events
                if event.event_type is EventType.FILL_COMPLETE),
            manifest_hash=context.manifest_hash,
            risk_version=context.mirror.risk_version,
            cost_model=context.mirror.cost_model)
        days.append(ArmDay(session=session, kind=kind,
            net_return=actual_net_return,
            gross_return=actual_net_return + actual_execution_cost,
            execution_cost=actual_execution_cost,
            completed_trades=completed, evidence=evidence))
    events = writer.events
    state = replay_v11(events, money(context.initial_nav))
    draft = MirrorLedger(account=context.mirror,
        initial_cash=money(context.initial_nav), events=events,
        replay_state=state, days=tuple(days), ledger_hash="")
    return draft.model_copy(update={"ledger_hash": _ledger_hash(draft)})


def verify_mirror_ledger(ledger: MirrorLedger) -> None:
    try:
        verify_chain(ledger.events)
        state = replay_v11(ledger.events, ledger.initial_cash)
    except V11ContractError as error:
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
            str(error)) from error
    if ledger.ledger_hash != _ledger_hash(ledger) \
            or state != ledger.replay_state:
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
            ledger.account.account_namespace)
    hashes = tuple(str(event.event_hash) for event in ledger.events)
    bound = tuple(value for day in ledger.days
        for value in day.evidence.event_hashes)
    if hashes != bound:
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE, "daily_events")
    by_hash = {str(event.event_hash): event for event in ledger.events}
    for day in ledger.days:
        event_hashes = day.evidence.event_hashes
        fills = tuple(value for value in event_hashes
            if by_hash[value].event_type is EventType.FILL_COMPLETE)
        if day.evidence.previous_event_hash \
                != str(by_hash[event_hashes[0]].previous_event_hash) \
                or day.evidence.ledger_tail_hash != event_hashes[-1] \
                or day.evidence.fill_hashes != fills \
                or len(fills) != day.completed_trades:
            raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
                day.session.isoformat())
        if (day.net_return, day.execution_cost, day.gross_return) \
                != replay_day_economics(ledger, day):
            raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
                f"economics:{day.session}")
    final_account = ledger.days[-1].evidence.account_snapshot
    if state.cash != final_account.cash or state.positions \
            or state.open_intents or state.halted \
            or state.fill_quantity != sum(day.completed_trades
                for day in ledger.days):
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE, "replay_state")


def _append_trade(writer: LedgerWriter, spec: TradeSpec) -> None:
    entity = spec.entity_id
    at = spec.occurred_at
    writer.append(EventType.SIGNAL_OBSERVED, entity, at,
        {"decision_id": entity, "semantic_key": "signal"})
    writer.append(EventType.ORDER_INTENDED, entity, at,
        {"decision_id": entity, "identity_hash": canonical_hash({
            "entity": entity}), "strategy_id": "v15-mirror",
            "candidate_id": "v15-mirror"})
    writer.append(EventType.RISK_CHECKED, entity, at,
        {"accepted": True, "semantic_key": "risk"})
    writer.append(EventType.ORDER_ACCEPTED, entity, at,
        {"quantity": 1, "semantic_key": "accepted"})
    writer.append(EventType.FILL_COMPLETE, entity, at,
        {"quantity": 1, "semantic_key": "fill"})
    writer.append(EventType.POSITION_UPDATED, entity, at,
        {"cash_delta": money(spec.cash_delta), "symbol": entity,
            "side": "long", "sector": "mirror", "quantity": 0,
            "mark_price": "1", "semantic_key": "position"})
    if spec.cost:
        writer.append(EventType.COST_ACCRUED, entity, at,
            {"total": money(spec.cost), "semantic_key": "cost"})
    payload: dict[str, JsonValue] = {
        "halted": spec.halted, "semantic_key": "reconciled"}
    if spec.halted:
        payload["halt_kind"] = "daily_loss"
    writer.append(EventType.RECONCILED, entity, at, payload)


def _day_kind(
    schedule: MarketSchedule, arm: Literal["orb", "router"], session: date
) -> DayKind:
    if session in schedule.no_trade_sessions:
        return DayKind.NO_TRADE
    if arm == "orb" and session == schedule.loss_kill_session:
        return DayKind.LOSS_KILL
    return DayKind.TRADE


def _net_return(
    context: MirrorBuildContext, session: date, kind: DayKind
) -> Decimal:
    if kind is DayKind.NO_TRADE:
        return Decimal(0)
    if kind is DayKind.LOSS_KILL:
        return Decimal("-0.02")
    if context.mirror.arm == "orb":
        return context.returns.orb
    if session in context.schedule.performance_sessions:
        return context.returns.router_rollback_period
    return context.returns.router_winner_period


def _ledger_hash(ledger: MirrorLedger) -> str:
    return canonical_hash({"account": model_json(ledger.account),
        "initial_cash": ledger.initial_cash,
        "events": [model_json(event) for event in ledger.events],
        "replay_state": model_json(ledger.replay_state),
        "days": [model_json(day) for day in ledger.days]})


def _session_events(
    events: tuple[LedgerEvent, ...], session: date
) -> tuple[LedgerEvent, ...]:
    if not events:
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
            session.isoformat())
    return events


def _at(session: date, hour: int, minute: int) -> datetime:
    return datetime.combine(session, time(hour=hour, minute=minute), UTC)
