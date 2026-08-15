from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market

from .failure import V14Failure, V14FailureCode
from .manifest_models import ExperimentPlanManifest
from .observed_models import ObservedStrategyVerdictArtifact
from .prd02_pipeline import build_prd02_holdout_from, build_prd02_validation_from
from .prd03_pipeline import SegmentPrd03ArtifactsBody, build_prd03_segment_from
from .prd04_models import HoldoutApproval, HoldoutLease, HoldoutPlan
from .prd04_run_models import (
    HoldoutRunArtifact,
    HoldoutRunBody,
    ValidationMarketScope,
    ValidationRunArtifact,
    ValidationRunBody,
)
from .prd04_source_models import LoadedSources
from .prd04_sources import verify_source_evidence
from .selection_models import DevelopmentSelection
from .series_models import ResearchSegment
from .verdict_models import HoldoutVerdict, ValidationVerdict


def _eligible(
    verdicts: tuple[ObservedStrategyVerdictArtifact, ...], market: Market
) -> tuple[str, ...]:
    return tuple(item.hypothesis_id for item in verdicts
        if item.market is market and item.verdict is ValidationVerdict.PASS)


def validation_scopes(run: ValidationRunArtifact) -> tuple[ValidationMarketScope, ...]:
    return tuple(ValidationMarketScope(market=market,
        eligible_strategy_ids=_eligible(run.prd03.observed_strategy_verdicts, market),
        correction_hashes=tuple(item.correction_hash for item in
            (*run.prd03.holm_corrections, *run.prd03.bh_corrections)
            if item.market is market),
        verdict_hashes=tuple(item.verdict_hash for item in
            run.prd03.observed_strategy_verdicts if item.market is market),
        router_enabled_ids=gate.enabled_strategy_ids,
        router_verdict_hash=verdict.verdict_hash)
        for market, gate, verdict in zip(Market, run.prd03.router_gates,
            run.prd03.observed_router_verdicts, strict=True))


def build_validation_run(
    plan: ExperimentPlanManifest,
    selection: DevelopmentSelection,
    sources: LoadedSources,
) -> ValidationRunArtifact:
    prd02 = build_prd02_validation_from(plan, selection, sources.prd02)
    prd03 = build_prd03_segment_from(
        plan, prd02, sources.prd03, ResearchSegment.VALIDATION)
    provisional = ValidationRunArtifact(schema_version="v14.validation_run.1",
        plan_manifest_hash=plan.manifest_hash,
        source_evidence_hash=sources.evidence.evidence_hash,
        prd02=prd02, prd03=prd03, market_scopes=(), validation_run_hash="pending")
    scopes = validation_scopes(provisional)
    body = ValidationRunBody(schema_version="v14.validation_run.1",
        plan_manifest_hash=plan.manifest_hash,
        source_evidence_hash=sources.evidence.evidence_hash,
        prd02=prd02, prd03=prd03, market_scopes=scopes)
    artifact = ValidationRunArtifact(plan_manifest_hash=body.plan_manifest_hash,
        schema_version=body.schema_version,
        source_evidence_hash=body.source_evidence_hash,
        prd02=body.prd02, prd03=body.prd03, market_scopes=body.market_scopes,
        validation_run_hash=canonical_hash(model_json(body)))
    verify_validation_run(plan, sources, artifact)
    return artifact


def verify_validation_run(
    plan: ExperimentPlanManifest,
    sources: LoadedSources,
    run: ValidationRunArtifact,
) -> None:
    verify_source_evidence(sources.evidence)
    body = ValidationRunBody.model_validate(
        run.model_dump(exclude={"validation_run_hash"}))
    if canonical_hash(model_json(body)) != run.validation_run_hash:
        raise V14Failure(V14FailureCode.VALIDATION_TUNE, run.validation_run_hash)
    if run.plan_manifest_hash != plan.manifest_hash:
        raise V14Failure(V14FailureCode.POINT_IN_TIME, run.plan_manifest_hash)
    if run.source_evidence_hash != sources.evidence.evidence_hash:
        raise V14Failure(V14FailureCode.COHORT_CONTINUITY, run.source_evidence_hash)
    if (len(run.prd02.metrics), len(run.prd02.router_comparisons),
            len(run.prd03.holm_corrections), len(run.prd03.bh_corrections),
            len(run.prd03.observed_strategy_verdicts),
            len(run.prd03.observed_router_verdicts),
            len(run.prd03.router_gates),
            len(run.prd03.observed_verdicts)) != (30, 2, 2, 2, 30, 2, 2, 32):
        raise V14Failure(V14FailureCode.VALIDATION_GATE, "validation inventory")
    if any(item.segment is not ResearchSegment.VALIDATION
            or item.sample.required_signal_days != 60
            or item.sample.required_completed_trades != 150
            or not item.sample.sufficient for item in run.prd02.metrics):
        raise V14Failure(V14FailureCode.VALIDATION_GATE, "validation sample")
    if any(item.segment is not ResearchSegment.VALIDATION
            for item in (*run.prd03.holm_corrections, *run.prd03.bh_corrections)):
        raise V14Failure(V14FailureCode.MULTIPLE_TESTING, "validation correction")
    prd03_body = SegmentPrd03ArtifactsBody.model_validate(
        run.prd03.model_dump(exclude={"artifact_hash"}))
    if canonical_hash(model_json(prd03_body)) != run.prd03.artifact_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "validation verdict artifact")
    if run.market_scopes != validation_scopes(run) or len(run.market_scopes) != 2:
        raise V14Failure(V14FailureCode.VERDICT, "validation eligible set")


