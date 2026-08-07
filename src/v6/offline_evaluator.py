from dataclasses import dataclass
from decimal import Decimal

from .candidate_artifact import CandidateArtifact
from .models import ExistingPerspective
from .offline_derive import derive_summary
from .offline_evidence import FrozenEvaluationInput
from .offline_models import OfflineCode, OfflineSummary
from .offline_validation import evidence_failures


@dataclass(frozen=True, slots=True)
class OfflineDecision:
    code: OfflineCode
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    summary: OfflineSummary | None
    decision: OfflineDecision


def _metric_decision(summary: OfflineSummary, candidate: CandidateArtifact, value: FrozenEvaluationInput) -> OfflineDecision:
    config = value.config.body
    if Decimal(summary.holdout_lift_bootstrap_lower_90) > Decimal(summary.holdout_incremental_lift_5) or Decimal(summary.target_error_lift_bootstrap_lower_90) > Decimal(summary.target_error_lift_5):
        return OfflineDecision(OfflineCode.MALFORMED, ("point_bound_inconsistent",))
    if Decimal(summary.max_error_correlation) >= Decimal("0.800000") or Decimal(summary.max_verdict_correlation) >= Decimal("0.900000"):
        closest = max(candidate.candidate_proposal.overlap_matrix, key=lambda item: Decimal(str(item.overlap_score)))
        observations = candidate.candidate_proposal.independent_hypothesis.primary_observations
        if closest.compared_to is ExistingPerspective.QUANT and all(item.startswith("signals.") for item in observations):
            return OfflineDecision(OfflineCode.QUANT_CLONE, ("quant_reweight_clone",))
        return OfflineDecision(OfflineCode.CLONE, ("high_correlation_clone",))
    harmful = Decimal(summary.harm_rate) > Decimal(config.harm_rate_maximum) or Decimal(summary.non_target_harm_rate) > Decimal(config.non_target_harm_rate_maximum) or Decimal(summary.candidate_brier) - Decimal(summary.baseline_brier) >= Decimal("0.020000") or not (Decimal(summary.candidate_ece) <= Decimal("0.100000") or Decimal(summary.baseline_ece) - Decimal(summary.candidate_ece) >= Decimal("0.020000")) or summary.overconfident_error_bucket_count > 0 or Decimal(summary.overall_na_rate) > Decimal("0.150000") or Decimal(summary.target_error_na_rate) > Decimal("0.200000")
    if harmful:
        return OfflineDecision(OfflineCode.HARMFUL, ("harm_calibration_or_coverage_gate",))
    no_lift = Decimal(summary.holdout_lift_bootstrap_lower_90) < Decimal(config.holdout_lift_lower_minimum) or Decimal(summary.target_error_lift_bootstrap_lower_90) < Decimal(config.target_lift_lower_minimum) or Decimal(summary.baseline_miss_recovery_rate) < Decimal(config.recovery_rate_minimum) or Decimal(summary.ablation_remove_novel_observations_lift_drop) < Decimal("0.007000") or Decimal(summary.existing_signal_only_overlap) > Decimal(config.overlap_ceiling) or abs(Decimal(summary.shuffle_candidate_outputs_lift)) > Decimal("0.003000")
    if no_lift:
        return OfflineDecision(OfflineCode.NO_LIFT, ("incremental_or_ablation_gate",))
    insufficient = summary.holdout_eligible_samples < 300 or summary.target_error_samples < 100 or summary.kr_samples < 100 or summary.us_samples < 100 or any(0 < count < 50 for count in (summary.buy_samples, summary.sell_samples, summary.hold_samples)) or summary.minimum_pair_correlation_samples < 100 or summary.minimum_calibration_bucket_samples < 20
    if insufficient:
        return OfflineDecision(OfflineCode.INSUFFICIENT, ("minimum_sample_gate",))
    if not summary.outcome_adapter_available:
        return OfflineDecision(OfflineCode.MISSING_ADAPTER, ("outcome_adapter_missing",))
    return OfflineDecision(OfflineCode.PASS, ())


def evaluate_evidence(candidate: CandidateArtifact, value: FrozenEvaluationInput) -> EvaluationResult:
    failures = evidence_failures(value, candidate, 20)
    if candidate.decision.accepted_for_evaluation is not True:
        failures = (*failures, "prd01_candidate_rejected")
    if failures:
        return EvaluationResult(None, OfflineDecision(OfflineCode.MALFORMED, failures))
    holdout = tuple(record for record in value.records if record.body.split == "holdout_window")
    if not holdout:
        decision = OfflineDecision(OfflineCode.INSUFFICIENT, ("holdout_window_missing",))
        return EvaluationResult(None, decision if value.reported_terminal_code is decision.code else OfflineDecision(OfflineCode.MALFORMED, ("reported_code_mismatch",)))
    if not any(record.body.outcome.adapter_available for record in holdout):
        decision = OfflineDecision(OfflineCode.MISSING_ADAPTER, ("outcome_adapter_missing",))
        return EvaluationResult(None, decision if value.reported_terminal_code is decision.code else OfflineDecision(OfflineCode.MALFORMED, ("reported_code_mismatch",)))
    eligible_holdout = tuple(record for record in holdout if record.body.outcome.adapter_available and record.body.outcome.candidate_edge is not None)
    if not eligible_holdout:
        decision = OfflineDecision(OfflineCode.INSUFFICIENT, ("eligible_holdout_missing",))
        return EvaluationResult(None, decision if value.reported_terminal_code is decision.code else OfflineDecision(OfflineCode.MALFORMED, ("reported_code_mismatch",)))
    if not any(record.body.target_error for record in eligible_holdout):
        decision = OfflineDecision(OfflineCode.INSUFFICIENT, ("target_error_cohort_missing",))
        return EvaluationResult(None, decision if value.reported_terminal_code is decision.code else OfflineDecision(OfflineCode.MALFORMED, ("reported_code_mismatch",)))
    summary = derive_summary(candidate, value)
    current = _metric_decision(summary, candidate, value)
    if value.reported_terminal_code is not current.code:
        return EvaluationResult(summary, OfflineDecision(OfflineCode.MALFORMED, ("reported_code_mismatch",)))
    if current.code is not OfflineCode.PASS:
        return EvaluationResult(summary, current)
    if any(run.terminal_code is not current.code for run in value.repeated_runs):
        return EvaluationResult(summary, OfflineDecision(OfflineCode.FLAKY, ("repeated_decision_mismatch",)))
    return EvaluationResult(summary, current)
