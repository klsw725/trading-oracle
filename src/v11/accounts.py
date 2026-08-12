from __future__ import annotations

from .models import Account, Market


def create_account(market: Market) -> Account:
    match market:  # noqa: MATCH_OK - Market enum is closed and exhaustively covered
        case Market.KR:
            return Account(market=market, currency="KRW", prior_close_nav="100000000", cash="100000000")
        case Market.US:
            return Account(market=market, currency="USD", prior_close_nav="100000", cash="100000")
