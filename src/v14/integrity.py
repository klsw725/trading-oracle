from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from src.v4.models import canonical_json
from src.v11.canonical import canonical_hash, model_json, parse_json
from src.v11.models import V11ContractError

from .failure import V14Failure, V14FailureCode
from .compatibility import build_compatibility
from .holdout import consume_lease, verify_history, verify_holdout_plan
from .manifest import verify_result_manifest
from .prd04_bundle import ROOT, build_prd04_from_loaded
from .prd04_models import (
    HoldoutApprovalBody,
    HoldoutApproval,
    HoldoutLease,
    HoldoutLeaseBody,
    HoldoutPlan,
    HoldoutPlanBody,
    V14ResultBundle,
    V14ResultBundleBody,
)
from .prd04_runs import verify_holdout_run, verify_validation_run
from .prd04_sources import load_sources, verify_source_evidence


_BUNDLE = TypeAdapter(V14ResultBundle)


def _plan_hash(value: HoldoutPlan) -> str:
    return canonical_hash(model_json(HoldoutPlanBody.model_validate(
        value.model_dump(exclude={"plan_hash"}))))


def _approval_hash(value: HoldoutApproval) -> str:
    return canonical_hash(model_json(HoldoutApprovalBody.model_validate(
        value.model_dump(exclude={"approval_hash"}))))


def _lease_hash(value: HoldoutLease) -> str:
    return canonical_hash(model_json(HoldoutLeaseBody.model_validate(
        value.model_dump(exclude={"lease_hash"}))))


def verify_bundle(payload: bytes, root: Path = ROOT) -> V14ResultBundle:
    try:
        _ = parse_json(payload)
        bundle = _BUNDLE.validate_json(payload)
    except (ValidationError, V11ContractError) as error:
        raise V14Failure(V14FailureCode.ARTIFACT_MALFORMED, str(error)) from error
    sources = load_sources(bundle.source, root)
    verify_source_evidence(bundle.source_evidence)
    if sources.evidence != bundle.source_evidence:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "source evidence")
    verify_validation_run(bundle.plan, sources, bundle.validation_run)
    verify_holdout_plan(bundle.plan, sources, bundle.validation_run,
        bundle.holdout_plan)
    if _plan_hash(bundle.holdout_plan) != bundle.holdout_plan.plan_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "holdout plan")
    if _approval_hash(bundle.approval) != bundle.approval.approval_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "approval")
    if _lease_hash(bundle.lease) != bundle.lease.lease_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "lease")
    if bundle.lease.plan_hash != bundle.holdout_plan.plan_hash \
            or bundle.lease.approval_hash != bundle.approval.approval_hash:
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, "lease lineage")
    verify_history(bundle.prior_history)
    if bundle.lease.prior_history_head != bundle.prior_history.head_hash:
        raise V14Failure(V14FailureCode.HOLDOUT_REUSE, "prior history")
    verify_holdout_run(bundle.holdout_plan, bundle.approval, bundle.lease,
        bundle.validation_run, bundle.holdout_run)
    expected_history = consume_lease(bundle.prior_history, bundle.lease,
        bundle.holdout_run.holdout_run_hash)
    if expected_history != bundle.history:
        raise V14Failure(V14FailureCode.HOLDOUT_REUSE, "consumed history")
    verify_result_manifest(bundle.plan, bundle.result_manifest)
    result = bundle.result_manifest
    lineage = (result.source_evidence_hash, result.holdout_plan_hash,
        result.approval_hash, result.lease_hash, result.validation_run_hash,
        result.holdout_run_hash, result.verdict_inventory_hash,
        result.history_head_hash)
    expected = (bundle.source_evidence.evidence_hash,
        bundle.holdout_plan.plan_hash, bundle.approval.approval_hash,
        bundle.lease.lease_hash, bundle.validation_run.validation_run_hash,
        bundle.holdout_run.holdout_run_hash,
        bundle.holdout_run.verdict_inventory_hash, bundle.history.head_hash)
    if lineage != expected:
        raise V14Failure(V14FailureCode.MANIFEST_MISMATCH, "result lineage")
    if build_compatibility(sources.v13) != bundle.compatibility:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "compatibility")
    body = V14ResultBundleBody.model_validate(
        bundle.model_dump(exclude={"bundle_hash"}))
    if canonical_hash(model_json(body)) != bundle.bundle_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, bundle.bundle_hash)
    rebuilt = build_prd04_from_loaded(
        bundle.source, bundle.prior_history, sources)
    if canonical_json(rebuilt.model_dump(mode="json")) != canonical_json(
            bundle.model_dump(mode="json")):
        raise V14Failure(V14FailureCode.HASH_MISMATCH, "derived bundle")
    return bundle
