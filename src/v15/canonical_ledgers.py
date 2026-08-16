from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.v11.canonical import canonical_hash, decimal_value, model_json, money
from src.v11.ledger import append_event
from src.v11.models import EventType, LedgerEvent
from src.v11.replay import replay as replay_v11
from src.v4.models import JsonValue

from .liquidation import KillExecution
from .contract import V15Failure, V15FailureCode
from .operation_models import MarketOperation, MirrorLedger
from .paired import ArmDay, DayKind, V11ExecutionEvidence
from .recovery import RecoveryEvidence


def splice_kill_recovery(
    markets: tuple[MarketOperation, MarketOperation],
    execution: KillExecution,
    recovery: RecoveryEvidence,
) -> tuple[MarketOperation, MarketOperation]:
    recovered = {item.account_namespace: item for item in recovery.accounts}
    affected = set(execution.scope.affected_accounts)
    rebuilt_markets: list[MarketOperation] = []
    for market in markets:
        ledgers: list[MirrorLedger] = []
        for ledger in market.mirror_ledgers:
            namespace = ledger.account.account_namespace
            if namespace not in affected:
                ledgers.append(ledger)
                continue
            account = recovered[namespace]
            events = account.events
            resume_after = events[-1].occurred_at
            events = _append_resumed_sessions(events, ledger, resume_after)
            ledgers.append(_replace_chain(ledger, events))
        rebuilt_markets.append(market.model_copy(update={
            "mirror_ledgers": tuple(ledgers)}))
    return (rebuilt_markets[0], rebuilt_markets[1])


def finalize_canonical_ledgers(
    markets: tuple[MarketOperation, MarketOperation],
) -> tuple[MarketOperation, MarketOperation]:
    rebuilt = tuple(market.model_copy(update={"mirror_ledgers": tuple(
        replace_mirror_events(ledger, ledger.events)
        for ledger in market.mirror_ledgers)}) for market in markets)
    return (rebuilt[0], rebuilt[1])


def replace_mirror_events(
    ledger: MirrorLedger, events: tuple[LedgerEvent, ...],
) -> MirrorLedger:
    original = {day.session: day for day in ledger.days}
    days: list[ArmDay] = []
    for session in tuple(day.session for day in ledger.days):
        day_events = tuple(event for event in events
            if event.occurred_at.date() == session)
        if not day_events:
            raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
                session.isoformat())
        first_index = day_events[0].event_index
        last_index = day_events[-1].event_index
        start = replay_v11(events[:first_index], ledger.initial_cash) \
            if first_index else replay_v11((), ledger.initial_cash)
        state = replay_v11(events[:last_index + 1], ledger.initial_cash)
        start_cash = decimal_value(start.cash)
        end_cash = decimal_value(state.cash)
        cost_amount = sum((decimal_value(total)
            for event in day_events if event.event_type is EventType.COST_ACCRUED
            and isinstance((total := event.payload.get("total")), str)),
            Decimal(0))
        net_return = (end_cash - start_cash) / start_cash
        execution_cost = cost_amount / start_cash
        snapshot = original[session].evidence.account_snapshot.model_copy(update={
            "prior_close_nav": start.cash, "cash": state.cash,
            "positions": state.positions, "halted": state.halted})
        fills = tuple(str(event.event_hash) for event in day_events
            if event.event_type is EventType.FILL_COMPLETE)
        evidence = V11ExecutionEvidence(arm=ledger.account.arm,
            account_snapshot=snapshot,
            account_hash=canonical_hash(model_json(snapshot)),
            previous_event_hash=str(day_events[0].previous_event_hash),
            ledger_tail_hash=str(day_events[-1].event_hash),
            event_hashes=tuple(str(event.event_hash) for event in day_events),
            fill_hashes=fills,
            manifest_hash=day_events[0].experiment_manifest_hash,
            risk_version=ledger.account.risk_version,
            cost_model=ledger.account.cost_model)
        source_day = original[session]
        kind = DayKind.NO_TRADE if not fills else DayKind.LOSS_KILL \
            if source_day.kind is DayKind.LOSS_KILL else DayKind.TRADE
        days.append(ArmDay(session=session, kind=kind,
            net_return=net_return, gross_return=net_return + execution_cost,
            execution_cost=execution_cost, completed_trades=len(fills),
            evidence=evidence))
    state = replay_v11(events, ledger.initial_cash)
    draft = MirrorLedger(account=ledger.account,
        initial_cash=ledger.initial_cash, events=events,
        replay_state=state, days=tuple(days), ledger_hash="")
    digest = canonical_hash({"account": model_json(draft.account),
        "initial_cash": draft.initial_cash,
        "events": [model_json(event) for event in draft.events],
        "replay_state": model_json(draft.replay_state),
        "days": [model_json(day) for day in draft.days]})
    return draft.model_copy(update={"ledger_hash": digest})


