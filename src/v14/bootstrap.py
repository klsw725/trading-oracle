from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from math import ceil
from typing import Final

from src.v11.canonical import canonical_hash, model_json, money

from .bootstrap_models import (
    BootstrapArtifact,
    BootstrapBody,
    SeedMaterial,
    SeriesKind,
)
from .contract import V14ContractError
from .manifest_models import ExperimentPlanManifest
from .manifest_plan import result_free_plan_hash
from .series_models import DailySeriesArtifact


LOWER_INDEX: Final = 249
UPPER_INDEX: Final = 9749
UINT256_RANGE: Final = 1 << 256


def derive_seed_hash(
    plan: ExperimentPlanManifest,
    series: DailySeriesArtifact,
    kind: SeriesKind,
) -> str:
    material = SeedMaterial(schema_version="v14.bootstrap_seed.1",
        result_free_plan_hash=result_free_plan_hash(plan),
        market=series.market, segment=series.segment,
        hypothesis_id=series.hypothesis_id, series_kind=kind)
    return canonical_hash(model_json(material))


def _draw(seed: bytes, counter: int, bound: int) -> tuple[int, int]:
    limit = UINT256_RANGE - (UINT256_RANGE % bound)
    current = counter
    while True:
        value = int.from_bytes(sha256(seed + current.to_bytes(16, "big")).digest())
        current += 1
        if value < limit:
            return value % bound, current


def _series_values(
    series: DailySeriesArtifact, kind: SeriesKind
) -> tuple[Decimal, ...]:
    return {
        SeriesKind.BASELINE: tuple(
            point.baseline_net_excess_return for point in series.points
        ),
        SeriesKind.STRESS: tuple(
            point.stress_net_excess_return for point in series.points
        ),
    }[kind]


def resampled_means(
    plan: ExperimentPlanManifest,
    series: DailySeriesArtifact,
    kind: SeriesKind,
) -> tuple[Decimal, ...]:
    values = _series_values(series, kind)
    block_size = plan.bootstrap.block_trading_days
    resamples = plan.bootstrap.resamples
    count = len(values)
    if count < block_size:
        raise V14ContractError("V14_BOOTSTRAP_LENGTH", str(count))
    possible_starts = count - block_size + 1
    blocks = ceil(count / block_size)
    remainder = count - block_size * (blocks - 1)
    full_sums = tuple(sum(values[start:start + block_size], Decimal(0))
        for start in range(possible_starts))
    final_sums = tuple(sum(values[start:start + remainder], Decimal(0))
        for start in range(possible_starts))
    seed_hash = derive_seed_hash(plan, series, kind)
    seed = bytes.fromhex(seed_hash.removeprefix("sha256:"))
    counter = 0
    means: list[Decimal] = []
    for _ in range(resamples):
        total = Decimal(0)
        for block_index in range(blocks):
            start, counter = _draw(seed, counter, possible_starts)
            total += final_sums[start] if block_index == blocks - 1 \
                else full_sums[start]
        means.append(total / count)
    means.sort()
    return tuple(means)


def bootstrap_series(
    plan: ExperimentPlanManifest,
    series: DailySeriesArtifact,
    kind: SeriesKind,
) -> BootstrapArtifact:
    values = _series_values(series, kind)
    block_size = plan.bootstrap.block_trading_days
    resamples = plan.bootstrap.resamples
    count = len(values)
    possible_starts = count - block_size + 1
    blocks = ceil(count / block_size)
    means = resampled_means(plan, series, kind)
    seed_hash = derive_seed_hash(plan, series, kind)
    non_positive = sum(value <= 0 for value in means)
    p_value = Decimal(1 + non_positive) / Decimal(resamples + 1)
    means_hash = canonical_hash([money(value) for value in means])
    body = BootstrapBody(schema_version="v14.bootstrap.1",
        plan_manifest_hash=plan.manifest_hash, market=series.market,
        segment=series.segment, hypothesis_id=series.hypothesis_id,
        series_kind=kind, derived_seed_hash=seed_hash,
        block_trading_days=block_size, resamples=resamples,
        observation_count=count, possible_block_starts=possible_starts,
        blocks_per_resample=blocks, ci_lower=means[LOWER_INDEX],
        ci_upper=means[UPPER_INDEX], non_positive_mean_count=non_positive,
        one_sided_p_value=p_value, resampled_means_hash=means_hash)
    return BootstrapArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash, market=body.market,
        segment=body.segment, hypothesis_id=body.hypothesis_id,
        series_kind=body.series_kind, derived_seed_hash=body.derived_seed_hash,
        block_trading_days=body.block_trading_days, resamples=body.resamples,
        observation_count=body.observation_count,
        possible_block_starts=body.possible_block_starts,
        blocks_per_resample=body.blocks_per_resample, ci_lower=body.ci_lower,
        ci_upper=body.ci_upper,
        non_positive_mean_count=body.non_positive_mean_count,
        one_sided_p_value=body.one_sided_p_value,
        resampled_means_hash=body.resampled_means_hash,
        bootstrap_hash=canonical_hash(model_json(body)))
