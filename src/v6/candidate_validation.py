from decimal import Decimal
import re
from typing import Final, TypeIs

from .candidate_clone_evidence import duplicates_incumbent
from .models import (
    CONTRACT_VERSION,
    DECIMAL_PATTERN,
    VERSION_PATTERN,
    ActionType,
    CandidateDecision,
    CandidateOutput,
    CandidateProposal,
    ExistingPerspective,
    ForbiddenFamily,
    MetricInput,
    OverlapReviewStatus,
    PerspectiveInputField,
    RejectionCode,
    RequestedStage,
    Verdict,
)


OVERLAP_CEILINGS: Final = {
    ExistingPerspective.KWANGSOO: Decimal("0.400000"),
    ExistingPerspective.OUROBOROS: Decimal("0.400000"),
    ExistingPerspective.QUANT: Decimal("0.250000"),
    ExistingPerspective.MACRO: Decimal("0.400000"),
    ExistingPerspective.VALUE: Decimal("0.350000"),
}
FORBIDDEN_FAMILY: Final = {
    ExistingPerspective.KWANGSOO: ForbiddenFamily.KWANGSOO,
    ExistingPerspective.OUROBOROS: ForbiddenFamily.OUROBOROS,
    ExistingPerspective.QUANT: ForbiddenFamily.QUANT,
    ExistingPerspective.MACRO: ForbiddenFamily.MACRO,
    ExistingPerspective.VALUE: ForbiddenFamily.VALUE,
}
VERDICTS: Final = tuple(item.value for item in Verdict)
ACTION_BY_VERDICT: Final = {
    Verdict.BUY.value: ActionType.BUY,
    Verdict.SELL.value: ActionType.SELL,
    Verdict.HOLD.value: ActionType.HOLD,
    Verdict.NA.value: ActionType.NONE,
}
INPUT_FIELDS: Final = frozenset(item.value for item in PerspectiveInputField)


def _is_metric_text(value: MetricInput) -> TypeIs[str]:
    return isinstance(value, str)


def _metric(value: MetricInput) -> Decimal | None:
    if not _is_metric_text(value) or re.fullmatch(DECIMAL_PATTERN, value) is None:
        return None
    parsed = Decimal(value)
    return parsed if Decimal("0") <= parsed <= Decimal("1") else None


def _reject(code: RejectionCode) -> CandidateDecision:
    return CandidateDecision(accepted_for_evaluation=False, rejection_code=code)


def _is_na_behavior(value: str) -> bool:
    return value == Verdict.NA.value


def _overlap_problem(candidate: CandidateProposal) -> RejectionCode | None:
    rows = candidate.overlap_matrix
    compared = tuple(row.compared_to for row in rows)
    if len(rows) != len(ExistingPerspective) or len(set(compared)) != len(rows):
        return RejectionCode.UNTYPED
    if set(compared) != set(ExistingPerspective):
        return RejectionCode.UNTYPED
    for row in rows:
        input_overlap = _metric(row.input_overlap)
        verdict_overlap = _metric(row.verdict_correlation_proxy)
        overlap = _metric(row.overlap_score)
        if input_overlap is None or verdict_overlap is None or overlap is None:
            return RejectionCode.UNTYPED
        if overlap != max(input_overlap, verdict_overlap):
            return RejectionCode.UNTYPED
        review = row.manual_review
        expected_family = FORBIDDEN_FAMILY[row.compared_to]
        if review.status is OverlapReviewStatus.INDEPENDENT and review.forbidden_families:
            return RejectionCode.UNTYPED
        if review.status is OverlapReviewStatus.DUPLICATE and (
            not review.forbidden_families
            or any(family is not expected_family for family in review.forbidden_families)
        ):
            return RejectionCode.UNTYPED
    return None


def _schema_problem(candidate: CandidateProposal) -> RejectionCode | None:
    output = candidate.output_contract
    if output.verdict_enum != VERDICTS:
        return RejectionCode.UNTYPED
    lower = _metric(output.confidence_range[0])
    upper = _metric(output.confidence_range[1])
    if lower != Decimal("0.000000") or upper != Decimal("1.000000"):
        return RejectionCode.UNTYPED
    if not output.na_requires_confidence_zero or not output.na_requires_action_none:
        return RejectionCode.UNTYPED
    fields = tuple(str(field) for field in candidate.input_contract.uses_perspective_input_fields)
    if not fields or len(set(fields)) != len(fields) or any(field not in INPUT_FIELDS for field in fields):
        return RejectionCode.UNTYPED
    if not _is_na_behavior(candidate.input_contract.missing_behavior):
        return RejectionCode.UNTYPED
    extra_names: set[str] = set()
    for extra_input in candidate.input_contract.required_extra_inputs:
        if (
            not extra_input.name.strip()
            or extra_input.name in extra_names
            or not extra_input.type
            or not extra_input.type.strip()
            or not extra_input.source_contract
            or not extra_input.source_contract.strip()
            or not _is_na_behavior(extra_input.missing_behavior)
            or extra_input.freshness_budget_hours is None
            or extra_input.freshness_budget_hours <= 0
        ):
            return RejectionCode.UNTYPED
        extra_names.add(extra_input.name)
    return _overlap_problem(candidate)


