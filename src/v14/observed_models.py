from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .cohort_models import JsonMarket
from .contract import StrictModel
from .series_models import JsonSegment
from .verdict_models import HoldoutVerdict, ValidationVerdict


type ObservedVerdict = ValidationVerdict | HoldoutVerdict
type RouterObservedVerdict = ObservedVerdict | Literal["HOLDOUT_NOT_OPENED"]


class ObservedStrategyVerdictBody(StrictModel):
    schema_version: Literal["v14.observed_strategy_verdict.1"]
    plan_manifest_hash: str
    registry_hash: str
    market: JsonMarket
    segment: JsonSegment
    hypothesis_id: str
    configuration_id: str
    metrics_hash: str
    bootstrap_hash: str
    correction_hash: str | None
    evidence_hash: str
    correction_passed: bool
    verdict: ObservedVerdict


class ObservedStrategyVerdictArtifact(ObservedStrategyVerdictBody):
    verdict_hash: str


class ObservedRouterVerdictBody(StrictModel):
    schema_version: Literal["v14.observed_router_verdict.1"]
    plan_manifest_hash: str
    registry_hash: str
    market: JsonMarket
    segment: JsonSegment
    selected_policy_id: str
    comparison_hash: str
    mixed_metrics_hash: str
    deterministic_metrics_hash: str
    paired_metrics_hash: str
    mixed_raw_verdict_hash: str | None
    paired_raw_verdict_hash: str | None
    orb_verdict_hash: str
    constituent_verdict_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    gate_hash: str
    verdict: RouterObservedVerdict


class ObservedRouterVerdictArtifact(ObservedRouterVerdictBody):
    verdict_hash: str
