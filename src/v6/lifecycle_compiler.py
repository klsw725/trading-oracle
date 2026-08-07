from dataclasses import dataclass

from .lifecycle_evaluator import evaluate_operation
from .lifecycle_context import CompilerContext
from .lifecycle_evidence import hash_body
from .lifecycle_incidents import CapIncident, DeliberationIncident, DirtyPolicyIncident, ErrorRateIncident, MonitoringIncident
from .lifecycle_models import LifecycleDecision, LifecycleInput, LifecycleResultCode, LifecycleState
from .lifecycle_operations import ExpiryOperation, IncidentAssessment, IncidentAssessmentBody, IncidentOperation, LifecycleOperation, PromotionOperation, RenewalOperation, ReopenOperation, RetirementAssessmentOperation, RetirementOperation, RollbackOperation
from .lifecycle_policy import ActiveCandidatePolicy, CandidateDeliberationPolicy, ConsensusPolicyArtifact, ConsensusPolicyBody, CurrentConsensusPolicy, IncidentThresholdPolicy, SourceTtlPolicy, weight_share
from .models import BoundaryModel, ContractInvariantError
from .offline_models import ContentHash


class CompiledOperation(BoundaryModel):
    decision: LifecycleDecision
    policy: ConsensusPolicyArtifact | CurrentConsensusPolicy | None
    evidence_hash: ContentHash


@dataclass(frozen=True, slots=True)
class PolicyEmission:
    current: CurrentConsensusPolicy | ConsensusPolicyArtifact
    lifecycle_input: LifecycleInput
    version: str
    candidates: tuple[ActiveCandidatePolicy, ...]


def compile_operation(operation: LifecycleOperation, context: CompilerContext) -> CompiledOperation:
    decision = evaluate_operation(operation, context)
    match operation:  # noqa: MATCH_OK - LifecycleOperation is a closed discriminated union
        case PromotionOperation():
            policy = promotion_policy(operation) if decision.result_code is LifecycleResultCode.PROMOTION_APPROVED_LIMITED else None
            return CompiledOperation(decision=decision, policy=policy, evidence_hash=operation.paper_artifact.artifact_hash)
        case IncidentOperation():
            policy = incident_review_policy(operation) if decision.result_code is LifecycleResultCode.RENEWAL_REVIEW_OPENED else None
            return CompiledOperation(decision=decision, policy=policy, evidence_hash=incident_evidence_hash(operation))
        case ExpiryOperation():
            return CompiledOperation(decision=decision, policy=expiry_policy(operation), evidence_hash=operation.prior_history.history_hash)
        case RenewalOperation():
            return CompiledOperation(decision=decision, policy=renewal_policy(operation), evidence_hash=operation.approval.approval_hash)
        case RollbackOperation():
            return CompiledOperation(decision=decision, policy=operation.rollback_policy, evidence_hash=operation.assessment.assessment_hash)
        case RetirementAssessmentOperation():
            return CompiledOperation(decision=decision, policy=None, evidence_hash=operation.prior_history.history_hash)
        case RetirementOperation():
            return CompiledOperation(decision=decision, policy=retirement_policy(operation), evidence_hash=operation.approval.approval_hash)
        case ReopenOperation():
            return CompiledOperation(decision=decision, policy=None, evidence_hash=operation.authorization.authorization_hash)


def promotion_policy(operation: PromotionOperation) -> ConsensusPolicyArtifact:
    approval, current, value = operation.approval, operation.current_policy, operation.lifecycle_input
    if approval.initial_weight is None or approval.policy_version is None or approval.approval_start_session_ordinal is None or approval.approval_duration_market_sessions is None:
        raise ContractInvariantError("promotion approval is incomplete")
    sources = tuple(SourceTtlPolicy(source_id=item.name, source_contract=item.source_contract or item.name) for item in operation.paper_artifact.paper_input.offline_artifact.candidate_artifact.candidate_proposal.input_contract.required_extra_inputs)
    candidate = ActiveCandidatePolicy(candidate_id=value.candidate_id, candidate_version=value.candidate_version, hypothesis_id=value.hypothesis_id, lifecycle_state=LifecycleState.LIMITED_PRODUCTION, source_paper_artifact_hash=operation.paper_artifact.artifact_hash, operator_approval_id=approval.approval_id, operator_approval_hash=approval.approval_hash, initial_weight=approval.initial_weight, total_valid_weight_share=weight_share(current.incumbent_weights, approval.initial_weight), approval_start_session_ordinal=approval.approval_start_session_ordinal, approval_end_session_ordinal=approval.approval_start_session_ordinal + approval.approval_duration_market_sessions - 1, rollback_policy_version=current.policy_version, rollback_policy_hash=current.policy_hash, deliberation=CandidateDeliberationPolicy(), incident_thresholds=IncidentThresholdPolicy(), source_ttl_policies=sources)
    preserved = tuple(item for item in current.active_candidates if item.candidate_id != value.candidate_id)
    return emitted_policy(PolicyEmission(current, value, approval.policy_version, (*preserved, candidate)))


