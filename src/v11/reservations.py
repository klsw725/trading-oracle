from __future__ import annotations

from .models import Account, EventType, LedgerEvent, Reservation, V11ContractError


def reserve(account: Account, reservation: Reservation) -> Account:
    if any(item.intent_id == reservation.intent_id for item in account.reservations):
        raise V11ContractError("V11_DUPLICATE_RESERVATION", reservation.intent_id)
    return account.model_copy(update={"reservations": (*account.reservations, reservation)})


def release(account: Account, intent_id: str, events: tuple[LedgerEvent, ...]) -> Account:
    terminal = {EventType.FILL_COMPLETE, EventType.ORDER_CANCELLED}
    if not any(event.entity_id == intent_id and event.event_type in terminal for event in events):
        raise V11ContractError("V11_RESERVATION_EVENT_REQUIRED", intent_id)
    return account.model_copy(update={
        "reservations": tuple(item for item in account.reservations if item.intent_id != intent_id)
    })
