from dataclasses import dataclass

from src.v4.models import canonical_hash

from .lifecycle_evidence import hash_body
from .lifecycle_events import EventType, LifecycleEvent, LifecycleEventBody, OperationPayload, PolicyEmittedPayload, event_hash_json
from .lifecycle_models import LifecycleDecision, LifecycleState
from .lifecycle_operations import ExpiryOperation, IncidentOperation, LifecycleOperation, PromotionOperation, RenewalOperation, ReopenOperation, RetirementAssessmentOperation, RetirementOperation, RollbackOperation
from .lifecycle_policy import ConsensusPolicyArtifact, CurrentConsensusPolicy
from .offline_models import ContentHash


@dataclass(frozen=True, slots=True)
class LedgerCompilation:
    operation: LifecycleOperation
    decision: LifecycleDecision
    policy: ConsensusPolicyArtifact | CurrentConsensusPolicy | None
    evidence_hash: ContentHash
    occurred_at: str


def semantic_ledger(compilation: LedgerCompilation) -> tuple[LifecycleEvent, ...]:
    operation, decision, policy = compilation.operation, compilation.decision, compilation.policy
    prior = operation.prior_history.events if operation.prior_history is not None else ()
    payload = OperationPayload(kind="operation", operation_type=operation.operation_type, operation_id=operation.lifecycle_input.operation_id, idempotency_key=operation.lifecycle_input.idempotency_key, result_code=decision.result_code.value, evidence_hash=compilation.evidence_hash, approval_hash=approval_hash_for(operation), policy_hash=policy.policy_hash if policy else None, source_paper_artifact_hash=source_paper_hash_for(operation), session_ordinal=operation.lifecycle_input.current_session_ordinal)
    events = prior
    if isinstance(operation, PromotionOperation) and operation.prior_history is None:
        events = append(events, compilation, "lifecycle_created", None, LifecycleState.PAPER_READY, None, payload)
    event_type: EventType
    match operation:  # noqa: MATCH_OK - LifecycleOperation is a closed discriminated union
        case PromotionOperation(): event_type = "limited_promotion_approved" if policy else "lifecycle_rejected"
        case IncidentOperation(): event_type = "renewal_review_started" if decision.result_code.value == "RENEWAL_REVIEW_OPENED" else "incident_recorded"
        case ExpiryOperation(): event_type = "renewal_review_started"
        case RenewalOperation(): event_type = "limited_renewal_approved"
        case RollbackOperation(): event_type = "lifecycle_rolled_back"
        case RetirementAssessmentOperation(): event_type = "retirement_required"
        case RetirementOperation(): event_type = "lifecycle_retired"
        case ReopenOperation(): event_type = "lifecycle_reopened"
    events = append(events, compilation, event_type, decision.prior_state, decision.next_state, policy.policy_version if policy else operation.current_policy.policy_version, payload)
    if policy is None or isinstance(policy, CurrentConsensusPolicy):
        return events
    emitted = PolicyEmittedPayload(kind="policy_emitted", operation_id=operation.lifecycle_input.operation_id, idempotency_key=operation.lifecycle_input.idempotency_key, transition_event_hash=events[-1].event_hash, policy_hash=policy.policy_hash)
    return append(events, compilation, "policy_emitted", decision.next_state, decision.next_state, policy.policy_version, emitted)


def append(events: tuple[LifecycleEvent, ...], compilation: LedgerCompilation, event_type: EventType, before: LifecycleState | None, after: LifecycleState, policy_version: str | None, payload: OperationPayload | PolicyEmittedPayload) -> tuple[LifecycleEvent, ...]:
    value = compilation.operation.lifecycle_input
    body = LifecycleEventBody(schema_version="v6.consensus_lifecycle.event.3", candidate_id=value.candidate_id, candidate_version=value.candidate_version, hypothesis_id=value.hypothesis_id, policy_version=policy_version, event_index=len(events), event_type=event_type, lifecycle_state_before=before, lifecycle_state_after=after, occurred_at=compilation.occurred_at, prev_event_hash=events[-1].event_hash if events else f"sha256:{'0' * 64}", payload_hash=hash_body(payload), payload=payload)
    event = LifecycleEvent.model_validate({**body.model_dump(mode="json"), "event_id": f"lifecycle_v6_{len(events):04d}", "event_hash": canonical_hash(event_hash_json(body))})
    return (*events, event)


def approval_hash_for(operation: LifecycleOperation) -> ContentHash | None:
    return operation.approval.approval_hash if isinstance(operation, (PromotionOperation, RenewalOperation, RollbackOperation, RetirementOperation)) else None


def source_paper_hash_for(operation: LifecycleOperation) -> ContentHash | None:
    if not isinstance(operation, RollbackOperation):
        return None
    value = operation.lifecycle_input
    candidate = next(item for item in operation.current_policy.active_candidates if (item.candidate_id, item.candidate_version) == (value.candidate_id, value.candidate_version))
    return candidate.source_paper_artifact_hash
