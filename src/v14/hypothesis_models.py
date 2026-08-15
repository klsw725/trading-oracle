from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field

from .cohort_models import JsonMarket
from .contract import StrictModel
from .selection_models import JsonDecimal
from .series_models import JsonSegment


@unique
class HypothesisRole(StrEnum):
    PRIMARY = "primary"
    HOLM = "holm"
    EXPLORATORY = "exploratory"
    ROUTER = "router"


class HypothesisSpec(StrictModel):
    hypothesis_id: str
    role: Annotated[HypothesisRole, Field(strict=False)]
    null: str
    comparator: str
    confirmatory: bool


class FrozenHypothesisRegistryBody(StrictModel):
    schema_version: Literal["v14.hypothesis_registry.1"]
    plan_manifest_hash: str
    primary: HypothesisSpec
    holm_family: Annotated[tuple[HypothesisSpec, ...], Field(strict=False)]
    exploratory: Annotated[tuple[HypothesisSpec, ...], Field(strict=False)]
    router: HypothesisSpec


class FrozenHypothesisRegistry(FrozenHypothesisRegistryBody):
    registry_hash: str


class PValueInput(StrictModel):
    hypothesis_id: str
    p_value: JsonDecimal
    tested: bool


class CorrectionResult(StrictModel):
    hypothesis_id: str
    raw_p_value: JsonDecimal
    rank: int
    threshold: JsonDecimal
    correction_passed: bool
    tested: bool
    confirmatory: bool


class CorrectionScope(StrictModel):
    plan_manifest_hash: str
    registry_hash: str
    market: JsonMarket
    segment: JsonSegment
    source_metrics_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    source_bootstrap_hashes: Annotated[tuple[str, ...], Field(strict=False)]


class CorrectionArtifactBody(StrictModel):
    schema_version: Literal["v14.correction.1"]
    method: Literal["holm", "bh_fdr"]
    alpha: JsonDecimal
    family_size: int
    plan_manifest_hash: str
    registry_hash: str
    market: JsonMarket
    segment: JsonSegment
    source_metrics_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    source_bootstrap_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    results: Annotated[tuple[CorrectionResult, ...], Field(strict=False)]


class CorrectionArtifact(CorrectionArtifactBody):
    correction_hash: str


class ConstituentGate(StrictModel):
    strategy_id: str
    passed: bool
    verdict_hash: str


class RouterGateInput(StrictModel):
    plan_manifest_hash: str
    registry_hash: str
    orb_passed: bool
    orb_verdict_hash: str
    frozen_enabled_strategy_ids: Annotated[tuple[str, ...], Field(strict=False)]
    enabled_constituents: Annotated[tuple[ConstituentGate, ...], Field(strict=False)]
    router_metric_passed: bool
    paired_p_value: JsonDecimal
    mixed_metrics_hash: str
    deterministic_metrics_hash: str
    paired_metrics_hash: str


@unique
class RouterGateState(StrEnum):
    PASS = "pass"
    ORB_BLOCKED = "orb_blocked"
    CONSTITUENT_BLOCKED = "constituent_blocked"
    METRIC_BLOCKED = "metric_blocked"
    ALPHA_BLOCKED = "alpha_blocked"
    NOT_OPENED = "not_opened"


class RouterGateResult(StrictModel):
    state: Annotated[RouterGateState, Field(strict=False)]
    confirmatory_passed: bool
    enabled_strategy_ids: Annotated[tuple[str, ...], Field(strict=False)]
    paired_p_value: JsonDecimal
    plan_manifest_hash: str
    registry_hash: str
    orb_verdict_hash: str
    constituent_verdict_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    mixed_metrics_hash: str
    deterministic_metrics_hash: str
    paired_metrics_hash: str
    gate_hash: str


class RouterGateBody(StrictModel):
    state: Annotated[RouterGateState, Field(strict=False)]
    confirmatory_passed: bool
    enabled_strategy_ids: Annotated[tuple[str, ...], Field(strict=False)]
    paired_p_value: JsonDecimal
    plan_manifest_hash: str
    registry_hash: str
    orb_verdict_hash: str
    constituent_verdict_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    mixed_metrics_hash: str
    deterministic_metrics_hash: str
    paired_metrics_hash: str
