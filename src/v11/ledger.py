from __future__ import annotations

from datetime import datetime
from typing import Final

from src.v4.models import JsonValue

from .canonical import canonical_hash
from .models import Decision, EventHash, EventType, IntentReceipt, LedgerEvent, V11ContractError


GENESIS: Final = EventHash(f"sha256:{'0' * 64}")
_ALLOWED: Final[dict[EventType, frozenset[EventType]]] = {
    EventType.SIGNAL_OBSERVED: frozenset({EventType.ORDER_INTENDED}),
    EventType.ORDER_INTENDED: frozenset({EventType.RISK_CHECKED, EventType.ORDER_CANCELLED}),
    EventType.RISK_CHECKED: frozenset({EventType.ORDER_ACCEPTED, EventType.ORDER_CANCELLED}),
    EventType.ORDER_ACCEPTED: frozenset({EventType.FILL_PARTIAL, EventType.FILL_COMPLETE, EventType.ORDER_CANCELLED}),
    EventType.FILL_PARTIAL: frozenset({EventType.POSITION_UPDATED, EventType.ORDER_CANCELLED}),
    EventType.FILL_COMPLETE: frozenset({EventType.POSITION_UPDATED}),
    EventType.ORDER_CANCELLED: frozenset({EventType.POSITION_UPDATED, EventType.RECONCILED}),
    EventType.POSITION_UPDATED: frozenset({EventType.COST_ACCRUED, EventType.RECONCILED}),
    EventType.COST_ACCRUED: frozenset({EventType.ORDER_CANCELLED, EventType.RECONCILED}),
    EventType.RECONCILED: frozenset({EventType.SESSION_CLOSED, EventType.ORDER_CANCELLED,
                                     EventType.SIGNAL_OBSERVED}),
    EventType.SESSION_CLOSED: frozenset(),
}


def register_intent(events: tuple[LedgerEvent, ...], decision: Decision, at: datetime,
                    manifest_hash: str, halted: bool = False,
                    forced_exit: bool = False) -> tuple[tuple[LedgerEvent, ...], IntentReceipt]:
    from .canonical import model_json
    from .identity import intent_id
    key = intent_id(decision)
    identity_hash = canonical_hash(model_json(decision))
    for event in events:
        if event.event_type is not EventType.ORDER_INTENDED or event.entity_id != key:
            continue
        if event.payload.get("identity_hash") != identity_hash:
            raise V11ContractError("V11_INTENT_IDENTITY_COLLISION", key)
        return events, IntentReceipt(intent_id=key, identity_hash=identity_hash, state="no_op")
    active_halt = halted or halt_active(events)
    if active_halt and not forced_exit:
        raise V11ContractError("V11_EXECUTION_HALTED", key)
    payload: dict[str, JsonValue] = {"identity_hash": identity_hash,
        "decision_id": decision.decision_id, "strategy_id": decision.strategy_id,
        "candidate_id": decision.candidate_id}
    signalled = append_event(events, EventType.SIGNAL_OBSERVED, key, at,
        {"decision_id": decision.decision_id, "semantic_key": "signal"}, manifest_hash)
    appended = append_event(signalled, EventType.ORDER_INTENDED, key, at, payload, manifest_hash)
    return appended, IntentReceipt(intent_id=key, identity_hash=identity_hash, state="appended")


def halt_active(events: tuple[LedgerEvent, ...]) -> bool:
    daily = False
    integrity = False
    for event in events:
        if event.payload.get("halt_kind") == "daily_loss":
            daily = True
        if event.payload.get("halt_kind") == "integrity":
            integrity = True
        if event.event_type is EventType.SESSION_CLOSED and event.payload.get("reset") is True:
            daily = False
        if event.event_type is EventType.RECONCILED and event.payload.get("reconciliation_clear") is True:
            integrity = False
    return daily or integrity


def verify_risk_checked(events: tuple[LedgerEvent, ...]) -> None:
    by_entity: dict[str, set[EventType]] = {}
    for event in events:
        seen = by_entity.setdefault(event.entity_id, set())
        if event.event_type is EventType.ORDER_ACCEPTED and EventType.RISK_CHECKED not in seen:
            raise V11ContractError("V11_RISK_CHECK_REQUIRED", event.entity_id)
        seen.add(event.event_type)


