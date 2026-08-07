from dataclasses import dataclass
from typing import override

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash

from .candidate_artifact import (
    CandidateArtifact,
    CandidateArtifactBody,
    artifact_body_json,
)
from .candidate_validation import evaluate_candidate as evaluate_candidate
from .models import (
    ARTIFACT_SCHEMA_VERSION,
    CANDIDATE_ADAPTER,
    JsonBoundary,
    CandidateProposal,
    RejectionCode,
)


@dataclass(frozen=True, slots=True)
class CandidateContractError(Exception):
    code: RejectionCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


def parse_candidate(value: JsonValue) -> CandidateProposal:
    try:
        return CANDIDATE_ADAPTER.validate_python(value)
    except ValidationError as error:
        detail = str(error)
        identity_markers = (
            "candidate_identity",
            "candidate identity",
            "candidate_version",
            "hypothesis identity",
        )
        code = (
            RejectionCode.IDENTITY
            if any(marker in detail for marker in identity_markers)
            else RejectionCode.UNTYPED
        )
        raise CandidateContractError(code, detail) from error


def candidate_json(candidate: CandidateProposal) -> JsonValue:
    return JsonBoundary.model_validate(candidate.model_dump(mode="json")).root


def artifact_json(artifact: CandidateArtifact) -> JsonValue:
    return JsonBoundary.model_validate(artifact.model_dump(mode="json")).root


def build_candidate_artifact(candidate: CandidateProposal) -> CandidateArtifact:
    proposal = candidate_json(candidate)
    identity = candidate.candidate_identity
    hypothesis = candidate.independent_hypothesis
    body = CandidateArtifactBody(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        generated_at=identity.created_at.isoformat(),
        candidate_id=identity.candidate_id,
        candidate_version=identity.candidate_version,
        hypothesis_id=hypothesis.hypothesis_id,
        candidate_proposal_hash=canonical_hash(proposal),
        candidate_proposal=candidate,
        decision=evaluate_candidate(candidate),
        production_isolation="offline_only_no_production_imports",
    )
    return CandidateArtifact.model_validate(
        {**body.model_dump(mode="json"), "artifact_hash": canonical_hash(artifact_body_json(body))}
    )
