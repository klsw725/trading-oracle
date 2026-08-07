from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .lifecycle_evidence import PromotionErrorWindow, hash_body
from .lifecycle_incidents import CapIncident, DeliberationIncident, DirtyPolicyIncident, ErrorRateIncident, MonitoringIncident
from .lifecycle_history import LifecycleHistory
from .lifecycle_models import LifecycleDecision, LifecycleInput, LifecycleResultCode, OperatorApproval
from .lifecycle_policy import ConsensusPolicyArtifact, CurrentConsensusPolicy
from .models import BoundaryModel, ContractInvariantError
from .offline_models import ContentHash
from .paper_artifact import PaperCohortArtifact
from .lifecycle_retirement import HypothesisFalsified, OwnerRequest, RetirementRequired, SourceUnavailable, SupersededVersion


type IncidentReport = Annotated[ErrorRateIncident | MonitoringIncident | DeliberationIncident | CapIncident | DirtyPolicyIncident, Field(discriminator="incident_type")]


class PromotionOperation(BoundaryModel):
    operation_type: Literal["promotion"]
    lifecycle_input: LifecycleInput
    paper_artifact: PaperCohortArtifact
    current_policy: CurrentConsensusPolicy | ConsensusPolicyArtifact
    approval: OperatorApproval
    error_window: PromotionErrorWindow
    prior_history: LifecycleHistory | None = None
    expected_prior_history_hash: ContentHash | None = None


class IncidentOperation(BoundaryModel):
    operation_type: Literal["incident"]
    lifecycle_input: LifecycleInput
    current_policy: ConsensusPolicyArtifact
    prior_history: LifecycleHistory
    expected_prior_history_hash: ContentHash
    output_policy_version: str
    source_paper_artifact: PaperCohortArtifact
    report: IncidentReport


class ExpiryOperation(BoundaryModel):
    operation_type: Literal["expiry"]
    lifecycle_input: LifecycleInput
    current_policy: ConsensusPolicyArtifact
    prior_history: LifecycleHistory
    expected_prior_history_hash: ContentHash
    output_policy_version: str


class RenewalOperation(BoundaryModel):
    operation_type: Literal["renewal"]
    lifecycle_input: LifecycleInput
    current_policy: ConsensusPolicyArtifact
    prior_history: LifecycleHistory
    expected_prior_history_hash: ContentHash
    approval: OperatorApproval


class IncidentAssessmentBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-incident-assessment.1"]
    candidate_id: str
    candidate_version: str
    policy_version: str
    source_policy_hash: ContentHash
    incident_evidence_hash: ContentHash
    decision: LifecycleDecision

    @model_validator(mode="after")
    def rollback_required(self) -> Self:
        if self.decision.result_code is not LifecycleResultCode.ROLLBACK_REQUIRED:
            raise ContractInvariantError("rollback assessment must require rollback")
        return self


class IncidentAssessment(IncidentAssessmentBody):
    assessment_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = IncidentAssessmentBody.model_validate(self.model_dump(mode="json", exclude={"assessment_hash"}))
        if self.assessment_hash != hash_body(body):
            raise ContractInvariantError("incident assessment hash mismatch")
        return self


class RollbackOperation(BoundaryModel):
    operation_type: Literal["rollback"]
    lifecycle_input: LifecycleInput
    current_policy: ConsensusPolicyArtifact
    prior_history: LifecycleHistory
    expected_prior_history_hash: ContentHash
    rollback_policy: CurrentConsensusPolicy
    approval: OperatorApproval
    assessment: IncidentAssessment


class RetirementAssessmentOperation(BoundaryModel):
    operation_type: Literal["retirement_assessment"]
    lifecycle_input: LifecycleInput
    current_policy: CurrentConsensusPolicy
    prior_history: LifecycleHistory
    expected_prior_history_hash: ContentHash


type RetirementTrigger = Annotated[OwnerRequest | SupersededVersion | SourceUnavailable | HypothesisFalsified | RetirementRequired, Field(discriminator="trigger_type")]


class RetirementOperation(BoundaryModel):
    operation_type: Literal["retirement"]
    lifecycle_input: LifecycleInput
    current_policy: CurrentConsensusPolicy | ConsensusPolicyArtifact
    prior_history: LifecycleHistory
    expected_prior_history_hash: ContentHash
    approval: OperatorApproval
    trigger: RetirementTrigger
    source_paper_artifact: PaperCohortArtifact


class ReopenAuthorizationBody(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.reopen-authorization.1"]
    candidate_id: str
    candidate_version: str
    prior_history_hash: ContentHash
    rollback_event_hash: ContentHash
    prior_source_paper_artifact_hash: ContentHash
    paper_artifact_hash: ContentHash


class ReopenAuthorization(ReopenAuthorizationBody):
    authorization_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = ReopenAuthorizationBody.model_validate(self.model_dump(mode="json", exclude={"authorization_hash"}))
        if self.authorization_hash != hash_body(body):
            raise ContractInvariantError("reopen authorization hash mismatch")
        return self


class ReopenOperation(BoundaryModel):
    operation_type: Literal["reopen"]
    lifecycle_input: LifecycleInput
    current_policy: CurrentConsensusPolicy
    prior_history: LifecycleHistory
    expected_prior_history_hash: ContentHash
    paper_artifact: PaperCohortArtifact
    authorization: ReopenAuthorization


type LifecycleOperation = Annotated[PromotionOperation | IncidentOperation | ExpiryOperation | RenewalOperation | RollbackOperation | RetirementAssessmentOperation | RetirementOperation | ReopenOperation, Field(discriminator="operation_type")]
