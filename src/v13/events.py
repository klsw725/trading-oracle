from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from src.v11.canonical import canonical_hash
from src.v11.ledger import GENESIS, append_event, register_intent
from src.v11.models import Decision, EventType, Fill, LedgerEvent, OrderAction, Position
from src.v4.models import JsonValue
from src.v13.models import StrictModel
from src.v13.prd03_models import SwitchState, SwitchTimelineEvent


class LegRecord(StrictModel):
    events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    decision: Decision
    fill: Fill
    resulting_position: Position | None
    recorded_at: Annotated[datetime, Field(strict=False)]
    manifest_hash: str


def append_timeline(
    events: tuple[SwitchTimelineEvent, ...],
    state: SwitchState,
    at: datetime,
    reason: str,
) -> tuple[SwitchTimelineEvent, ...]:
    previous = events[-1].event_hash if events else str(GENESIS)
    body: JsonValue = {
        "event_index": len(events),
        "state": state.value,
        "occurred_at": at.isoformat(),
        "reason_code": reason,
        "previous_event_hash": previous,
    }
    return (
        *events,
        SwitchTimelineEvent(
            event_index=len(events),
            state=state,
            occurred_at=at,
            reason_code=reason,
            previous_event_hash=previous,
            event_hash=canonical_hash(body),
        ),
    )


def record_leg(record: LegRecord) -> tuple[LedgerEvent, ...]:
    events, _ = register_intent(
        record.events, record.decision, record.recorded_at, record.manifest_hash
    )
    entity = record.fill.intent_id
    events = append_event(
        events,
        EventType.RISK_CHECKED,
        entity,
        record.recorded_at,
        {"accepted": True, "semantic_key": "risk"},
        record.manifest_hash,
    )
    if record.fill.filled_quantity == 0:
        return append_event(
            events,
            EventType.ORDER_CANCELLED,
            entity,
            record.recorded_at,
            {"quantity": record.fill.cancelled_quantity, "semantic_key": "zero_fill_cancel"},
            record.manifest_hash,
        )
    fill_kind = (
        EventType.FILL_PARTIAL
        if record.fill.cancelled_quantity
        else EventType.FILL_COMPLETE
    )
    position = record.resulting_position
    quantity = position.quantity if position is not None else 0
    side = position.side.value if position is not None else record.decision.side.value
    sector = position.sector if position is not None else record.decision.sector
    mark_price = position.mark_price if position is not None else record.fill.price
    notional = Decimal(record.fill.filled_quantity) * Decimal(record.fill.price)
    cash_delta = notional if record.fill.action in {OrderAction.SELL, OrderAction.SHORT} else -notional
    sequence: tuple[tuple[EventType, dict[str, JsonValue]], ...] = (
        (EventType.ORDER_ACCEPTED, {"quantity": record.fill.requested_quantity, "semantic_key": "accepted"}),
        (fill_kind, {"quantity": record.fill.filled_quantity, "semantic_key": "fill"}),
        (EventType.POSITION_UPDATED, {"cash_delta": str(cash_delta),
            "symbol": record.decision.symbol, "side": side, "sector": sector,
            "quantity": quantity, "mark_price": mark_price, "semantic_key": "position"}),
        (EventType.COST_ACCRUED, {"total": record.fill.costs.total, "semantic_key": "cost"}),
    )
    for event_type, payload in sequence:
        events = append_event(events, event_type, entity, record.recorded_at,
            payload, record.manifest_hash)
    if record.fill.cancelled_quantity:
        events = append_event(events, EventType.ORDER_CANCELLED, entity,
            record.recorded_at, {"quantity": record.fill.cancelled_quantity,
                "semantic_key": "remainder_cancel"}, record.manifest_hash)
    return events


def record_rejected(
    events: tuple[LedgerEvent, ...], decision: Decision, at: datetime, manifest_hash: str
) -> tuple[LedgerEvent, ...]:
    events, receipt = register_intent(events, decision, at, manifest_hash)
    events = append_event(events, EventType.RISK_CHECKED, receipt.intent_id, at,
        {"accepted": False, "semantic_key": "risk"}, manifest_hash)
    return append_event(events, EventType.ORDER_CANCELLED, receipt.intent_id, at,
        {"quantity": 0, "semantic_key": "risk_rejected"}, manifest_hash)