def build_holdout_run(
    plan: ExperimentPlanManifest,
    selection: DevelopmentSelection,
    sources: LoadedSources,
    holdout_plan: HoldoutPlan,
    approval: HoldoutApproval,
    lease: HoldoutLease,
    validation: ValidationRunArtifact,
) -> HoldoutRunArtifact:
    prd02 = build_prd02_holdout_from(plan, selection, sources.prd02)
    prd03 = build_prd03_segment_from(
        plan, prd02, sources.prd03, ResearchSegment.HOLDOUT)
    verdict_hash = canonical_hash(
        [item.verdict_hash for item in prd03.observed_verdicts])
    body = HoldoutRunBody(schema_version="v14.holdout_run.1",
        plan_manifest_hash=plan.manifest_hash, holdout_plan_hash=holdout_plan.plan_hash,
        approval_hash=approval.approval_hash, lease_hash=lease.lease_hash,
        validation_run_hash=validation.validation_run_hash,
        source_evidence_hash=sources.evidence.evidence_hash,
        prd02=prd02, prd03=prd03, verdict_inventory_hash=verdict_hash)
    artifact = HoldoutRunArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash,
        holdout_plan_hash=body.holdout_plan_hash,
        approval_hash=body.approval_hash, lease_hash=body.lease_hash,
        validation_run_hash=body.validation_run_hash,
        source_evidence_hash=body.source_evidence_hash,
        prd02=body.prd02, prd03=body.prd03,
        verdict_inventory_hash=body.verdict_inventory_hash,
        holdout_run_hash=canonical_hash(model_json(body)))
    verify_holdout_run(holdout_plan, approval, lease, validation, artifact)
    return artifact


def verify_holdout_run(
    plan: HoldoutPlan,
    approval: HoldoutApproval,
    lease: HoldoutLease,
    validation: ValidationRunArtifact,
    run: HoldoutRunArtifact,
) -> None:
    body = HoldoutRunBody.model_validate(
        run.model_dump(exclude={"holdout_run_hash"}))
    if canonical_hash(model_json(body)) != run.holdout_run_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, run.holdout_run_hash)
    if (run.holdout_plan_hash, run.approval_hash, run.lease_hash,
            run.validation_run_hash) != (plan.plan_hash, approval.approval_hash,
            lease.lease_hash, validation.validation_run_hash):
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, run.holdout_run_hash)
    if (len(run.prd02.metrics), len(run.prd02.router_comparisons),
            len(run.prd03.holm_corrections), len(run.prd03.bh_corrections),
            len(run.prd03.observed_strategy_verdicts),
            len(run.prd03.observed_router_verdicts),
            len(run.prd03.router_gates),
            len(run.prd03.observed_verdicts)) != (30, 2, 2, 2, 30, 2, 2, 32):
        raise V14Failure(V14FailureCode.VALIDATION_GATE, "holdout inventory")
    if run.plan_manifest_hash != plan.plan_manifest_hash \
            or run.source_evidence_hash != plan.source_evidence_hash:
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, "holdout lineage")
    if any(item.segment is not ResearchSegment.HOLDOUT
            or item.sample.required_signal_days != 100
            or item.sample.required_completed_trades != 300
            for item in run.prd02.metrics):
        raise V14Failure(V14FailureCode.VALIDATION_GATE, "holdout segment")
    if tuple(gate.enabled_strategy_ids for gate in run.prd03.router_gates) \
            != tuple(scope.router_enabled_ids for scope in plan.market_scopes):
        raise V14Failure(V14FailureCode.VERDICT, "router enabled set")
    prd03_body = SegmentPrd03ArtifactsBody.model_validate(
        run.prd03.model_dump(exclude={"artifact_hash"}))
    if canonical_hash(model_json(prd03_body)) != run.prd03.artifact_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "holdout verdict artifact")
    if canonical_hash([item.verdict_hash for item in
            run.prd03.observed_verdicts]) != run.verdict_inventory_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "verdict inventory")
    verify_holdout_samples(run)


def verify_holdout_samples(run: HoldoutRunArtifact) -> None:
    verdicts = {item.metrics_hash: item for item in
        run.prd03.observed_strategy_verdicts}
    for metric in run.prd02.metrics:
        observed = verdicts.get(metric.metrics_hash)
        if observed is None:
            raise V14Failure(V14FailureCode.VERDICT, metric.metrics_hash)
        verdict = observed.verdict
        if not metric.sample.sufficient and verdict is not HoldoutVerdict.INSUFFICIENT_SAMPLE:
            raise V14Failure(V14FailureCode.SAMPLE_INSUFFICIENT, metric.metrics_hash)
