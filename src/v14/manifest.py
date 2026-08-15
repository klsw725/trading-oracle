from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json
from pydantic import ValidationError
from src.v4.models import JsonValue

from .failure import V14Failure, V14FailureCode
from .manifest_models import ExperimentPlanManifest
from .manifest_plan import result_free_plan, result_free_plan_hash
from .prd04_models import (
    HoldoutApproval,
    HoldoutHistory,
    HoldoutLease,
    HoldoutPlan,
    ResultManifest,
    ResultManifestBody,
)
from .prd04_run_models import HoldoutRunArtifact, ValidationRunArtifact
from .prd04_source_models import SourceEvidence


def verify_plan_manifest(plan: ExperimentPlanManifest) -> None:
    required_sequences = (plan.config.feature_flags, plan.universes,
        plan.data.raw, plan.data.normalized, plan.data.derived,
        plan.sources.provenance, plan.periods,
        plan.hypotheses.holm_family_ids,
        plan.hypotheses.router_candidate_registry)
    required_text = (plan.code.commit, plan.runtime_lock.python_version,
        plan.runtime_lock.dependency_lock_hash, plan.config.config_hash,
        plan.components.strategy, plan.components.parameters,
        plan.components.risk, plan.components.router,
        plan.references.market_calendar, plan.references.corporate_actions,
        plan.costs.baseline, plan.costs.stress_2x_variable,
        plan.prompt.canonical_bytes_hex, plan.prompt.codex_model,
        plan.prompt.output_schema_hash)
    if any(not item for item in required_sequences) or any(not item for item in required_text):
        raise V14Failure(V14FailureCode.MANIFEST_INCOMPLETE, plan.manifest_hash)
    expected = canonical_hash(model_json(result_free_plan(plan)))
    if expected != plan.manifest_hash:
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, plan.manifest_hash)


def verify_manifest_value(value: JsonValue) -> ExperimentPlanManifest:
    try:
        plan = ExperimentPlanManifest.model_validate(value)
    except ValidationError as error:
        raise V14Failure(V14FailureCode.MANIFEST_INCOMPLETE, str(error)) from error
    verify_plan_manifest(plan)
    return plan


def build_result_manifest(
    plan: ExperimentPlanManifest,
    source_evidence: SourceEvidence,
    holdout_plan: HoldoutPlan,
    approval: HoldoutApproval,
    lease: HoldoutLease,
    validation: ValidationRunArtifact,
    holdout: HoldoutRunArtifact,
    history: HoldoutHistory,
) -> ResultManifest:
    verify_plan_manifest(plan)
    body = ResultManifestBody(schema_version="v14.result_manifest.2",
        experiment_version=plan.experiment_version,
        plan_manifest_hash=plan.manifest_hash,
        plan_contract_hash=result_free_plan_hash(plan),
        source_evidence_hash=source_evidence.evidence_hash,
        holdout_plan_hash=holdout_plan.plan_hash,
        approval_hash=approval.approval_hash, lease_hash=lease.lease_hash,
        validation_run_hash=validation.validation_run_hash,
        holdout_run_hash=holdout.holdout_run_hash,
        verdict_inventory_hash=holdout.verdict_inventory_hash,
        history_head_hash=history.head_hash,
        promotion_eligible=False, paper_side_effect_count=0,
        live_side_effect_count=0)
    return ResultManifest(schema_version=body.schema_version,
        experiment_version=body.experiment_version,
        plan_manifest_hash=body.plan_manifest_hash,
        plan_contract_hash=body.plan_contract_hash,
        source_evidence_hash=body.source_evidence_hash,
        holdout_plan_hash=body.holdout_plan_hash,
        approval_hash=body.approval_hash, lease_hash=body.lease_hash,
        validation_run_hash=body.validation_run_hash,
        holdout_run_hash=body.holdout_run_hash,
        verdict_inventory_hash=body.verdict_inventory_hash,
        history_head_hash=body.history_head_hash,
        promotion_eligible=body.promotion_eligible,
        paper_side_effect_count=body.paper_side_effect_count,
        live_side_effect_count=body.live_side_effect_count,
        result_manifest_hash=canonical_hash(model_json(body)))


def verify_result_manifest(
    plan: ExperimentPlanManifest, result: ResultManifest
) -> None:
    verify_plan_manifest(plan)
    body = ResultManifestBody.model_validate(
        result.model_dump(exclude={"result_manifest_hash"}))
    if result.plan_manifest_hash != plan.manifest_hash \
            or result.experiment_version != plan.experiment_version \
            or result.plan_contract_hash != result_free_plan_hash(plan):
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, result.plan_manifest_hash)
    if canonical_hash(model_json(body)) != result.result_manifest_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, result.result_manifest_hash)
