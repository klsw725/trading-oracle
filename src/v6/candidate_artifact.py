from typing import Literal, Self

from pydantic import Field, model_validator

from src.v4.models import JsonValue, canonical_hash

from .candidate_validation import evaluate_candidate
from .models import (
    BoundaryModel,
    CandidateDecision,
    CandidateId,
    CandidateProposal,
    CandidateVersion,
    ContractInvariantError,
    HypothesisId,
    JsonBoundary,
)


class CandidateArtifactBody(BoundaryModel):
    schema_version: Literal["perspective-candidate-contract-artifact.1"]
    generated_at: str
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    candidate_proposal_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_proposal: CandidateProposal
    decision: CandidateDecision
    production_isolation: Literal["offline_only_no_production_imports"]


def artifact_body_json(artifact: CandidateArtifactBody) -> JsonValue:
    return JsonBoundary.model_validate(artifact.model_dump(mode="json")).root


class CandidateArtifact(CandidateArtifactBody):
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verified_integrity(self) -> Self:
        proposal = self.candidate_proposal
        identity = proposal.candidate_identity
        hypothesis = proposal.independent_hypothesis
        proposal_json = JsonBoundary.model_validate(
            proposal.model_dump(mode="json")
        ).root
        if self.candidate_proposal_hash != canonical_hash(proposal_json):
            raise ContractInvariantError("candidate proposal hash mismatch")
        if (
            self.candidate_id != identity.candidate_id
            or self.candidate_version != identity.candidate_version
            or self.hypothesis_id != hypothesis.hypothesis_id
            or self.generated_at != identity.created_at.isoformat()
        ):
            raise ContractInvariantError("artifact identity mismatch")
        body = CandidateArtifactBody.model_validate(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != canonical_hash(artifact_body_json(body)):
            raise ContractInvariantError("artifact hash mismatch")
        if self.decision != evaluate_candidate(proposal):
            raise ContractInvariantError("artifact decision differs from candidate evaluation")
        return self
