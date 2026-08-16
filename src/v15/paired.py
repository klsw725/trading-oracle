from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum, unique
from functools import lru_cache
from hashlib import sha256
from math import ceil
from typing import Annotated, Final, Literal, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import Field
from src.v11.canonical import canonical_hash, model_json, money
from src.v11.models import Account

from .contract import StrictModel, V15Failure, V15FailureCode
from .upstream import BootstrapIdentity


LOWER_INDEX: Final = 249
UPPER_INDEX: Final = 9_749
UINT256_RANGE: Final = 1 << 256
MAX_BOOTSTRAP_DRAWS: Final = 200_000


@unique
class DayKind(StrEnum):
    TRADE = "trade"
    NO_TRADE = "no_trade"
    LOSS_KILL = "loss_kill"


class V11ExecutionEvidence(StrictModel):
    arm: Literal["orb", "router"]
    account_snapshot: Account
    account_hash: str
    previous_event_hash: str
    ledger_tail_hash: str
    event_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    fill_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    manifest_hash: str
    risk_version: str
    cost_model: str


class ArmDay(StrictModel):
    session: date
    kind: DayKind
    net_return: Decimal
    gross_return: Decimal
    execution_cost: Decimal
    completed_trades: int
    evidence: V11ExecutionEvidence


class ComparisonPlan(StrictModel):
    schema_version: Literal["v15.comparison_plan.1"]
    market: Literal["KR", "US"]
    comparison_epoch_start: date
    router_primary_session: date | None
    expected_official_sessions: Annotated[tuple[date, ...], Field(strict=False)]
    bootstrap: BootstrapIdentity


class PairedPoint(StrictModel):
    session: date
    orb_kind: DayKind
    router_kind: DayKind
    orb_net_return: Decimal
    router_net_return: Decimal
    router_gross_return: Decimal
    router_execution_cost: Decimal
    orb_completed_trades: int
    router_completed_trades: int
    orb_ledger_tail_hash: str
    router_ledger_tail_hash: str


class PairedSeries(StrictModel):
    schema_version: Literal["v15.paired_series.2"]
    plan: ComparisonPlan
    points: Annotated[tuple[PairedPoint, ...], Field(strict=False)]
    series_hash: str


class BootstrapResult(StrictModel):
    schema_version: Literal["v15.bootstrap.2"]
    seed_hash: str
    block_trading_days: Literal[5]
    resamples: Literal[10000]
    observation_count: int
    ci_lower: Decimal
    ci_upper: Decimal
    means_hash: str


def pre_primary_series(series: PairedSeries) -> PairedSeries:
    expected = series.plan.expected_official_sessions
    if series.plan.router_primary_session is None:
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED, "router_winner")
    try:
        primary_index = expected.index(series.plan.router_primary_session)
    except ValueError as error:
        raise V15Failure(V15FailureCode.COMPARISON_INVALID,
            "primary_session") from error
    if primary_index != 60:
        raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT,
            "primary_requires_60_sessions")
    return series_prefix(series, primary_index)


def series_prefix(series: PairedSeries, count: int) -> PairedSeries:
    expected = series.plan.expected_official_sessions
    points = series.points[:count]
    if count > len(series.points) \
            or tuple(item.session for item in points) != expected[:count]:
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "winner_sessions")
    plan = series.plan.model_copy(update={
        "expected_official_sessions": expected[:count]})
    draft = PairedSeries(schema_version="v15.paired_series.2",
        plan=plan, points=points, series_hash="")
    return draft.model_copy(update={"series_hash": canonical_hash(
        model_json(draft.model_copy(update={"series_hash": ""})))})


def pair_days(
    plan: ComparisonPlan,
    orb_days: tuple[ArmDay, ...],
    router_days: tuple[ArmDay, ...],
) -> PairedSeries:
    expected = plan.expected_official_sessions
    orb_by_day = {item.session: item for item in orb_days}
    router_by_day = {item.session: item for item in router_days}
    if len(orb_days) != len(orb_by_day) \
            or len(router_days) != len(router_by_day) \
            or tuple(sorted(orb_by_day)) != expected \
            or tuple(sorted(router_by_day)) != expected:
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "expected_sessions")
    for day in (*orb_days, *router_days):
        _verify_day(day, plan)
    points = tuple(PairedPoint(session=session,
        orb_kind=orb_by_day[session].kind,
        router_kind=router_by_day[session].kind,
        orb_net_return=orb_by_day[session].net_return,
        router_net_return=router_by_day[session].net_return,
        router_gross_return=router_by_day[session].gross_return,
        router_execution_cost=router_by_day[session].execution_cost,
        orb_completed_trades=orb_by_day[session].completed_trades,
        router_completed_trades=router_by_day[session].completed_trades,
        orb_ledger_tail_hash=orb_by_day[session].evidence.ledger_tail_hash,
        router_ledger_tail_hash=router_by_day[session].evidence.ledger_tail_hash)
        for session in expected)
    post_promotion = tuple(day for day in orb_days
        if plan.router_primary_session is None
        or day.session >= plan.router_primary_session)
    if not post_promotion or any(not day.evidence.event_hashes
            for day in post_promotion):
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "orb_continuation")
    draft = PairedSeries(schema_version="v15.paired_series.2", plan=plan,
        points=points, series_hash="")
    return draft.model_copy(update={"series_hash": canonical_hash(
        model_json(draft.model_copy(update={"series_hash": ""})))})


