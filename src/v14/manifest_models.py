from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .cohort_models import JsonDate, JsonMarket
from .contract import StrictModel


class CodeState(StrictModel):
    commit: str
    dirty: bool


class RuntimeLock(StrictModel):
    python_version: str
    dependency_lock_hash: str


class ConfigState(StrictModel):
    config_hash: str
    feature_flags: Annotated[tuple[str, ...], Field(strict=False)]


class ComponentVersions(StrictModel):
    strategy: str
    parameters: str
    risk: str
    router: str


class UniverseState(StrictModel):
    universe_version: str
    eligibility_snapshot_chain: Annotated[tuple[str, ...], Field(strict=False)]


class ReferenceVersions(StrictModel):
    market_calendar: str
    corporate_actions: str


class DataManifestHashes(StrictModel):
    raw: Annotated[tuple[str, ...], Field(strict=False)]
    normalized: Annotated[tuple[str, ...], Field(strict=False)]
    derived: Annotated[tuple[str, ...], Field(strict=False)]


class SourceHistory(StrictModel):
    provenance: Annotated[tuple[str, ...], Field(strict=False)]
    fallback_history: Annotated[tuple[str, ...], Field(strict=False)]


class CostModels(StrictModel):
    baseline: str
    stress_2x_variable: str


class PromptContract(StrictModel):
    canonical_bytes_hex: str
    codex_model: str
    output_schema_hash: str


class BootstrapPlan(StrictModel):
    seed: int
    block_trading_days: Literal[5]
    resamples: Literal[10000]


class MarketPeriod(StrictModel):
    market: JsonMarket
    development_start: JsonDate
    validation_start: JsonDate
    holdout_start: JsonDate
    holdout_end: JsonDate


class HypothesisRegistry(StrictModel):
    primary_id: Literal["long_orb_15m"]
    holm_family_ids: Annotated[tuple[str, ...], Field(strict=False)]
    router_hypothesis_id: Literal["mixed_router_vs_deterministic"]
    router_candidate_registry: Annotated[tuple[str, ...], Field(strict=False)]
    router_enabled_set_freeze_stage: Literal["after_validation"]
    exploratory_ids: Annotated[tuple[str, ...], Field(strict=False)]


class PlanInputs(StrictModel):
    code: CodeState
    runtime_lock: RuntimeLock
    config: ConfigState
    components: ComponentVersions
    universes: Annotated[tuple[UniverseState, ...], Field(strict=False)]
    references: ReferenceVersions
    data: DataManifestHashes
    sources: SourceHistory
    costs: CostModels
    prompt: PromptContract
    bootstrap: BootstrapPlan
    exploratory_ids: Annotated[tuple[str, ...], Field(strict=False)]


class ExperimentPlanBody(StrictModel):
    schema_version: Literal["v14.experiment_plan.1"]
    cohort_hash: str
    selection_hash: str
    code: CodeState
    runtime_lock: RuntimeLock
    config: ConfigState
    components: ComponentVersions
    universes: Annotated[tuple[UniverseState, ...], Field(strict=False)]
    references: ReferenceVersions
    data: DataManifestHashes
    sources: SourceHistory
    costs: CostModels
    prompt: PromptContract
    bootstrap: BootstrapPlan
    periods: Annotated[tuple[MarketPeriod, ...], Field(strict=False)]
    hypotheses: HypothesisRegistry


class ExperimentPlanManifest(ExperimentPlanBody):
    experiment_version: str
    manifest_hash: str
