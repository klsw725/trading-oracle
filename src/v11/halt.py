from __future__ import annotations

from datetime import date

from .models import StrictModel, V11ContractError


class HaltState(StrictModel):
    kind: str
    session_date: date
    pending_cancelled: bool
    new_intents_blocked: bool
    forced_exit_requested: bool


def daily_loss_halt(session_date: date) -> HaltState:
    return HaltState(kind="daily_loss", session_date=session_date, pending_cancelled=True,
        new_intents_blocked=True, forced_exit_requested=True)


def integrity_halt(session_date: date) -> HaltState:
    return HaltState(kind="integrity", session_date=session_date, pending_cancelled=True,
        new_intents_blocked=True, forced_exit_requested=False)


def reset(halt: HaltState, next_session: date, reconciled: bool = False) -> HaltState | None:
    if halt.kind == "integrity" and not reconciled:
        raise V11ContractError("V11_MANUAL_RECONCILIATION_REQUIRED", next_session.isoformat())
    if next_session <= halt.session_date:
        return halt
    return None
