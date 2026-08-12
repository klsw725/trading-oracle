from __future__ import annotations

from datetime import datetime, timedelta

from .models import V11ContractError


def entry_allowed(target_at: datetime, regular_close: datetime) -> bool:
    return target_at < regular_close - timedelta(minutes=20)


def exit_boundary(regular_close: datetime) -> datetime:
    return regular_close - timedelta(minutes=4)


def overnight(position_quantity: int, regular_close: datetime, exit_at: datetime | None) -> bool:
    return position_quantity > 0 and (exit_at is None or exit_at > regular_close)


def verify_flat_at_close(position_quantity: int, regular_close: datetime,
                         exit_at: datetime | None) -> None:
    if overnight(position_quantity, regular_close, exit_at):
        raise V11ContractError("V11_OVERNIGHT_POSITION", str(position_quantity))
