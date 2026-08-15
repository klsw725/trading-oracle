from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from .contract import StrictModel
from .manifest_models import ExperimentPlanManifest
from .prd04_run_models import HoldoutRunArtifact, ValidationMarketScope, ValidationRunArtifact
from .prd04_source_models import Prd04Source, SourceEvidence


class HoldoutMarketScope(ValidationMarketScope):
    holdout_period_hash: str


class HoldoutPlanBody(StrictModel):
    schema_version: Literal["v14.holdout_plan.2"]
    plan_manifest_hash: str
    validation_run_hash: str
    source_evidence_hash: str
    market_scopes: Annotated[tuple[HoldoutMarketScope, ...], Field(strict=False)]
    cost_model_id: str


class HoldoutPlan(HoldoutPlanBody):
    plan_hash: str


class HoldoutApprovalBody(StrictModel):
    schema_version: Literal["v14.holdout_approval.2"]
    plan_hash: str
    approved_manifest_hash: str
    approved_validation_run_hash: str
    approved_source_evidence_hash: str
    approved_cost_model_id: str
    operator_id: str
    approved_at: AwareDatetime
    approval_reason: str


class HoldoutApproval(HoldoutApprovalBody):
    approval_hash: str


class HoldoutLeaseBody(StrictModel):
    schema_version: Literal["v14.holdout_lease.2"]
    lease_id: str
    plan_hash: str
    approval_hash: str
    prior_history_head: str


class HoldoutLease(HoldoutLeaseBody):
    lease_hash: str


class HistoryEntryBody(StrictModel):
    schema_version: Literal["v14.holdout_history_entry.2"]
    sequence: int
    lease_id: str
    lease_hash: str
    plan_hash: str
    holdout_run_hash: str
    prior_head_hash: str


class HistoryEntry(HistoryEntryBody):
    entry_hash: str


class HoldoutHistory(StrictModel):
    schema_version: Literal["v14.holdout_history.1"]
    genesis_head_hash: str
    entries: Annotated[tuple[HistoryEntry, ...], Field(strict=False)]
    head_hash: str


class ResultManifestBody(StrictModel):
    schema_version: Literal["v14.result_manifest.2"]
    experiment_version: str
    plan_manifest_hash: str
    plan_contract_hash: str
    source_evidence_hash: str
    holdout_plan_hash: str
    approval_hash: str
    lease_hash: str
    validation_run_hash: str
    holdout_run_hash: str
    verdict_inventory_hash: str
    history_head_hash: str
    promotion_eligible: Literal[False]
    paper_side_effect_count: Literal[0]
    live_side_effect_count: Literal[0]


class ResultManifest(ResultManifestBody):
    result_manifest_hash: str


class CompatibilityEvidence(StrictModel):
    v10_prd_count: Literal[4]
    v11_prd_count: Literal[4]
    v12_strategy_count: Literal[15]
    v12_case_count: Literal[45]
    v13_probe_count: Literal[13]
    v13_replay_provider_call_count: Literal[0]
    compatibility_hash: str


class V14ResultBundleBody(StrictModel):
    schema_version: Literal["v14.result_bundle.2"]
    source: Prd04Source
    source_evidence: SourceEvidence
    plan: ExperimentPlanManifest
    validation_run: ValidationRunArtifact
    holdout_plan: HoldoutPlan
    approval: HoldoutApproval
    lease: HoldoutLease
    prior_history: HoldoutHistory
    holdout_run: HoldoutRunArtifact
    history: HoldoutHistory
    result_manifest: ResultManifest
    compatibility: CompatibilityEvidence
    verdict_inventory: Annotated[tuple[str, ...], Field(strict=False)]
    promotion_eligible: Literal[False]
    paper_side_effect_count: Literal[0]
    live_side_effect_count: Literal[0]


class V14ResultBundle(V14ResultBundleBody):
    bundle_hash: str
