from __future__ import annotations

from datetime import date
from typing import Final

from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market

from .cohort_models import (
    FrozenCohort,
    FrozenCohortBody,
    MarketCohort,
    MarketDescriptor,
    MonthRow,
    Segment,
)
from .contract import V14ContractError


MONTH_COUNT: Final = 24
SEGMENT_LENGTHS: Final = (12, 6, 6)


def _month_after(value: date) -> date:
    year = value.year + (value.month // 12)
    month = (value.month % 12) + 1
    return date(year, month, 1)


def expand_descriptor(descriptor: MarketDescriptor) -> tuple[MonthRow, ...]:
    if descriptor.start.day != 1 or descriptor.month_count != MONTH_COUNT:
        raise V14ContractError("V14_COHORT_LENGTH", descriptor.market.value)
    if len(descriptor.context_snapshot_hashes) != MONTH_COUNT:
        raise V14ContractError("V14_CONTEXT_CONTINUITY", descriptor.market.value)
    rows: list[MonthRow] = []
    start = descriptor.start
    for context_hash in descriptor.context_snapshot_hashes:
        end = _month_after(start)
        rows.append(MonthRow(market=descriptor.market, start=start, end=end,
            observed_at=end, context_snapshot_hash=context_hash))
        start = end
    return tuple(rows)


def _segment(role: str, rows: tuple[MonthRow, ...]) -> Segment:
    if not rows:
        raise V14ContractError("V14_SEGMENT_EMPTY", role)
    return Segment.model_validate({"role": role, "start": rows[0].start,
        "end": rows[-1].end, "months": rows})


def _market_cohort(market: Market, rows: tuple[MonthRow, ...]) -> MarketCohort:
    if len(rows) != MONTH_COUNT or any(row.market is not market for row in rows):
        raise V14ContractError("V14_MARKET_ISOLATION", market.value)
    for index, row in enumerate(rows):
        if not row.context_snapshot_hash:
            raise V14ContractError("V14_CONTEXT_CONTINUITY", f"{market}:{index}")
        if row.start >= row.end or row.observed_at > row.end:
            raise V14ContractError("V14_POINT_IN_TIME", f"{market}:{index}")
        if index and rows[index - 1].end != row.start:
            raise V14ContractError("V14_SEGMENT_OVERLAP", f"{market}:{index}")
    development = rows[:12]
    validation = rows[12:18]
    holdout = rows[18:]
    return MarketCohort(market=market,
        development=_segment("development", development),
        validation=_segment("validation", validation),
        holdout=_segment("holdout", holdout))


def freeze_cohort(rows: tuple[MonthRow, ...]) -> FrozenCohort:
    markets = tuple(
        _market_cohort(market, tuple(row for row in rows if row.market is market))
        for market in (Market.KR, Market.US)
    )
    if len(rows) != MONTH_COUNT * 2:
        raise V14ContractError("V14_MARKET_ISOLATION", str(len(rows)))
    body = FrozenCohortBody(schema_version="v14.frozen_cohort.1", markets=markets)
    return FrozenCohort(schema_version=body.schema_version, markets=body.markets,
        cohort_hash=canonical_hash(model_json(body)))
