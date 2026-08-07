from datetime import datetime

from .source_bundle import SourceBundleManifest, verify_source_bundle
from .source_context import TrustedCompilerContext
from .source_models import IncidentCode, LifecycleState, PromotionObservation, SourcePolicyError, contract_expired
from .source_operations import IncidentOperation, PromotionOperation, RetirementOperation, SourceOperation
from .source_policy import SourcePolicySnapshot


_PROMOTION_STEPS = {
    (LifecycleState.CANDIDATE, LifecycleState.SHADOW, "0.00"),
    (LifecycleState.SHADOW, LifecycleState.CANARY, "0.05"),
    (LifecycleState.CANARY, LifecycleState.LIMITED, "0.25"),
    (LifecycleState.LIMITED, LifecycleState.LIMITED, "0.50"),
    (LifecycleState.LIMITED, LifecycleState.PRIMARY, "1.00"),
}


def _promotion_gates(operation: PromotionOperation, manifest: SourceBundleManifest, context: TrustedCompilerContext) -> None:
    verify_source_bundle(manifest, context.value_context)
    evaluate_verified_artifacts(operation, manifest, context)


def evaluate_verified_artifacts(operation: PromotionOperation, manifest: SourceBundleManifest, context: TrustedCompilerContext) -> None:
    if manifest.contract != context.contract:
        raise SourcePolicyError("SOURCE_CONTEXT_MISMATCH", "contract")
    if operation.owner_approval is None:
        raise SourcePolicyError("OWNER_APPROVAL_MISSING", operation.operation_id)
    if operation.owner_approval.accountable_owner == operation.owner_approval.reviewer:
        raise SourcePolicyError("OWNER_REVIEWER_CONFLICT", operation.operation_id)
    if operation.owner_approval != context.promotion_approval:
        raise SourcePolicyError("SOURCE_CONTEXT_MISMATCH", "promotion approval")
    if operation.observation.attempts < 100:
        raise SourcePolicyError("INSUFFICIENT_OBSERVATIONS", operation.operation_id)
    if operation.expected_source_bundle_hash != manifest.source_bundle_hash:
        raise SourcePolicyError("SOURCE_BUNDLE_HASH_MISMATCH", operation.operation_id)
    if operation.expected_contract_hash != manifest.contract.contract_ref_hash:
        raise SourcePolicyError("CONTRACT_HASH_MISMATCH", operation.operation_id)
    if any(item.freshness_label != "fresh" for item in manifest.quality):
        raise SourcePolicyError("QUALITY_STALE", operation.operation_id)
    if any(item.quality_label == "degraded" for item in manifest.quality):
        raise SourcePolicyError("QUALITY_DEGRADED", operation.operation_id)
    if any(item.quality_label == "blocked" or any(claim.opposing_cluster_ids for claim in item.claims) for item in manifest.quality):
        raise SourcePolicyError("QUALITY_CONTRADICTORY", operation.operation_id)
    if manifest.value.terminal_code != "PASS_INCREMENTAL_VALUE_EVALUATION" or not manifest.value.promotion_eligible:
        raise SourcePolicyError("VALUE_NOT_PASS", operation.operation_id)
    trusted_value = context.value_context
    if trusted_value.outcome_root is None or manifest.value.outcome_adapter_root != str(trusted_value.outcome_root):
        raise SourcePolicyError("MISSING_OUTCOME_ADAPTER", operation.operation_id)
    metrics = manifest.value.metrics
    expected_observation = PromotionObservation(
        attempts=metrics.eligible_pairs,
        harm_events=int(metrics.harm_rate * metrics.eligible_pairs),
        timeout_spikes=int(metrics.timeout_rate * metrics.eligible_pairs),
        stale_cache_events=0,
    )
    if operation.observation != expected_observation:
        raise SourcePolicyError("OBSERVATION_CONTEXT_MISMATCH", operation.operation_id)


def evaluate_operation(operation: SourceOperation, current: SourcePolicySnapshot, manifest: SourceBundleManifest, context: TrustedCompilerContext, evaluated_at: datetime) -> LifecycleState:
    if operation.expected_prior_policy_hash != current.policy_hash:
        raise SourcePolicyError("POLICY_HASH_MISMATCH", operation.operation_id)
    match operation:  # noqa: MATCH_OK - SourceOperation union is fully enumerated
        case PromotionOperation():
            if current.state in (LifecycleState.DISABLED, LifecycleState.RETIRED, LifecycleState.EXPIRED):
                raise SourcePolicyError("CLOSED_STATE_REOPEN", operation.operation_id)
            matching_state = tuple(step for step in _PROMOTION_STEPS if step[:2] == (current.state, operation.to_state))
            if not matching_state:
                raise SourcePolicyError("ILLEGAL_PROMOTION_JUMP", operation.operation_id)
            if operation.traffic_share != matching_state[0][2]:
                raise SourcePolicyError("ILLEGAL_TRAFFIC_SHARE", operation.operation_id)
            if contract_expired(manifest.contract, evaluated_at):
                raise SourcePolicyError("CONTRACT_EXPIRED_SOURCE_ACTIVE", operation.operation_id)
            if manifest.contract.license_scope != "internal_prompt_eligible_hash_only":
                raise SourcePolicyError("LICENSE_CURRENT_USE_FORBIDDEN", operation.operation_id)
            _promotion_gates(operation, manifest, context)
            return operation.to_state
        case IncidentOperation():
            if operation.traffic_share not in ("0", "0.00"):
                raise SourcePolicyError("DISABLE_TRAFFIC_NOT_ZERO", operation.operation_id)
            authorization = tuple(item for item in context.incident_authorizations if (item.incident_code, item.evidence_hash, item.source_bundle_id) == (operation.incident_code, operation.evidence_hash, manifest.source_bundle_id))
            if len(authorization) != 1:
                raise SourcePolicyError("INCIDENT_UNAUTHORIZED", operation.operation_id)
            return LifecycleState.EXPIRED if operation.incident_code is IncidentCode.CONTRACT_EXPIRED else LifecycleState.DISABLED
        case RetirementOperation():
            if operation.delete_retained_history:
                raise SourcePolicyError("RETENTION_DELETION_FORBIDDEN", operation.operation_id)
            if current.state is LifecycleState.EXPIRED:
                return LifecycleState.RETIRED
            if contract_expired(manifest.contract, evaluated_at):
                return LifecycleState.EXPIRED
            if current.state in (LifecycleState.CANARY, LifecycleState.LIMITED, LifecycleState.PRIMARY, LifecycleState.DISABLED):
                return LifecycleState.RETIRING
            if current.state is LifecycleState.RETIRING:
                return LifecycleState.RETIRED
            raise SourcePolicyError("ILLEGAL_PROMOTION_JUMP", operation.operation_id)
