from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from .canonical import money
from .models import Market, StrictModel


class BorrowSnapshot(StrictModel):
    market: Market
    symbol: str
    observed_at: datetime
    effective_from: datetime
    effective_until: datetime
    regulation_hash: str
    locate: bool
    etb: bool
    shortable: bool
    rule_known: bool
    annual_fee: str
    recalled_at: datetime | None = None


def short_eligible(snapshot: BorrowSnapshot | None, at: datetime,
                   market: Market | None = None, symbol: str | None = None) -> bool:
    if snapshot is None:
        return False
    bound = (market is None or snapshot.market is market) and (symbol is None or snapshot.symbol == symbol)
    return (bound and snapshot.effective_from <= at < snapshot.effective_until and snapshot.locate
            and snapshot.etb and snapshot.shortable and snapshot.rule_known)


def borrow_cost(notional: str, annual_fee: str, calendar_days: int) -> str:
    return money(Decimal(notional) * Decimal(annual_fee) * Decimal(calendar_days) / Decimal(365))


def recall_exit(snapshot: BorrowSnapshot, regular_open: datetime | None = None,
                regular_close: datetime | None = None) -> datetime | None:
    if snapshot.recalled_at is None:
        return None
    boundary = snapshot.recalled_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if regular_open and boundary < regular_open:
        return regular_open
    if regular_close and boundary >= regular_close:
        return None
    return boundary