def _output_problem(output: CandidateOutput | None) -> RejectionCode | None:
    if output is None:
        return None
    if output.verdict not in VERDICTS:
        return RejectionCode.VERDICT
    confidence = _metric(output.confidence)
    if confidence is None:
        return RejectionCode.CONFIDENCE
    if _metric(output.extra.overlap_score) is None:
        return RejectionCode.UNTYPED
    if output.action.type is not ACTION_BY_VERDICT[output.verdict]:
        return RejectionCode.NA if output.verdict == Verdict.NA else RejectionCode.VERDICT
    if output.verdict == Verdict.NA and (
        confidence != 0
        or output.extra.not_applicable_reason is None
        or not output.extra.not_applicable_reason.strip()
    ):
        return RejectionCode.NA
    return None


def _budget_problem(candidate: CandidateProposal) -> RejectionCode | None:
    budget = candidate.budget
    if not 0 < budget.max_wall_ms_per_ticker <= 6000:
        return RejectionCode.BUDGET
    if not 0 <= budget.max_llm_calls_per_ticker <= 1:
        return RejectionCode.BUDGET
    if not 0 <= budget.max_prompt_tokens_per_ticker <= 2500:
        return RejectionCode.BUDGET
    if not 0 <= budget.max_output_tokens_per_ticker <= 900:
        return RejectionCode.BUDGET
    if not 0 <= budget.max_extra_fetches_per_ticker <= 1:
        return RejectionCode.BUDGET
    if budget.max_extra_fetches_per_ticker > 0 and (
        budget.cache_ttl_hours is None or not 0 < budget.cache_ttl_hours <= 168
    ):
        return RejectionCode.BUDGET
    if budget.timeout_behavior != Verdict.NA:
        return RejectionCode.BUDGET
    return None


def _identity_problem(
    candidate: CandidateProposal, output: CandidateOutput | None
) -> RejectionCode | None:
    identity = candidate.candidate_identity
    name = identity.candidate_name
    hypothesis_id = candidate.independent_hypothesis.hypothesis_id
    if (
        not identity.owner.strip()
        or identity.contract_version != CONTRACT_VERSION
        or identity.candidate_id != f"pcand_v6_{name}"
        or re.fullmatch(VERSION_PATTERN, identity.candidate_version) is None
        or not identity.candidate_version.startswith(f"{name}.")
        or not hypothesis_id.startswith(f"hyp_v6_{name}_")
    ):
        return RejectionCode.IDENTITY
    if output is not None and (
        output.perspective != name
        or output.extra.contract_version != CONTRACT_VERSION
        or output.extra.candidate_version != identity.candidate_version
        or output.extra.hypothesis_id != hypothesis_id
    ):
        return RejectionCode.IDENTITY
    return None


def _hypothesis_problem(candidate: CandidateProposal) -> RejectionCode | None:
    hypothesis = candidate.independent_hypothesis
    if (
        not hypothesis.summary.strip()
        or not hypothesis.error_mode_explained.strip()
        or not hypothesis.falsifiable_claim.strip()
        or any(not observation.strip() for observation in hypothesis.primary_observations)
    ):
        return RejectionCode.NO_HYPOTHESIS
    fields = tuple(str(field) for field in candidate.input_contract.uses_perspective_input_fields)
    if fields == (PerspectiveInputField.SIGNALS.value,) and any(
        not item.startswith("signals.") for item in hypothesis.primary_observations
    ):
        return RejectionCode.NO_HYPOTHESIS
    return None


def _claimed_duplicate(candidate: CandidateProposal) -> bool:
    for row in candidate.overlap_matrix:
        overlap = _metric(row.overlap_score)
        if overlap is not None and overlap > OVERLAP_CEILINGS[row.compared_to]:
            return True
    return False


def evaluate_candidate(
    candidate: CandidateProposal, output: CandidateOutput | None = None
) -> CandidateDecision:
    for problem in (
        _schema_problem(candidate),
        _output_problem(output),
        _budget_problem(candidate),
        _identity_problem(candidate, output),
    ):
        if problem is not None:
            return _reject(problem)
    if candidate.requested_stage is RequestedStage.PRODUCTION:
        return _reject(RejectionCode.ADOPTION)
    hypothesis_problem = _hypothesis_problem(candidate)
    if hypothesis_problem is not None:
        return _reject(hypothesis_problem)
    if _claimed_duplicate(candidate) or duplicates_incumbent(candidate):
        return _reject(RejectionCode.DUPLICATE)
    return CandidateDecision(accepted_for_evaluation=True, rejection_code=None)
