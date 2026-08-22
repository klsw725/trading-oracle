from __future__ import annotations

from dataclasses import dataclass, replace

from .errors import V17Error
from .events import Event
from .models import AmountPayload, OpenedPayload, PositionPayload, ReleasePayload, ReservationPayload
from .schema import require_int64


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: int
    average_cost_minor: int


@dataclass(frozen=True, slots=True)
class Reservation:
    reservation_id: str
    amount_minor: int
    status: str
    created_event_sequence: int
    created_event_hash: str
    created_event_id: str
    released_event_sequence: int | None
    released_event_hash: str | None
    released_event_id: str | None


@dataclass(frozen=True, slots=True)
class AccountState:
    available_cash_minor: int
    reserved_cash_minor: int
    positions: tuple[Position, ...]
    reservations: tuple[Reservation, ...]
    sequence: int
    event_hash: str


def _position(state: AccountState, symbol: str) -> Position | None:
    return next((item for item in state.positions if item.symbol == symbol), None)


def _reservation(state: AccountState, reservation_id: str) -> Reservation | None:
    return next((item for item in state.reservations if item.reservation_id == reservation_id), None)


def apply_event(state: AccountState | None, event: Event) -> AccountState:
    match event.event_type, event.payload:  # noqa: MATCH_OK - persisted payload mismatch is corruption.
        case "account.opened", OpenedPayload(opening_cash_minor=opening):
            if state is not None or event.sequence != 1:
                raise V17Error("ACCOUNT_ALREADY_OPEN", event.event_id)
            _ = require_int64(opening, "opening_cash_minor")
            return AccountState(opening, 0, (), (), event.sequence, event.event_hash)
        case "cash.credited", AmountPayload(amount_minor=amount):
            current = _require_state(state)
            available = require_int64(current.available_cash_minor + amount, "available_cash_minor")
            return replace(current, available_cash_minor=available,
                           sequence=event.sequence, event_hash=event.event_hash)
        case "cash.debited", AmountPayload(amount_minor=amount):
            current = _require_state(state)
            available = current.available_cash_minor - amount
            if available < 0:
                raise V17Error("INSUFFICIENT_CASH", str(amount))
            return replace(current, available_cash_minor=available,
                           sequence=event.sequence, event_hash=event.event_hash)
        case "position.adjusted", PositionPayload() as payload:
            current = _require_state(state)
            prior = _position(current, payload.symbol)
            quantity = (prior.quantity if prior is not None else 0) + payload.quantity_delta
            _ = require_int64(quantity, "quantity")
            if quantity < 0:
                raise V17Error("SHORT_POSITION_FORBIDDEN", payload.symbol)
            if (quantity == 0 and payload.average_cost_minor != 0) or (
                quantity > 0 and payload.average_cost_minor <= 0
            ):
                raise V17Error("INVALID_AVERAGE_COST", payload.symbol)
            positions = tuple(item for item in current.positions if item.symbol != payload.symbol)
            if quantity > 0:
                positions += (Position(payload.symbol, quantity, payload.average_cost_minor),)
            return replace(current, positions=tuple(sorted(positions, key=lambda item: item.symbol)),
                           sequence=event.sequence, event_hash=event.event_hash)
        case "reservation.placed", ReservationPayload() as payload:
            current = _require_state(state)
            if _reservation(current, payload.reservation_id) is not None:
                raise V17Error("RESERVATION_EXISTS", payload.reservation_id)
            available = current.available_cash_minor - payload.amount_minor
            if available < 0:
                raise V17Error("INSUFFICIENT_CASH", payload.reservation_id)
            reserved = require_int64(current.reserved_cash_minor + payload.amount_minor,
                                     "reserved_cash_minor")
            item = Reservation(payload.reservation_id, payload.amount_minor, "ACTIVE",
                               event.sequence, event.event_hash, event.event_id, None, None, None)
            reservations = tuple(sorted(current.reservations + (item,),
                                        key=lambda value: value.reservation_id))
            return replace(current, available_cash_minor=available,
                           reserved_cash_minor=reserved, reservations=reservations,
                           sequence=event.sequence, event_hash=event.event_hash)
        case "reservation.released", ReleasePayload(reservation_id=reservation_id):
            current = _require_state(state)
            prior = _reservation(current, reservation_id)
            if prior is None or prior.status != "ACTIVE":
                raise V17Error("RESERVATION_NOT_ACTIVE", reservation_id)
            available = require_int64(current.available_cash_minor + prior.amount_minor,
                                      "available_cash_minor")
            reserved = current.reserved_cash_minor - prior.amount_minor
            released = replace(prior, status="RELEASED",
                               released_event_sequence=event.sequence,
                               released_event_hash=event.event_hash,
                               released_event_id=event.event_id)
            reservations = tuple(released if item.reservation_id == reservation_id else item
                                 for item in current.reservations)
            return replace(current, available_cash_minor=available,
                           reserved_cash_minor=reserved, reservations=reservations,
                           sequence=event.sequence, event_hash=event.event_hash)
        case _:
            raise V17Error("INVALID_EVENT_PAYLOAD", event.event_type)


def _require_state(state: AccountState | None) -> AccountState:
    if state is None:
        raise V17Error("ACCOUNT_NOT_OPEN", "missing opening event")
    return state