def append_event(events: tuple[LedgerEvent, ...], event_type: EventType, entity_id: str,
                 at: datetime, payload: dict[str, JsonValue], manifest_hash: str) -> tuple[LedgerEvent, ...]:
    if events and at < events[-1].occurred_at:
        raise V11ContractError("V11_EVENT_TIME_ORDER", at.isoformat())
    semantic_key = payload.get("semantic_key")
    if semantic_key is not None and any(item.entity_id == entity_id and
        item.payload.get("semantic_key") == semantic_key for item in events):
        raise V11ContractError("V11_SEMANTIC_DUPLICATE", str(semantic_key))
    prior = next((item.event_type for item in reversed(events) if item.entity_id == entity_id), None)
    if prior is None and event_type is not EventType.SIGNAL_OBSERVED:
        raise V11ContractError("V11_EVENT_ORDER", f"genesis->{event_type.value}")
    if prior is not None and event_type not in _ALLOWED[prior]:
        raise V11ContractError("V11_EVENT_ORDER", f"{prior.value}->{event_type.value}")
    index = len(events)
    previous = events[-1].event_hash if events else GENESIS
    payload_hash = canonical_hash(payload)
    body: dict[str, JsonValue] = {"event_index": index, "event_type": event_type.value,
        "entity_id": entity_id, "occurred_at": at.isoformat(), "recorded_at": at.isoformat(),
        "payload_hash": payload_hash, "previous_event_hash": previous,
        "experiment_manifest_hash": manifest_hash, "payload": payload}
    digest = canonical_hash(body)
    event = LedgerEvent(event_id=f"v11:event:{digest.removeprefix('sha256:')[:20]}",
        event_index=index, event_type=event_type, entity_id=entity_id, occurred_at=at,
        recorded_at=at, payload_hash=payload_hash, previous_event_hash=previous,
        event_hash=EventHash(digest), experiment_manifest_hash=manifest_hash, payload=payload)
    return (*events, event)


def verify_chain(events: tuple[LedgerEvent, ...]) -> None:
    previous = GENESIS
    semantics: set[tuple[str, str]] = set()
    prior_by_entity: dict[str, EventType] = {}
    for index, event in enumerate(events):
        if index > 0 and event.occurred_at < events[index - 1].occurred_at:
            raise V11ContractError("V11_EVENT_TIME_ORDER", event.event_id)
        if event.event_index != index:
            raise V11ContractError("V11_EVENT_GAP", str(index))
        if event.previous_event_hash != previous:
            raise V11ContractError("V11_LEDGER_BREAK", event.event_id)
        if event.payload_hash != canonical_hash(event.payload):
            raise V11ContractError("V11_PAYLOAD_HASH", event.event_id)
        body: dict[str, JsonValue] = {"event_index": event.event_index, "event_type": event.event_type.value,
            "entity_id": event.entity_id, "occurred_at": event.occurred_at.isoformat(),
            "recorded_at": event.recorded_at.isoformat(), "payload_hash": event.payload_hash,
            "previous_event_hash": event.previous_event_hash,
            "experiment_manifest_hash": event.experiment_manifest_hash, "payload": event.payload}
        if event.event_hash != canonical_hash(body):
            raise V11ContractError("V11_LEDGER_BREAK", event.event_id)
        prior_type = prior_by_entity.get(event.entity_id)
        if prior_type is None and event.event_type is not EventType.SIGNAL_OBSERVED:
            raise V11ContractError("V11_EVENT_ORDER", event.event_id)
        if prior_type is not None and event.event_type not in _ALLOWED[prior_type]:
            raise V11ContractError("V11_EVENT_ORDER", event.event_id)
        semantic_key = event.payload.get("semantic_key")
        if isinstance(semantic_key, str):
            semantic = (event.entity_id, semantic_key)
            if semantic in semantics:
                raise V11ContractError("V11_SEMANTIC_DUPLICATE", event.event_id)
            semantics.add(semantic)
        prior_by_entity[event.entity_id] = event.event_type
        previous = event.event_hash
    verify_risk_checked(events)
