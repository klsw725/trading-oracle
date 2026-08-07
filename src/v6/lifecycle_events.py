from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from datetime import datetime

from src.v4.models import JsonValue, canonical_hash

from .lifecycle_evidence import hash_body
from .lifecycle_models import LifecycleState
from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, HypothesisId
from .offline_models import ContentHash


GENESIS_HASH = f"sha256:{'0' * 64}"
EventType = Literal["lifecycle_created", "limited_promotion_approved", "lifecycle_rejected", "incident_recorded", "renewal_review_started", "limited_renewal_approved", "lifecycle_rolled_back", "retirement_required", "lifecycle_retired", "lifecycle_reopened", "policy_emitted"]


class OperationPayload(BoundaryModel):
    kind: Literal["operation"]
    operation_type: Literal["promotion", "incident", "expiry", "renewal", "rollback", "retirement_assessment", "retirement", "reopen"]
    operation_id: str
    idempotency_key: str
    result_code: str
    evidence_hash: ContentHash
    approval_hash: ContentHash | None
    policy_hash: ContentHash | None
    source_paper_artifact_hash: ContentHash | None
    session_ordinal: Annotated[int, Field(strict=True, ge=1)]


class PolicyEmittedPayload(BoundaryModel):
    kind: Literal["policy_emitted"]
    operation_id: str
    idempotency_key: str
    transition_event_hash: ContentHash
    policy_hash: ContentHash


type LifecyclePayload = OperationPayload | PolicyEmittedPayload


class LifecycleEventBody(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.event.3"]
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    policy_version: str | None
    event_index: Annotated[int, Field(strict=True, ge=0)]
    event_type: EventType
    lifecycle_state_before: LifecycleState | None
    lifecycle_state_after: LifecycleState
    occurred_at: str
    prev_event_hash: ContentHash
    payload_hash: ContentHash
    payload: LifecyclePayload = Field(discriminator="kind")

    @field_validator("occurred_at")
    @classmethod
    def valid_time(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ContractInvariantError("lifecycle event timestamp requires timezone")
        return value


class LifecycleEvent(LifecycleEventBody):
    event_id: str
    event_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = LifecycleEventBody.model_validate(self.model_dump(mode="json", exclude={"event_id", "event_hash"}))
        if self.payload_hash != hash_body(self.payload) or self.event_hash != canonical_hash(event_hash_json(body)) or self.event_id != f"lifecycle_v6_{self.event_index:04d}":
            raise ContractInvariantError("lifecycle event integrity mismatch")
        return self


def event_hash_json(value: LifecycleEventBody) -> JsonValue:
    return {"schema_version": value.schema_version, "candidate_id": value.candidate_id, "candidate_version": value.candidate_version, "hypothesis_id": value.hypothesis_id, "policy_version": value.policy_version, "event_index": value.event_index, "event_type": value.event_type, "lifecycle_state_before": value.lifecycle_state_before.value if value.lifecycle_state_before else None, "lifecycle_state_after": value.lifecycle_state_after.value, "prev_event_hash": value.prev_event_hash, "payload_hash": value.payload_hash}