def renewal_policy(operation: RenewalOperation) -> ConsensusPolicyArtifact:
    approval, current, value = operation.approval, operation.current_policy, operation.lifecycle_input
    if approval.policy_version is None or approval.approval_start_session_ordinal is None or approval.approval_duration_market_sessions is None:
        raise ContractInvariantError("renewal approval is incomplete")
    candidates = tuple(renewed_candidate(item, operation) if (item.candidate_id, item.candidate_version) == (value.candidate_id, value.candidate_version) else item for item in current.active_candidates)
    return emitted_policy(PolicyEmission(current, value, approval.policy_version, candidates))


def expiry_policy(operation: ExpiryOperation) -> ConsensusPolicyArtifact:
    value, current = operation.lifecycle_input, operation.current_policy
    candidates = tuple(item.model_copy(update={"lifecycle_state": LifecycleState.RENEWAL_REVIEW}) if (item.candidate_id, item.candidate_version) == (value.candidate_id, value.candidate_version) else item for item in current.active_candidates)
    return emitted_policy(PolicyEmission(current, value, operation.output_policy_version, candidates))


def incident_review_policy(operation: IncidentOperation) -> ConsensusPolicyArtifact:
    value, current = operation.lifecycle_input, operation.current_policy
    candidates = tuple(item.model_copy(update={"lifecycle_state": LifecycleState.RENEWAL_REVIEW}) if (item.candidate_id, item.candidate_version) == (value.candidate_id, value.candidate_version) else item for item in current.active_candidates)
    return emitted_policy(PolicyEmission(current, value, operation.output_policy_version, candidates))


def renewed_candidate(candidate: ActiveCandidatePolicy, operation: RenewalOperation) -> ActiveCandidatePolicy:
    approval = operation.approval
    if approval.approval_start_session_ordinal is None or approval.approval_duration_market_sessions is None:
        raise ContractInvariantError("renewal duration is missing")
    return candidate.model_copy(update={"lifecycle_state": LifecycleState.LIMITED_PRODUCTION, "operator_approval_id": approval.approval_id, "operator_approval_hash": approval.approval_hash, "approval_start_session_ordinal": approval.approval_start_session_ordinal, "approval_end_session_ordinal": approval.approval_start_session_ordinal + approval.approval_duration_market_sessions - 1})


def retirement_policy(operation: RetirementOperation) -> ConsensusPolicyArtifact:
    approval, current, value = operation.approval, operation.current_policy, operation.lifecycle_input
    if approval.policy_version is None:
        raise ContractInvariantError("retirement approval requires output policy version")
    candidates = tuple(item for item in current.active_candidates if (item.candidate_id, item.candidate_version) != (value.candidate_id, value.candidate_version))
    expected = len(current.active_candidates) - (1 if any((item.candidate_id, item.candidate_version) == (value.candidate_id, value.candidate_version) for item in current.active_candidates) else 0)
    if len(candidates) != expected:
        raise ContractInvariantError("retirement candidate projection mismatch")
    return emitted_policy(PolicyEmission(current, value, approval.policy_version, candidates))


def emitted_policy(emission: PolicyEmission) -> ConsensusPolicyArtifact:
    current, value = emission.current, emission.lifecycle_input
    body = ConsensusPolicyBody(schema_version="v6.consensus_policy.2", policy_version=emission.version, source_policy_version=current.policy_version, source_policy_hash=current.policy_hash, scorer_version=current.scorer_version, deliberator_version=current.deliberator_version, base_perspectives=current.base_perspectives, incumbent_weights=current.incumbent_weights, active_candidates=emission.candidates, incumbent_deliberation_policy_hash=current.incumbent_deliberation_policy_hash, observed_production_snapshot_hash=current.observed_production_snapshot_hash, authorizing_operation_id=value.operation_id, idempotency_key=value.idempotency_key, automatic_permanent_perspective=False, runtime_adoption="not_automatically_wired")
    return ConsensusPolicyArtifact.model_validate({**body.model_dump(mode="json"), "policy_hash": hash_body(body)})


def incident_evidence_hash(operation: IncidentOperation) -> ContentHash:
    match operation.report:  # noqa: MATCH_OK - IncidentReport is a closed discriminated union
        case ErrorRateIncident(error_window=window):
            return window.window_hash
        case MonitoringIncident(evidence=evidence):
            return evidence.evidence_hash
        case DeliberationIncident(evidence=evidence):
            return evidence.evidence_hash
        case CapIncident(evidence=evidence):
            return evidence.evidence_hash
        case DirtyPolicyIncident(evidence=evidence):
            return evidence.evidence_hash


def build_assessment(operation: IncidentOperation, context: CompilerContext) -> IncidentAssessment:
    decision = evaluate_operation(operation, context)
    body = IncidentAssessmentBody(schema_version="v6.lifecycle-incident-assessment.1", candidate_id=operation.lifecycle_input.candidate_id, candidate_version=operation.lifecycle_input.candidate_version, policy_version=operation.current_policy.policy_version, source_policy_hash=operation.current_policy.policy_hash, incident_evidence_hash=incident_evidence_hash(operation), decision=decision)
    return IncidentAssessment.model_validate({**body.model_dump(mode="json"), "assessment_hash": hash_body(body)})
