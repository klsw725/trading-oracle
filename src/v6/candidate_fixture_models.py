from typing import Final

from pydantic import TypeAdapter

from .models import (
    ActionType,
    BoundaryModel,
    CandidateOutput,
    CandidateProposal,
    ForbiddenFamily,
    MetricInput,
    RejectionCode,
    RequestedStage,
)


class AdversarialVectors(BoundaryModel):
    malformed_confidence: MetricInput
    malformed_wall_ms: int
    malformed_na_confidence: MetricInput
    dirty_duplicate_observations: tuple[str, ...]
    misleading_input_fields: tuple[str, ...]
    direct_adoption_stage: RequestedStage
    malformed_verdict: str
    untyped_confidence_range: tuple[MetricInput, MetricInput]
    missing_owner: str
    malformed_overlap_metric: MetricInput
    kwangsoo_clone_family: ForbiddenFamily
    ouroboros_clone_family: ForbiddenFamily
    quant_clone_family: ForbiddenFamily
    macro_clone_family: ForbiddenFamily
    value_clone_family: ForbiddenFamily
    mismatched_candidate_id: str
    mismatched_candidate_version: str
    mismatched_hypothesis_id: str
    unknown_input_field: str
    mismatched_output_perspective: str
    mismatched_action: ActionType
    blank_na_reason: str
    blank_hypothesis_metadata: str
    low_overlap_value_clone_observations: tuple[str, ...]
    invalid_top_level_missing_behavior: str
    documented_action_watch: str


class ExpectedCheck(BoundaryModel):
    check: str
    accepted_for_evaluation: bool
    rejection_code: RejectionCode | None


class CandidateFixture(BoundaryModel):
    schema_version: str
    base_candidate: CandidateProposal
    valid_output: CandidateOutput
    valid_na_output: CandidateOutput
    quant_clone_candidate: CandidateProposal
    adversarial: AdversarialVectors
    expected: tuple[ExpectedCheck, ...]


FIXTURE_ADAPTER: Final = TypeAdapter(CandidateFixture)
