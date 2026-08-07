from .candidate_fixture_models import CandidateFixture
from .candidate_validation import evaluate_candidate
from .models import (
    CandidateDecision,
    CandidateProposal,
    ExistingPerspective,
    ForbiddenFamily,
    OverlapReviewStatus,
)


def _duplicate_candidate(
    candidate: CandidateProposal,
    perspective: ExistingPerspective,
    family: ForbiddenFamily,
) -> CandidateProposal:
    rows = tuple(
        row.model_copy(
            update={
                "manual_review": row.manual_review.model_copy(
                    update={
                        "status": OverlapReviewStatus.DUPLICATE,
                        "forbidden_families": (family,),
                    }
                )
            }
        )
        if row.compared_to is perspective
        else row
        for row in candidate.overlap_matrix
    )
    return candidate.model_copy(update={"overlap_matrix": rows})


def observed_decisions(fixture: CandidateFixture) -> dict[str, CandidateDecision]:
    base = fixture.base_candidate
    output = fixture.valid_output
    na_output = fixture.valid_na_output
    vectors = fixture.adversarial
    malformed_probability = output.model_copy(
        update={"confidence": vectors.malformed_confidence}
    )
    malformed_budget = base.model_copy(
        update={
            "budget": base.budget.model_copy(
                update={"max_wall_ms_per_ticker": vectors.malformed_wall_ms}
            )
        }
    )
    malformed_na = na_output.model_copy(
        update={"confidence": vectors.malformed_na_confidence}
    )
    dirty_duplicate = _duplicate_candidate(
        base.model_copy(
            update={
                "independent_hypothesis": base.independent_hypothesis.model_copy(
                    update={
                        "primary_observations": vectors.dirty_duplicate_observations
                    }
                )
            }
        ),
        ExistingPerspective.QUANT,
        vectors.quant_clone_family,
    )
    misleading = base.model_copy(
        update={
            "input_contract": base.input_contract.model_copy(
                update={
                    "uses_perspective_input_fields": vectors.misleading_input_fields
                }
            )
        }
    )
    direct_adoption = base.model_copy(
        update={"requested_stage": vectors.direct_adoption_stage}
    )
    malformed_verdict = output.model_copy(
        update={"verdict": vectors.malformed_verdict}
    )
    untyped_output = base.model_copy(
        update={
            "output_contract": base.output_contract.model_copy(
                update={"confidence_range": vectors.untyped_confidence_range}
            )
        }
    )
    missing_owner = base.model_copy(
        update={
            "candidate_identity": base.candidate_identity.model_copy(
                update={"owner": vectors.missing_owner}
            )
        }
    )
    malformed_rows = tuple(
        row.model_copy(update={"overlap_score": vectors.malformed_overlap_metric})
        if row.compared_to is ExistingPerspective.QUANT
        else row
        for row in base.overlap_matrix
    )
    candidate_id_mismatch = base.model_copy(
        update={
            "candidate_identity": base.candidate_identity.model_copy(
                update={"candidate_id": vectors.mismatched_candidate_id}
            )
        }
    )
    candidate_version_mismatch = base.model_copy(
        update={
            "candidate_identity": base.candidate_identity.model_copy(
                update={"candidate_version": vectors.mismatched_candidate_version}
            )
        }
    )
    hypothesis_id_mismatch = base.model_copy(
        update={
            "independent_hypothesis": base.independent_hypothesis.model_copy(
                update={"hypothesis_id": vectors.mismatched_hypothesis_id}
            )
        }
    )
    unknown_input = base.model_copy(
        update={
            "input_contract": base.input_contract.model_copy(
                update={
                    "uses_perspective_input_fields": (
                        *base.input_contract.uses_perspective_input_fields,
                        vectors.unknown_input_field,
                    )
                }
            )
        }
    )
    output_perspective = output.model_copy(
        update={"perspective": vectors.mismatched_output_perspective}
    )
    verdict_action = output.model_copy(
        update={
            "action": output.action.model_copy(
                update={"type": vectors.mismatched_action}
            )
        }
    )
    blank_na = na_output.model_copy(
        update={
            "extra": na_output.extra.model_copy(
                update={"not_applicable_reason": vectors.blank_na_reason}
            )
        }
    )
    blank_hypothesis = base.model_copy(
        update={
            "independent_hypothesis": base.independent_hypothesis.model_copy(
                update={"error_mode_explained": vectors.blank_hypothesis_metadata}
            )
        }
    )
    low_overlap_value_clone = base.model_copy(
        update={
            "independent_hypothesis": base.independent_hypothesis.model_copy(
                update={
                    "primary_observations": vectors.low_overlap_value_clone_observations
                }
            )
        }
    )
    missing_behavior_buy = base.model_copy(
        update={
            "input_contract": base.input_contract.model_copy(
                update={"missing_behavior": vectors.invalid_top_level_missing_behavior}
            )
        }
    )
    documented_watch = output.model_copy(
        update={
            "action": output.action.model_copy(
                update={"watch": vectors.documented_action_watch}
            )
        }
    )
    return {
        "happy_independent_candidate": evaluate_candidate(base, output),
        "valid_na_output": evaluate_candidate(base, na_output),
        "rejected_quant_clone_candidate": evaluate_candidate(fixture.quant_clone_candidate),
        "malformed_probability": evaluate_candidate(base, malformed_probability),
        "malformed_budget": evaluate_candidate(malformed_budget),
        "malformed_na": evaluate_candidate(base, malformed_na),
        "dirty_duplicate": evaluate_candidate(dirty_duplicate),
        "misleading_purpose": evaluate_candidate(misleading),
        "direct_adoption": evaluate_candidate(direct_adoption),
        "malformed_verdict": evaluate_candidate(base, malformed_verdict),
        "untyped_input_or_output": evaluate_candidate(untyped_output),
        "missing_owner_or_version": evaluate_candidate(missing_owner),
        "incomplete_overlap_rows": evaluate_candidate(
            base.model_copy(update={"overlap_matrix": base.overlap_matrix[:-1]})
        ),
        "duplicate_overlap_rows": evaluate_candidate(
            base.model_copy(
                update={"overlap_matrix": (*base.overlap_matrix[:-1], base.overlap_matrix[0])}
            )
        ),
        "malformed_overlap_metric": evaluate_candidate(
            base.model_copy(update={"overlap_matrix": malformed_rows})
        ),
        "kwangsoo_clone": evaluate_candidate(
            _duplicate_candidate(base, ExistingPerspective.KWANGSOO, vectors.kwangsoo_clone_family)
        ),
        "ouroboros_clone": evaluate_candidate(
            _duplicate_candidate(base, ExistingPerspective.OUROBOROS, vectors.ouroboros_clone_family)
        ),
        "macro_clone": evaluate_candidate(
            _duplicate_candidate(base, ExistingPerspective.MACRO, vectors.macro_clone_family)
        ),
        "value_clone": evaluate_candidate(
            _duplicate_candidate(base, ExistingPerspective.VALUE, vectors.value_clone_family)
        ),
        "candidate_id_name_mismatch": evaluate_candidate(candidate_id_mismatch),
        "candidate_version_name_mismatch": evaluate_candidate(candidate_version_mismatch),
        "hypothesis_id_name_mismatch": evaluate_candidate(hypothesis_id_mismatch),
        "unknown_perspective_input_field": evaluate_candidate(unknown_input),
        "output_perspective_mismatch": evaluate_candidate(base, output_perspective),
        "verdict_action_mismatch": evaluate_candidate(base, verdict_action),
        "blank_na_reason": evaluate_candidate(base, blank_na),
        "malformed_precedes_direct_adoption": evaluate_candidate(
            direct_adoption, malformed_probability
        ),
        "blank_hypothesis_metadata": evaluate_candidate(blank_hypothesis),
        "low_overlap_value_core_clone": evaluate_candidate(low_overlap_value_clone),
        "top_level_missing_behavior_buy": evaluate_candidate(missing_behavior_buy),
        "documented_action_watch_output": evaluate_candidate(base, documented_watch),
    }
