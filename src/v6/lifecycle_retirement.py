from typing import Literal, Self

from pydantic import Field, model_validator

from .lifecycle_evidence import hash_body
from .models import BoundaryModel, CandidateId, CandidateVersion, HypothesisId, ContractInvariantError
from .offline_models import ContentHash
from .candidate_artifact import CandidateArtifact
from .lifecycle_models import ApprovalAction, OperatorApproval
from .lifecycle_policy import ConsensusPolicyArtifact


class AvailabilityObservationBody(BoundaryModel):
    schema_version: Literal["v6.source-availability-observation.1"]
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    source_id: str
    source_contract: str
    observed_session_ordinal: int
    last_available_session_ordinal: int
    available: Literal[False]


class AvailabilityObservation(AvailabilityObservationBody):
    observation_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = AvailabilityObservationBody.model_validate(self.model_dump(mode="json", exclude={"observation_hash"}))
        if self.observed_session_ordinal <= self.last_available_session_ordinal or self.observation_hash != hash_body(body): raise ContractInvariantError("availability observation mismatch")
        return self


class SourceAvailabilityArtifactBody(BoundaryModel):
    schema_version: Literal["v6.source-availability-artifact.1"]
    candidate_artifact: CandidateArtifact
    observation: AvailabilityObservation


class SourceAvailabilityArtifact(SourceAvailabilityArtifactBody):
    artifact_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = SourceAvailabilityArtifactBody.model_validate(self.model_dump(mode="json", exclude={"artifact_hash"}))
        candidate = self.candidate_artifact
        observation = self.observation
        declared = tuple((item.name, item.source_contract or item.name) for item in candidate.candidate_proposal.input_contract.required_extra_inputs)
        identity = (candidate.candidate_id, candidate.candidate_version, candidate.hypothesis_id)
        if (observation.candidate_id, observation.candidate_version, observation.hypothesis_id) != identity or (observation.source_id, observation.source_contract) not in declared or self.artifact_hash != hash_body(body): raise ContractInvariantError("source availability artifact mismatch")
        return self


class FalsificationObservationBody(BoundaryModel):
    schema_version: Literal["v6.hypothesis-falsification-observation.1"]
    observation_id: str
    source_artifact_hash: ContentHash
    supports_hypothesis: Literal[False]


class FalsificationObservation(FalsificationObservationBody):
    observation_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = FalsificationObservationBody.model_validate(self.model_dump(mode="json", exclude={"observation_hash"}))
        if self.observation_hash != hash_body(body): raise ContractInvariantError("falsification observation hash mismatch")
        return self


class HypothesisFalsificationArtifactBody(BoundaryModel):
    schema_version: Literal["v6.hypothesis-falsification-artifact.1"]
    candidate_artifact: CandidateArtifact
    source_paper_artifact_hash: ContentHash
    observations: tuple[FalsificationObservation, ...] = Field(min_length=1)
    result: Literal["falsified"]


class HypothesisFalsificationArtifact(HypothesisFalsificationArtifactBody):
    artifact_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = HypothesisFalsificationArtifactBody.model_validate(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if any(item.source_artifact_hash != self.source_paper_artifact_hash for item in self.observations) or self.artifact_hash != hash_body(body): raise ContractInvariantError("hypothesis falsification artifact mismatch")
        return self


class OwnerRequestBody(BoundaryModel):
    trigger_type: Literal["owner_request"]
    owner_id: str
    candidate_artifact_hash: ContentHash


class OwnerRequest(OwnerRequestBody):
    trigger_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = OwnerRequestBody.model_validate(self.model_dump(mode="json", exclude={"trigger_hash"}))
        if self.trigger_hash != hash_body(body): raise ContractInvariantError("owner retirement trigger hash mismatch")
        return self


class SupersededVersionBody(BoundaryModel):
    trigger_type: Literal["superseded_version"]
    candidate_id: CandidateId
    retired_version: CandidateVersion
    newer_version: CandidateVersion
    newer_approval: OperatorApproval
    newer_policy: ConsensusPolicyArtifact


class SupersededVersion(SupersededVersionBody):
    trigger_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = SupersededVersionBody.model_validate(self.model_dump(mode="json", exclude={"trigger_hash"}))
        candidate = next((item for item in self.newer_policy.active_candidates if (item.candidate_id, item.candidate_version) == (self.candidate_id, self.newer_version)), None)
        if semantic_version(self.newer_version) <= semantic_version(self.retired_version) or self.newer_approval.action is not ApprovalAction.PROMOTE or (self.newer_approval.candidate_id, self.newer_approval.candidate_version, self.newer_approval.policy_version) != (self.candidate_id, self.newer_version, self.newer_policy.policy_version) or candidate is None or candidate.operator_approval_hash != self.newer_approval.approval_hash or self.trigger_hash != hash_body(body): raise ContractInvariantError("superseded retirement trigger mismatch")
        return self


def semantic_version(version: CandidateVersion) -> tuple[str, int, int]:
    name, major, minor = str(version).rsplit(".", 2)
    return name, int(major), int(minor)


class SourceUnavailableBody(BoundaryModel):
    trigger_type: Literal["source_unavailable_beyond_ttl"]
    evidence: SourceAvailabilityArtifact


class SourceUnavailable(SourceUnavailableBody):
    trigger_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = SourceUnavailableBody.model_validate(self.model_dump(mode="json", exclude={"trigger_hash"}))
        if self.trigger_hash != hash_body(body): raise ContractInvariantError("source retirement trigger mismatch")
        return self


class HypothesisFalsifiedBody(BoundaryModel):
    trigger_type: Literal["hypothesis_falsified"]
    evidence: HypothesisFalsificationArtifact


class HypothesisFalsified(HypothesisFalsifiedBody):
    trigger_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = HypothesisFalsifiedBody.model_validate(self.model_dump(mode="json", exclude={"trigger_hash"}))
        if self.trigger_hash != hash_body(body): raise ContractInvariantError("hypothesis retirement trigger mismatch")
        return self


class RetirementRequiredBody(BoundaryModel):
    trigger_type: Literal["retirement_required"]
    assessment_event_hash: ContentHash
    history_hash: ContentHash


class RetirementRequired(RetirementRequiredBody):
    trigger_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = RetirementRequiredBody.model_validate(self.model_dump(mode="json", exclude={"trigger_hash"}))
        if self.trigger_hash != hash_body(body): raise ContractInvariantError("assessment retirement trigger hash mismatch")
        return self
