from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import ValidationError

from src.v4.models import JsonValue

from .canonical import seal_meta
from .instruments import InstrumentType, ranking_eligible
from .models import ArtifactMeta, Market, StrictModel, Symbol, V10ContractError


class UniverseCandidate(StrictModel):
    symbol: Symbol
    instrument_type: InstrumentType
    classification_verified: bool
    listed_sessions: int
    halted: bool
    turnovers: tuple[Decimal, ...]


class UniverseMember(StrictModel):
    symbol: Symbol
    rank: int
    average_turnover: Decimal


class UniverseExclusion(StrictModel):
    symbol: Symbol
    reason: str


class UniverseSnapshot(StrictModel):
    meta: ArtifactMeta
    market: Market
    ranking_date: date
    effective_date: date
    members: tuple[UniverseMember, ...]
    exclusions: tuple[UniverseExclusion, ...]
    frozen: Literal[True]


def build_universe(
    value: JsonValue, ranking_date: date, effective_date: date, market: Market
) -> UniverseSnapshot:
    try:
        candidates = tuple(UniverseCandidate.model_validate(item) for item in _items(value))
    except ValidationError as error:
        raise V10ContractError("V10_UNIVERSE_MALFORMED", str(error)) from error
    if len(candidates) < 101 or effective_date <= ranking_date:
        raise V10ContractError("V10_UNIVERSE_LOOKAHEAD", str(effective_date))
    ranked: list[tuple[Symbol, Decimal]] = []
    exclusions: list[UniverseExclusion] = []
    for candidate in candidates:
        reason = _exclusion_reason(candidate)
        if reason is not None:
            exclusions.append(UniverseExclusion(symbol=candidate.symbol, reason=reason))
            continue
        ranked.append((candidate.symbol, sum(candidate.turnovers) / Decimal(20)))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    members = tuple(
        UniverseMember(symbol=symbol, rank=index, average_turnover=average)
        for index, (symbol, average) in enumerate(ranked[:100], start=1)
    )
    body: JsonValue = {
        "market": market.value,
        "ranking_date": ranking_date.isoformat(),
        "effective_date": effective_date.isoformat(),
        "members": [item.model_dump(mode="json") for item in members],
        "exclusions": [item.model_dump(mode="json") for item in exclusions],
        "frozen": True,
    }
    return UniverseSnapshot(
        meta=seal_meta("universe_snapshot", body), market=market,
        ranking_date=ranking_date, effective_date=effective_date,
        members=members, exclusions=tuple(exclusions), frozen=True,
    )


def _items(value: JsonValue) -> list[JsonValue]:
    match value:  # noqa: MATCH_OK - fixture boundary rejects every non-array JSON shape
        case list() as items:
            return items
        case _:
            raise V10ContractError("V10_UNIVERSE_MALFORMED", "candidate array")


def _exclusion_reason(candidate: UniverseCandidate) -> str | None:
    if not ranking_eligible(candidate.instrument_type):
        return "excluded_instrument"
    if not candidate.classification_verified:
        return "classification_unknown"
    if candidate.listed_sessions < 20:
        return "insufficient_history"
    if candidate.halted:
        return "halted"
    if len(candidate.turnovers) != 20:
        return "incomplete_history"
    return None


def assert_membership_frozen(snapshot: UniverseSnapshot, proposed: tuple[Symbol, ...]) -> None:
    if proposed != tuple(member.symbol for member in snapshot.members):
        raise V10ContractError("V10_UNIVERSE_NOT_FROZEN", "membership changed")
