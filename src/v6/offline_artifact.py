from typing import Literal, Self

from pydantic import Field, model_validator

from src.v4.models import JsonValue, canonical_hash

from .candidate_artifact import CandidateArtifact
from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, HypothesisId, JsonBoundary
from .offline_evaluator import evaluate_evidence
from .offline_evidence import FrozenEvaluationInput
from .offline_metrics import HandMetrics, derive_hand_metrics
from .offline_models import ContentHash, OfflineCode, OfflineSummary
from .offline_validation import evidence_failures


class OfflineArtifactBody(BoundaryModel):
    schema_version: Literal["v6.offline-evaluation-artifact.2"]
    generated_at: str
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    candidate_artifact_hash: ContentHash
    candidate_artifact: CandidateArtifact
    hand_input_hash: ContentHash
    hand_input: FrozenEvaluationInput
    evaluation_input_hash: ContentHash
    evaluation_input: FrozenEvaluationInput
    summary: OfflineSummary | None
    hand_metrics: HandMetrics
    terminal_code: OfflineCode
    reasons: tuple[str, ...]
    production_isolation: Literal["offline_read_only_no_production_mutation"]


def offline_body_json(body: OfflineArtifactBody) -> JsonValue:
    return JsonBoundary.model_validate(body.model_dump(mode="json")).root


class OfflineEvaluationArtifact(OfflineArtifactBody):
    artifact_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verified_integrity(self) -> Self:
        candidate = CandidateArtifact.model_validate(self.candidate_artifact.model_dump(mode="json"))
        identity = (candidate.candidate_id, candidate.candidate_version, candidate.hypothesis_id)
        if (self.candidate_id, self.candidate_version, self.hypothesis_id) != identity:
            raise ContractInvariantError("offline artifact lineage mismatch")
        if candidate.decision.accepted_for_evaluation is not True or self.candidate_artifact_hash != candidate.artifact_hash:
            raise ContractInvariantError("candidate artifact is not accepted or hash-bound")
        if self.hand_input_hash != self.hand_input.input_hash or self.evaluation_input_hash != self.evaluation_input.input_hash:
            raise ContractInvariantError("offline input hash pointer mismatch")
        if evidence_failures(self.hand_input, candidate, 0):
            raise ContractInvariantError("hand evidence integrity failed")
        expected_hand = derive_hand_metrics(self.hand_input)
        result = evaluate_evidence(candidate, self.evaluation_input)
        if self.hand_metrics != expected_hand or self.summary != result.summary or (self.terminal_code, self.reasons) != (result.decision.code, result.decision.reasons):
            raise ContractInvariantError("offline derived result mismatch")
        body = OfflineArtifactBody.model_validate(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != canonical_hash(offline_body_json(body)):
            raise ContractInvariantError("offline artifact hash mismatch")
        return self


def build_offline_artifact(candidate: CandidateArtifact, evaluation_input: FrozenEvaluationInput, hand_input: FrozenEvaluationInput) -> OfflineEvaluationArtifact:
    hand_failures = evidence_failures(hand_input, candidate, 0)
    if hand_failures:
        raise ContractInvariantError(f"hand evidence failed: {','.join(hand_failures)}")
    metrics = derive_hand_metrics(hand_input)
    result = evaluate_evidence(candidate, evaluation_input)
    body = OfflineArtifactBody(schema_version="v6.offline-evaluation-artifact.2", generated_at=candidate.generated_at, candidate_id=candidate.candidate_id, candidate_version=candidate.candidate_version, hypothesis_id=candidate.hypothesis_id, candidate_artifact_hash=candidate.artifact_hash, candidate_artifact=candidate, hand_input_hash=hand_input.input_hash, hand_input=hand_input, evaluation_input_hash=evaluation_input.input_hash, evaluation_input=evaluation_input, summary=result.summary, hand_metrics=metrics, terminal_code=result.decision.code, reasons=result.decision.reasons, production_isolation="offline_read_only_no_production_mutation")
    return OfflineEvaluationArtifact.model_validate({**body.model_dump(mode="json"), "artifact_hash": canonical_hash(offline_body_json(body))})


def offline_artifact_json(artifact: OfflineEvaluationArtifact) -> JsonValue:
    return JsonBoundary.model_validate(artifact.model_dump(mode="json")).root
