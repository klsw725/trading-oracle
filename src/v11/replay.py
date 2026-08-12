from __future__ import annotations

from .canonical import decimal_value, money, normalize_scalar
from .ledger import GENESIS, verify_chain
from .models import EventType, LedgerEvent, Position, ReplayCheckpoint, ReplayState, Side, V11ContractError


def replay(events: tuple[LedgerEvent, ...], initial_cash: str,
           checkpoint: ReplayCheckpoint | None = None) -> ReplayState:
    verify_chain(events)
    state = checkpoint.state if checkpoint else ReplayState(cash=initial_cash, positions=(),
        open_intents=(), fill_quantity=0, accrued_cost="0", halted=False, tail_hash=GENESIS)
    start = checkpoint.event_index + 1 if checkpoint else 0
    if checkpoint and (checkpoint.event_index >= len(events) or
                       events[checkpoint.event_index].event_hash != checkpoint.state.tail_hash):
        raise V11ContractError("V11_CHECKPOINT_MISMATCH", str(checkpoint.event_index))
    if checkpoint:
        rebuilt = replay(events[:checkpoint.event_index + 1], initial_cash)
        if rebuilt != checkpoint.state:
            raise V11ContractError("V11_CHECKPOINT_MISMATCH", "state")
    cash = decimal_value(state.cash)
    positions = {item.symbol: item for item in state.positions}
    open_intents = set(state.open_intents)
    fill_quantity = state.fill_quantity
    accrued = decimal_value(state.accrued_cost)
    halted = state.halted
    for event in events[start:]:
        match event.event_type:  # noqa: MATCH_OK - EventType enum is exhaustively covered
            case EventType.SIGNAL_OBSERVED | EventType.RISK_CHECKED | EventType.RECONCILED:
                halted = halted or event.payload.get("halted") is True
            case EventType.SESSION_CLOSED:
                halted = False if event.payload.get("reset") is True else halted
            case EventType.ORDER_INTENDED | EventType.ORDER_ACCEPTED:
                open_intents.add(event.entity_id)
            case EventType.FILL_PARTIAL | EventType.FILL_COMPLETE:
                fill_quantity += _integer(event, "quantity")
                if event.event_type is EventType.FILL_COMPLETE:
                    open_intents.discard(event.entity_id)
            case EventType.ORDER_CANCELLED:
                open_intents.discard(event.entity_id)
            case EventType.POSITION_UPDATED:
                cash += decimal_value(_text(event, "cash_delta"))
                quantity = _integer(event, "quantity")
                symbol = _text(event, "symbol")
                if quantity == 0:
                    _ = positions.pop(symbol, None)
                else:
                    positions[symbol] = Position(symbol=symbol, side=Side(_text(event, "side")),
                        sector=_text(event, "sector"), quantity=quantity,
                        mark_price=_text(event, "mark_price"))
            case EventType.COST_ACCRUED:
                cost = decimal_value(_text(event, "total"))
                accrued += cost
                cash -= cost
    tail = events[-1].event_hash if events else GENESIS
    return ReplayState(cash=money(cash), positions=tuple(positions[key] for key in sorted(positions)),
        open_intents=tuple(sorted(open_intents)), fill_quantity=fill_quantity,
        accrued_cost=money(accrued), halted=halted, tail_hash=tail)


def checkpoint(events: tuple[LedgerEvent, ...], initial_cash: str, event_index: int) -> ReplayCheckpoint:
    if event_index < 0 or event_index >= len(events):
        raise V11ContractError("V11_CHECKPOINT_MISMATCH", str(event_index))
    state = replay(events[:event_index + 1], initial_cash)
    return ReplayCheckpoint(event_index=event_index, state=state)


def _text(event: LedgerEvent, field: str) -> str:
    value = normalize_scalar(event.payload.get(field))
    if isinstance(value, str):
        return value
    raise V11ContractError("V11_REPLAY_PAYLOAD", field)


def _integer(event: LedgerEvent, field: str) -> int:
    value = normalize_scalar(event.payload.get(field))
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise V11ContractError("V11_REPLAY_PAYLOAD", field)
