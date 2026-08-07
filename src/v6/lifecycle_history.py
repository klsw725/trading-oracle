from typing import Literal, Self

from pydantic import model_validator

from .lifecycle_evidence import hash_body
from .lifecycle_events import GENESIS_HASH, LifecycleEvent, OperationPayload, PolicyEmittedPayload
from .lifecycle_models import LifecycleState
from .lifecycle_registry import PolicyVersionRegistry
from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, HypothesisId
from .offline_models import ContentHash


class LifecycleHistoryBody(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.history.1"]
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    policy_registry: PolicyVersionRegistry
    genesis_policy_version: str
    genesis_policy_hash: ContentHash
    events: tuple[LifecycleEvent, ...]
    current_state: LifecycleState
    current_policy_version: str
    current_policy_hash: ContentHash
    head_event_hash: ContentHash
    next_event_index: int


class LifecycleHistory(LifecycleHistoryBody):
    history_hash: ContentHash

    @model_validator(mode="after")
    def verified_history(self) -> Self:
        validate_history(self)
        body = LifecycleHistoryBody.model_validate(self.model_dump(mode="json", exclude={"history_hash"}))
        if self.history_hash != hash_body(body):
            raise ContractInvariantError("lifecycle history hash mismatch")
        return self


def validate_history(history: LifecycleHistoryBody) -> None:
    if not history.events:
        raise ContractInvariantError("lifecycle history cannot be empty")
    previous_hash = GENESIS_HASH
    prior_state: LifecycleState | None = None
    operations: set[str] = set()
    idempotency: set[str] = set()
    operation_sequences: dict[str, tuple[str, ...]] = {}
    operation_payloads: dict[str, OperationPayload] = {}
    last_session_ordinal = 0
    policy_version = history.genesis_policy_version
    policy_hash = history.genesis_policy_hash
    registry = {item.policy_version: item.policy_hash for item in history.policy_registry.entries}
    if registry.get(history.genesis_policy_version) != history.genesis_policy_hash: raise ContractInvariantError("genesis policy is absent from authoritative registry")
    emitted_versions: set[str] = set()
    for index, event in enumerate(history.events):
        if event.event_index != index or event.prev_event_hash != previous_hash:
            raise ContractInvariantError("lifecycle history chain mismatch")
        if (event.candidate_id, event.candidate_version, event.hypothesis_id) != (history.candidate_id, history.candidate_version, history.hypothesis_id) or event.lifecycle_state_before is not prior_state:
            raise ContractInvariantError("lifecycle history identity or state mismatch")
        validate_event_semantics(event)
        if isinstance(event.payload, OperationPayload):
            seen_operation = event.payload.operation_id in operations
            seen_idempotency = event.payload.idempotency_key in idempotency
            if seen_operation != seen_idempotency:
                raise ContractInvariantError("operation identity and idempotency key were reused inconsistently")
            if seen_operation:
                sequence = operation_sequences[event.payload.operation_id]
                if event.payload.operation_type != "promotion" or sequence != ("lifecycle_created",) or event.event_type not in ("limited_promotion_approved", "lifecycle_rejected") or operation_payloads[event.payload.operation_id] != event.payload:
                    raise ContractInvariantError("lifecycle operation payload replay is forbidden")
                operation_sequences[event.payload.operation_id] = (*sequence, event.event_type)
            else:
                if event.payload.session_ordinal < last_session_ordinal:
                    raise ContractInvariantError("lifecycle operation session ordinals must be monotonic")
                operations.add(event.payload.operation_id)
                idempotency.add(event.payload.idempotency_key)
                operation_sequences[event.payload.operation_id] = (event.event_type,)
                operation_payloads[event.payload.operation_id] = event.payload
                last_session_ordinal = event.payload.session_ordinal
            if event.event_type == "lifecycle_rolled_back":
                policy_version = event.policy_version or ""
                policy_hash = event.payload.policy_hash or GENESIS_HASH
        else:
            if event.payload.operation_id not in operations or event.payload.idempotency_key not in idempotency:
                raise ContractInvariantError("policy event has no authorizing operation")
            if event.payload.transition_event_hash != previous_hash:
                raise ContractInvariantError("policy event is not bound to preceding transition")
            transition = history.events[index - 1].payload if index else None
            if not isinstance(transition, OperationPayload) or (event.payload.operation_id, event.payload.idempotency_key, event.payload.policy_hash) != (transition.operation_id, transition.idempotency_key, transition.policy_hash):
                raise ContractInvariantError("policy event authorization payload mismatch")
            sequence = operation_sequences[event.payload.operation_id]
            if sequence[-1] == "policy_emitted":
                raise ContractInvariantError("duplicate policy event for lifecycle operation")
            operation_sequences[event.payload.operation_id] = (*sequence, "policy_emitted")
            if event.policy_version is None or event.policy_version in emitted_versions or registry.get(event.policy_version) != event.payload.policy_hash:
                raise ContractInvariantError("emitted policy version reuse is forbidden")
            emitted_versions.add(event.policy_version)
            policy_version = event.policy_version or ""
            policy_hash = event.payload.policy_hash
        previous_hash = event.event_hash
        prior_state = event.lifecycle_state_after
    if history.current_state is not prior_state or history.head_event_hash != previous_hash or history.next_event_index != len(history.events):
        raise ContractInvariantError("lifecycle history head projection mismatch")
    if (history.current_policy_version, history.current_policy_hash) != (policy_version, policy_hash):
        raise ContractInvariantError("lifecycle history policy projection mismatch")
    for operation_id, sequence in operation_sequences.items():
        validate_operation_sequence(operation_payloads[operation_id], sequence)


def validate_operation_sequence(payload: OperationPayload, sequence: tuple[str, ...]) -> None:
    match payload.operation_type:  # noqa: MATCH_OK - all operation type literals are handled
        case "promotion":
            expected = (("lifecycle_created", "limited_promotion_approved", "policy_emitted"), ("limited_promotion_approved", "policy_emitted")) if payload.result_code == "PROMOTION_APPROVED_LIMITED" else (("lifecycle_created", "lifecycle_rejected"),)
        case "incident":
            expected = (("renewal_review_started", "policy_emitted"),) if payload.result_code == "RENEWAL_REVIEW_OPENED" else (("incident_recorded",),)
        case "expiry": expected = (("renewal_review_started", "policy_emitted"),)
        case "renewal": expected = (("limited_renewal_approved", "policy_emitted"),)
        case "rollback": expected = (("lifecycle_rolled_back",),)
        case "retirement_assessment": expected = (("retirement_required",),)
        case "retirement": expected = (("lifecycle_retired", "policy_emitted"),)
        case "reopen": expected = (("lifecycle_reopened",),)
    if sequence not in expected:
        raise ContractInvariantError("lifecycle operation event sequence mismatch")


def validate_event_semantics(event: LifecycleEvent) -> None:
    exact = {
        "lifecycle_created": (None, LifecycleState.PAPER_READY),
        "limited_promotion_approved": (LifecycleState.PAPER_READY, LifecycleState.LIMITED_PRODUCTION),
        "lifecycle_rejected": (LifecycleState.PAPER_READY, LifecycleState.REJECTED),
        "renewal_review_started": (LifecycleState.LIMITED_PRODUCTION, LifecycleState.RENEWAL_REVIEW),
        "limited_renewal_approved": (LifecycleState.RENEWAL_REVIEW, LifecycleState.LIMITED_PRODUCTION),
        "lifecycle_reopened": (LifecycleState.ROLLED_BACK, LifecycleState.PAPER_READY),
    }
    if event.event_type in exact and (event.lifecycle_state_before, event.lifecycle_state_after) != exact[event.event_type]:
        raise ContractInvariantError("lifecycle event state transition mismatch")
    if event.event_type == "incident_recorded" and (event.lifecycle_state_before not in (LifecycleState.LIMITED_PRODUCTION, LifecycleState.RENEWAL_REVIEW) or event.lifecycle_state_after is not event.lifecycle_state_before):
        raise ContractInvariantError("incident event state mismatch")
    if event.event_type == "lifecycle_rolled_back" and (event.lifecycle_state_before not in (LifecycleState.LIMITED_PRODUCTION, LifecycleState.RENEWAL_REVIEW) or event.lifecycle_state_after is not LifecycleState.ROLLED_BACK):
        raise ContractInvariantError("rollback event state mismatch")
    if event.event_type == "retirement_required" and (event.lifecycle_state_before, event.lifecycle_state_after) != (LifecycleState.ROLLED_BACK, LifecycleState.ROLLED_BACK):
        raise ContractInvariantError("retirement assessment state mismatch")
    if event.event_type == "lifecycle_retired" and event.lifecycle_state_after is not LifecycleState.RETIRED:
        raise ContractInvariantError("retirement event state mismatch")
    if event.event_type == "policy_emitted" and event.lifecycle_state_before is not event.lifecycle_state_after:
        raise ContractInvariantError("policy event must preserve transition state")
    match event.payload:  # noqa: MATCH_OK - LifecyclePayload is a closed discriminated union
        case OperationPayload(operation_type=operation_type):
            allowed = {
                "promotion": ("lifecycle_created", "limited_promotion_approved", "lifecycle_rejected"),
                "incident": ("incident_recorded", "renewal_review_started"), "expiry": ("renewal_review_started",),
                "renewal": ("limited_renewal_approved",), "rollback": ("lifecycle_rolled_back",),
                "retirement_assessment": ("retirement_required",), "retirement": ("lifecycle_retired",),
                "reopen": ("lifecycle_reopened",),
            }
            if event.event_type not in allowed[operation_type]:
                raise ContractInvariantError("event type and operation payload mismatch")
            results = {
                "limited_promotion_approved": ("PROMOTION_APPROVED_LIMITED",), "lifecycle_rejected": ("PROMOTION_REJECTED_GATE",),
                "incident_recorded": ("ROLLBACK_REQUIRED", "INCIDENT_NO_ACTION"), "renewal_review_started": ("RENEWAL_REVIEW_OPENED",),
                "limited_renewal_approved": ("RENEWAL_APPROVED_LIMITED",), "lifecycle_rolled_back": ("ROLLBACK_COMPLETED",),
                "retirement_required": ("RETIREMENT_REQUIRED",), "lifecycle_retired": ("RETIREMENT_COMPLETED",),
                "lifecycle_reopened": ("REOPENED_PAPER_READY",),
            }
            if event.event_type != "lifecycle_created" and event.payload.result_code not in results[event.event_type]:
                raise ContractInvariantError("event result code and operation semantics mismatch")
            policy_required = event.event_type in ("limited_promotion_approved", "renewal_review_started", "limited_renewal_approved", "lifecycle_rolled_back", "lifecycle_retired")
            if event.event_type != "lifecycle_created" and (event.payload.policy_hash is not None) != policy_required:
                raise ContractInvariantError("event policy emission semantics mismatch")
            source_paper_required = event.event_type == "lifecycle_rolled_back"
            if (event.payload.source_paper_artifact_hash is not None) != source_paper_required:
                raise ContractInvariantError("rollback source paper semantics mismatch")
        case PolicyEmittedPayload():
            if event.event_type != "policy_emitted":
                raise ContractInvariantError("policy payload requires policy_emitted event")


def rollback_ordinals(history: LifecycleHistory) -> tuple[int, ...]:
    return tuple(event.payload.session_ordinal for event in history.events if event.event_type == "lifecycle_rolled_back" and isinstance(event.payload, OperationPayload))
