from typing import Annotated, Literal

from pydantic import Field

from src.v4.models import canonical_hash
from src.v6.models import BoundaryModel
from src.v6.models import JsonBoundary

from .models import HashText
from .source_models import IncidentCode, LifecycleState, OwnerApproval, PromotionObservation, RetirementReason


class PromotionOperation(BoundaryModel):
    kind: Literal["promotion"]
    operation_id: Annotated[str, Field(min_length=1)]
    idempotency_key: Annotated[str, Field(min_length=1)]
    expected_prior_policy_hash: HashText
    expected_registry_hash: HashText
    expected_source_bundle_hash: HashText
    expected_contract_hash: HashText
    to_state: LifecycleState
    traffic_share: str
    owner_approval: OwnerApproval | None
    observation: PromotionObservation
    interrupted: bool = False


class IncidentOperation(BoundaryModel):
    kind: Literal["incident"]
    operation_id: Annotated[str, Field(min_length=1)]
    idempotency_key: Annotated[str, Field(min_length=1)]
    expected_prior_policy_hash: HashText
    expected_registry_hash: HashText
    incident_code: IncidentCode
    evidence_hash: HashText
    traffic_share: str
    interrupted: bool = False


class RetirementOperation(BoundaryModel):
    kind: Literal["retirement"]
    operation_id: Annotated[str, Field(min_length=1)]
    idempotency_key: Annotated[str, Field(min_length=1)]
    expected_prior_policy_hash: HashText
    expected_registry_hash: HashText
    reason: RetirementReason
    delete_retained_history: bool = False
    interrupted: bool = False


type SourceOperation = Annotated[PromotionOperation | IncidentOperation | RetirementOperation, Field(discriminator="kind")]


def operation_hash(operation: SourceOperation) -> str:
    value = JsonBoundary.model_validate(operation.model_dump(mode="json")).root
    return str(canonical_hash(value))
