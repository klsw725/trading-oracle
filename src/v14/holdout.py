from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json
from src.v12.models import Market

from .failure import V14Failure, V14FailureCode
from .manifest_models import ExperimentPlanManifest
from .prd04_models import (
    HistoryEntry,
    HistoryEntryBody,
    HoldoutApproval,
    HoldoutApprovalBody,
    HoldoutHistory,
    HoldoutLease,
    HoldoutLeaseBody,
    HoldoutMarketScope,
    HoldoutPlan,
    HoldoutPlanBody,
)
from .prd04_run_models import ValidationRunArtifact
from .prd04_runs import verify_validation_run
from .prd04_source_models import ApprovalInput, LeaseInput, LoadedSources
from .hypothesis_models import RouterGateState
from .series_models import ResearchSegment
from .verdict_models import ValidationVerdict


def freeze_holdout_plan(
    manifest: ExperimentPlanManifest,
    sources: LoadedSources,
    validation: ValidationRunArtifact,
) -> HoldoutPlan:
    verify_validation_run(manifest, sources, validation)
    _verify_strict_validation(manifest, validation)
    scopes = _market_scopes(manifest, validation)
    if len(scopes) != 2 or any(not item.eligible_strategy_ids for item in scopes):
        raise V14Failure(V14FailureCode.VALIDATION_GATE, "market scopes")
    body = HoldoutPlanBody(schema_version="v14.holdout_plan.2",
        plan_manifest_hash=manifest.manifest_hash,
        validation_run_hash=validation.validation_run_hash,
        source_evidence_hash=sources.evidence.evidence_hash,
        market_scopes=scopes, cost_model_id=manifest.costs.stress_2x_variable)
    plan = HoldoutPlan(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash,
        validation_run_hash=body.validation_run_hash,
        source_evidence_hash=body.source_evidence_hash,
        market_scopes=body.market_scopes, cost_model_id=body.cost_model_id,
        plan_hash=canonical_hash(model_json(body)))
    verify_holdout_plan(manifest, sources, validation, plan)
    return plan


def _market_scopes(
    manifest: ExperimentPlanManifest,
    validation: ValidationRunArtifact,
) -> tuple[HoldoutMarketScope, ...]:
    return tuple(HoldoutMarketScope(market=scope.market,
        holdout_period_hash=canonical_hash({"market": scope.market.value,
            "start": next(item.holdout_start.isoformat() for item in manifest.periods
                if item.market is scope.market),
            "end": next(item.holdout_end.isoformat() for item in manifest.periods
                if item.market is scope.market)}),
        eligible_strategy_ids=scope.eligible_strategy_ids,
        correction_hashes=scope.correction_hashes,
        verdict_hashes=scope.verdict_hashes,
        router_enabled_ids=scope.router_enabled_ids,
        router_verdict_hash=scope.router_verdict_hash)
        for scope in validation.market_scopes)


def _verify_strict_validation(
    manifest: ExperimentPlanManifest,
    validation: ValidationRunArtifact,
) -> None:
    expected_ids = manifest.hypotheses.router_candidate_registry
    if len(expected_ids) != 15:
        raise V14Failure(V14FailureCode.VALIDATION_GATE, "strategy registry")
    rows = zip(Market, validation.market_scopes,
        validation.prd03.router_gates,
        validation.prd03.observed_router_verdicts, strict=True)
    for market, scope, gate, router in rows:
        strategies = tuple(item for item in
            validation.prd03.observed_strategy_verdicts
            if item.market is market
            and item.segment is ResearchSegment.VALIDATION)
        strategy_ids = tuple(item.hypothesis_id for item in strategies)
        if strategy_ids != expected_ids \
                or scope.eligible_strategy_ids != expected_ids \
                or any(item.verdict is not ValidationVerdict.PASS
                    for item in strategies) \
                or router.market is not market \
                or router.verdict is not ValidationVerdict.PASS \
                or gate.state is not RouterGateState.PASS \
                or not gate.confirmatory_passed:
            raise V14Failure(V14FailureCode.VALIDATION_GATE, market.value)


def verify_holdout_plan(
    manifest: ExperimentPlanManifest,
    sources: LoadedSources,
    validation: ValidationRunArtifact,
    plan: HoldoutPlan,
) -> None:
    verify_validation_run(manifest, sources, validation)
    _verify_strict_validation(manifest, validation)
    body = HoldoutPlanBody.model_validate(plan.model_dump(exclude={"plan_hash"}))
    if canonical_hash(model_json(body)) != plan.plan_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, plan.plan_hash)
    if (plan.plan_manifest_hash, plan.validation_run_hash,
            plan.source_evidence_hash, plan.cost_model_id) != (
            manifest.manifest_hash, validation.validation_run_hash,
            sources.evidence.evidence_hash, manifest.costs.stress_2x_variable):
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, plan.plan_hash)
    if plan.market_scopes != _market_scopes(manifest, validation):
        raise V14Failure(V14FailureCode.VERDICT, "frozen validation scopes")


