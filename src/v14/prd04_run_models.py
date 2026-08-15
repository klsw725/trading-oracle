from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .cohort_models import JsonMarket
from .contract import StrictModel
from .prd02_pipeline import Prd02Artifacts
from .prd03_pipeline import SegmentPrd03Artifacts


class ValidationMarketScope(StrictModel):
    market: JsonMarket
    eligible_strategy_ids: Annotated[tuple[str, ...], Field(strict=False)]
    correction_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    verdict_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    router_enabled_ids: Annotated[tuple[str, ...], Field(strict=False)]
    router_verdict_hash: str


class ValidationRunBody(StrictModel):
    schema_version: Literal["v14.validation_run.1"]
    plan_manifest_hash: str
    source_evidence_hash: str
    prd02: Prd02Artifacts
    prd03: SegmentPrd03Artifacts
    market_scopes: Annotated[tuple[ValidationMarketScope, ...], Field(strict=False)]


class ValidationRunArtifact(ValidationRunBody):
    validation_run_hash: str


class HoldoutRunBody(StrictModel):
    schema_version: Literal["v14.holdout_run.1"]
    plan_manifest_hash: str
    holdout_plan_hash: str
    approval_hash: str
    lease_hash: str
    validation_run_hash: str
    source_evidence_hash: str
    prd02: Prd02Artifacts
    prd03: SegmentPrd03Artifacts
    verdict_inventory_hash: str


class HoldoutRunArtifact(HoldoutRunBody):
    holdout_run_hash: str
