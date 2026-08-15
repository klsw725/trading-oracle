from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field

from .cohort_models import JsonMarket
from .contract import StrictModel
from .selection_models import JsonDecimal
from .series_models import JsonSegment


@unique
class SeriesKind(StrEnum):
    BASELINE = "baseline_net_excess"
    STRESS = "stress_net_excess"


JsonSeriesKind = Annotated[SeriesKind, Field(strict=False)]


class SeedMaterial(StrictModel):
    schema_version: Literal["v14.bootstrap_seed.1"]
    result_free_plan_hash: str
    market: JsonMarket
    segment: JsonSegment
    hypothesis_id: str
    series_kind: JsonSeriesKind


class BootstrapBody(StrictModel):
    schema_version: Literal["v14.bootstrap.1"]
    plan_manifest_hash: str
    market: JsonMarket
    segment: JsonSegment
    hypothesis_id: str
    series_kind: JsonSeriesKind
    derived_seed_hash: str
    block_trading_days: Literal[5]
    resamples: Literal[10000]
    observation_count: int
    possible_block_starts: int
    blocks_per_resample: int
    ci_lower: JsonDecimal
    ci_upper: JsonDecimal
    non_positive_mean_count: int
    one_sided_p_value: JsonDecimal
    resampled_means_hash: str


class BootstrapArtifact(BootstrapBody):
    bootstrap_hash: str
