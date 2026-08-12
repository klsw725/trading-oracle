from __future__ import annotations

from datetime import datetime
from typing import Literal

from src.v4.models import JsonValue

from .canonical import seal_meta
from .models import ArtifactMeta, Market, StrictModel, Symbol


class EligibilityEvent(StrictModel):
    meta: ArtifactMeta
    market: Market
    symbol: Symbol
    effective_at: datetime
    eligible: Literal[False]
    reason: str
    replacement_allowed: Literal[False]


def block_eligibility(market: Market, symbol: Symbol, at: datetime, reason: str) -> EligibilityEvent:
    body: JsonValue = {"market": market.value, "symbol": symbol, "effective_at": at.isoformat(),
                       "eligible": False, "reason": reason, "replacement_allowed": False}
    return EligibilityEvent(meta=seal_meta("eligibility_event", body), market=market,
                            symbol=symbol, effective_at=at, eligible=False, reason=reason,
                            replacement_allowed=False)