def approve_holdout(
    plan: HoldoutPlan, approval: ApprovalInput
) -> HoldoutApproval:
    body = HoldoutApprovalBody(schema_version="v14.holdout_approval.2",
        plan_hash=plan.plan_hash, approved_manifest_hash=plan.plan_manifest_hash,
        approved_validation_run_hash=plan.validation_run_hash,
        approved_source_evidence_hash=plan.source_evidence_hash,
        approved_cost_model_id=plan.cost_model_id,
        operator_id=approval.operator_id, approved_at=approval.approved_at,
        approval_reason=approval.approval_reason)
    return HoldoutApproval(schema_version=body.schema_version,
        plan_hash=body.plan_hash,
        approved_manifest_hash=body.approved_manifest_hash,
        approved_validation_run_hash=body.approved_validation_run_hash,
        approved_source_evidence_hash=body.approved_source_evidence_hash,
        approved_cost_model_id=body.approved_cost_model_id,
        operator_id=body.operator_id, approved_at=body.approved_at,
        approval_reason=body.approval_reason,
        approval_hash=canonical_hash(model_json(body)))


def issue_lease(
    plan: HoldoutPlan,
    approval: HoldoutApproval,
    lease_input: LeaseInput,
    history: HoldoutHistory,
) -> HoldoutLease:
    if (approval.plan_hash, approval.approved_manifest_hash,
            approval.approved_validation_run_hash,
            approval.approved_source_evidence_hash,
            approval.approved_cost_model_id) != (plan.plan_hash,
            plan.plan_manifest_hash, plan.validation_run_hash,
            plan.source_evidence_hash, plan.cost_model_id):
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, plan.plan_hash)
    verify_history(history)
    if any(item.plan_hash == plan.plan_hash for item in history.entries):
        raise V14Failure(V14FailureCode.HOLDOUT_REUSE, plan.plan_hash)
    body = HoldoutLeaseBody(schema_version="v14.holdout_lease.2",
        lease_id=lease_input.lease_id, plan_hash=plan.plan_hash,
        approval_hash=approval.approval_hash,
        prior_history_head=history.head_hash)
    return HoldoutLease(schema_version=body.schema_version,
        lease_id=body.lease_id, plan_hash=body.plan_hash,
        approval_hash=body.approval_hash,
        prior_history_head=body.prior_history_head,
        lease_hash=canonical_hash(model_json(body)))


def initial_history(genesis_head_hash: str) -> HoldoutHistory:
    return HoldoutHistory(schema_version="v14.holdout_history.1",
        genesis_head_hash=genesis_head_hash, entries=(), head_hash=genesis_head_hash)


def verify_history(history: HoldoutHistory) -> None:
    head = history.genesis_head_hash
    seen: set[str] = set()
    for index, entry in enumerate(history.entries):
        body = HistoryEntryBody.model_validate(entry.model_dump(exclude={"entry_hash"}))
        if entry.sequence != index or entry.prior_head_hash != head \
                or canonical_hash(model_json(body)) != entry.entry_hash \
                or entry.plan_hash in seen:
            raise V14Failure(V14FailureCode.HOLDOUT_REUSE, history.head_hash)
        seen.add(entry.plan_hash)
        head = entry.entry_hash
    if history.head_hash != head:
        raise V14Failure(V14FailureCode.HOLDOUT_REUSE, history.head_hash)


def consume_lease(
    history: HoldoutHistory,
    lease: HoldoutLease,
    holdout_run_hash: str,
) -> HoldoutHistory:
    verify_history(history)
    if lease.prior_history_head != history.head_hash \
            or any(item.lease_id == lease.lease_id or item.plan_hash == lease.plan_hash
                for item in history.entries):
        raise V14Failure(V14FailureCode.HOLDOUT_REUSE, lease.lease_id)
    body = HistoryEntryBody(schema_version="v14.holdout_history_entry.2",
        sequence=len(history.entries), lease_id=lease.lease_id,
        lease_hash=lease.lease_hash, plan_hash=lease.plan_hash,
        holdout_run_hash=holdout_run_hash, prior_head_hash=history.head_hash)
    entry = HistoryEntry(schema_version=body.schema_version,
        sequence=body.sequence, lease_id=body.lease_id,
        lease_hash=body.lease_hash, plan_hash=body.plan_hash,
        holdout_run_hash=body.holdout_run_hash,
        prior_head_hash=body.prior_head_hash,
        entry_hash=canonical_hash(model_json(body)))
    return HoldoutHistory(schema_version=history.schema_version,
        genesis_head_hash=history.genesis_head_hash,
        entries=(*history.entries, entry), head_hash=entry.entry_hash)