def _replace_chain(
    ledger: MirrorLedger, events: tuple[LedgerEvent, ...],
) -> MirrorLedger:
    state = replay_v11(events, ledger.initial_cash)
    draft = ledger.model_copy(update={"events": events,
        "replay_state": state, "ledger_hash": ""})
    digest = canonical_hash({"account": model_json(draft.account),
        "initial_cash": draft.initial_cash,
        "events": [model_json(event) for event in draft.events],
        "replay_state": model_json(draft.replay_state),
        "days": [model_json(day) for day in draft.days]})
    return draft.model_copy(update={"ledger_hash": digest})


def replay_day_economics(
    ledger: MirrorLedger, day: ArmDay,
) -> tuple[Decimal, Decimal, Decimal]:
    by_hash = {str(event.event_hash): event for event in ledger.events}
    day_events = tuple(by_hash[value] for value in day.evidence.event_hashes)
    first_index = day_events[0].event_index
    last_index = day_events[-1].event_index
    start = replay_v11(ledger.events[:first_index], ledger.initial_cash) \
        if first_index else replay_v11((), ledger.initial_cash)
    end = replay_v11(ledger.events[:last_index + 1], ledger.initial_cash)
    start_cash = decimal_value(start.cash)
    end_cash = decimal_value(end.cash)
    cost_amount = sum((decimal_value(total)
        for event in day_events if event.event_type is EventType.COST_ACCRUED
        and isinstance((total := event.payload.get("total")), str)), Decimal(0))
    net_return = (end_cash - start_cash) / start_cash
    execution_cost = cost_amount / start_cash
    return net_return, execution_cost, net_return + execution_cost


def _append_resumed_sessions(
    events: tuple[LedgerEvent, ...], ledger: MirrorLedger,
    resume_after: datetime,
) -> tuple[LedgerEvent, ...]:
    prior_cash = decimal_value(replay_v11(events, ledger.initial_cash).cash)
    for day in ledger.days:
        source_events = tuple(event for event in ledger.events
            if event.occurred_at.date() == day.session
            and event.occurred_at > resume_after
            and event.event_type is not EventType.SESSION_CLOSED)
        if not source_events:
            continue
        ordinary_positions = tuple(event for event in source_events
            if event.event_type is EventType.POSITION_UPDATED
            and event.entity_id.startswith(
                f"{ledger.account.account_namespace}:{day.session}:"))
        financial_entity = ordinary_positions[-1].entity_id \
            if ordinary_positions else None
        target_cash = decimal_value(money(
            prior_cash * (Decimal(1) + day.net_return)))
        cost_amount = decimal_value(money(
            prior_cash * day.execution_cost))
        cash_delta = target_cash - prior_cash + cost_amount
        for event in source_events:
            payload: dict[str, JsonValue] = dict(event.payload)
            if event.entity_id == financial_entity \
                    and event.event_type is EventType.POSITION_UPDATED:
                payload["cash_delta"] = money(cash_delta)
            if event.entity_id == financial_entity \
                    and event.event_type is EventType.COST_ACCRUED:
                payload["total"] = money(cost_amount)
            events = append_event(events, event.event_type, event.entity_id,
                event.occurred_at, payload, event.experiment_manifest_hash)
        prior_cash = target_cash
    return events
