from typing import Annotated, Literal

from pydantic import Field

from src.v4.models import canonical_hash
from src.v6.models import BoundaryModel, JsonBoundary

from .models import HashText
from .source_models import LifecycleState


class AuditPayload(BoundaryModel):
    operation_id: Annotated[str, Field(min_length=1)]
    idempotency_key: Annotated[str, Field(min_length=1)]
    operation_hash: HashText
    event_type: Literal["promotion", "disable", "expiry", "retirement"]
    from_state: LifecycleState
    to_state: LifecycleState
    traffic_share: str
    decision_reason: Literal["promotion_gate_passed", "incident", "contract_expired", "voluntary_retirement"]
    previous_policy_hash: HashText
    new_policy_hash: HashText
    source_bundle_hash: HashText
    cache_generation: Annotated[int, Field(strict=True, ge=0)]
    interrupted_transition: bool


class AuditEventBody(BoundaryModel):
    schema_version: Literal["v7.source-policy.audit-event.1"]
    event_index: Annotated[int, Field(strict=True, ge=0)]
    previous_event_hash: HashText
    payload_hash: HashText
    payload: AuditPayload


class AuditEvent(AuditEventBody):
    audit_event_hash: HashText


def event_hash(model: BoundaryModel) -> str:
    value = JsonBoundary.model_validate(model.model_dump(mode="json")).root
    return str(canonical_hash(value))


def build_event(index: int, previous_hash: str, payload: AuditPayload) -> AuditEvent:
    body = AuditEventBody(schema_version="v7.source-policy.audit-event.1", event_index=index, previous_event_hash=previous_hash, payload_hash=event_hash(payload), payload=payload)
    return AuditEvent.model_validate({**body.model_dump(mode="json"), "audit_event_hash": event_hash(body)})