def _verify_day(day: ArmDay, plan: ComparisonPlan) -> None:
    evidence = day.evidence
    if evidence.manifest_hash != plan.bootstrap.plan_manifest_hash \
            or evidence.account_hash != canonical_hash(
                model_json(evidence.account_snapshot)) \
            or not evidence.event_hashes \
            or evidence.ledger_tail_hash != evidence.event_hashes[-1]:
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
            day.session.isoformat())
    if day.kind is DayKind.TRADE and (day.completed_trades <= 0
            or len(evidence.fill_hashes) != day.completed_trades):
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE, "trade_fill")
    if day.kind is DayKind.NO_TRADE and (day.completed_trades != 0
            or evidence.fill_hashes):
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE, "no_trade_fill")


def require_winner_sample(series: PairedSeries) -> None:
    orb_trades = sum(item.orb_completed_trades for item in series.points)
    router_trades = sum(item.router_completed_trades for item in series.points)
    if len(series.points) < 60 or orb_trades < 300 or router_trades < 300:
        raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT, "winner")


def bootstrap(series: PairedSeries, window: int | None = None) -> BootstrapResult:
    points = series.points[-window:] if window is not None else series.points
    values = tuple(item.router_net_return - item.orb_net_return for item in points)
    identity = series.plan.bootstrap
    seed_hash = canonical_hash({"schema_version": "v15.bootstrap_seed.2",
        "plan_manifest_hash": identity.plan_manifest_hash,
        "experiment_version": identity.experiment_version, "seed": identity.seed,
        "market": series.plan.market, "hypothesis_id": identity.hypothesis_id,
        "window": window, "block_trading_days": identity.block_trading_days,
        "resamples": identity.resamples})
    means = _resampled_means(values,
        bytes.fromhex(seed_hash.removeprefix("sha256:")),
        identity.block_trading_days, identity.resamples)
    return BootstrapResult(schema_version="v15.bootstrap.2",
        seed_hash=seed_hash, block_trading_days=identity.block_trading_days,
        resamples=identity.resamples, observation_count=len(values),
        ci_lower=means[LOWER_INDEX], ci_upper=means[UPPER_INDEX],
        means_hash=canonical_hash([money(value) for value in means]))


@lru_cache(maxsize=128)
def _resampled_means(
    values: tuple[Decimal, ...], seed: bytes, block_size: int, resamples: int
) -> tuple[Decimal, ...]:
    count = len(values)
    if count < block_size:
        raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT, "bootstrap")
    starts = count - block_size + 1
    blocks = ceil(count / block_size)
    remainder = count - block_size * (blocks - 1)
    places = min(max(_decimal_places(value) for value in values), 12)
    scale: int = 1
    for _ in range(places):
        scale *= 10
    scaled = np.asarray([int(value * scale) for value in values],
        dtype=np.int64)
    prefix = np.concatenate((np.zeros(1, dtype=np.int64),
        np.cumsum(scaled, dtype=np.int64)))
    full = prefix[block_size:] - prefix[:-block_size]
    final = prefix[remainder:] - prefix[:-remainder]
    indices = _draw_indices(seed, starts, resamples * blocks).reshape(
        resamples, blocks)
    totals: NDArray[np.int64] = np.sum(full[indices[:, :-1]],
        axis=1, dtype=np.int64) \
        + final[indices[:, -1]]
    denominator = Decimal(scale * count)
    means = tuple(Decimal(int(cast(np.int64, totals[index]))) / denominator
        for index in range(resamples))
    return tuple(sorted(means))


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "non_finite_return")
    return max(0, -exponent)


def _draw_indices(seed: bytes, bound: int, count: int) -> NDArray[np.int64]:
    limit = UINT256_RANGE - UINT256_RANGE % bound
    values = (value % bound for value in _random_values(seed)
        if value < limit)
    return np.fromiter(values, dtype=np.int64, count=count)


@lru_cache(maxsize=4)
def _random_values(seed: bytes) -> tuple[int, ...]:
    return tuple(int.from_bytes(sha256(seed
        + counter.to_bytes(16, "big")).digest(), "big")
        for counter in range(MAX_BOOTSTRAP_DRAWS))
