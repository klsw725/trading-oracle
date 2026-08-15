from __future__ import annotations

from decimal import Decimal
from typing import Literal, assert_never

from src.v11.canonical import canonical_hash, model_json

from .hypothesis_models import CorrectionArtifact, FrozenHypothesisRegistry
from .metric_models import MetricsArtifact
from .multiple_testing import one_sided_alpha
from .verdict_models import (
    HoldoutVerdict,
    HoldoutVerdictArtifact,
    HoldoutVerdictBody,
    MetricScenario,
    ValidationVerdict,
    ValidationVerdictArtifact,
    ValidationVerdictBody,
    VerdictEvidence,
    VerdictEvidenceBody,
)


type OutcomeId = Literal[
    "pass", "no_edge", "cost_fragile", "multiple_testing",
    "inconclusive", "insufficient_sample", "invalid_experiment",
]
type ValidationOutcomeId = Literal[
    "validation_pass", "validation_reject", "validation_inconclusive"
]


def _seal_evidence(body: VerdictEvidenceBody) -> VerdictEvidence:
    return VerdictEvidence(hypothesis_id=body.hypothesis_id,
        integrity_valid=body.integrity_valid, signal_days=body.signal_days,
        completed_trades=body.completed_trades, ci_lower=body.ci_lower,
        ci_upper=body.ci_upper, baseline_return=body.baseline_return,
        stress_return=body.stress_return,
        one_sided_p_value=body.one_sided_p_value,
        evidence_hash=canonical_hash(model_json(body)))


def evidence_from_metrics(
    metrics: MetricsArtifact, integrity_valid: bool
) -> VerdictEvidence:
    return _seal_evidence(VerdictEvidenceBody(
        hypothesis_id=metrics.hypothesis_id, integrity_valid=integrity_valid,
        signal_days=metrics.sample.independent_signal_days,
        completed_trades=metrics.sample.completed_trades,
        ci_lower=metrics.baseline.bootstrap.ci_lower,
        ci_upper=metrics.baseline.bootstrap.ci_upper,
        baseline_return=metrics.baseline.cumulative_net_excess_return,
        stress_return=metrics.stress.cumulative_net_excess_return,
        one_sided_p_value=metrics.baseline.bootstrap.one_sided_p_value))


def evidence_from_scenario(scenario: MetricScenario) -> VerdictEvidence:
    return _seal_evidence(VerdictEvidenceBody(
        hypothesis_id=scenario.hypothesis_id,
        integrity_valid=scenario.integrity_valid,
        signal_days=scenario.signal_days, completed_trades=scenario.completed_trades,
        ci_lower=scenario.ci_lower, ci_upper=scenario.ci_upper,
        baseline_return=scenario.baseline_return,
        stress_return=scenario.stress_return,
        one_sided_p_value=Decimal(1 + scenario.bootstrap_non_positive_count)
            / Decimal(10001)))


def confirmatory_gate(
    registry: FrozenHypothesisRegistry,
    evidence: VerdictEvidence,
    holm: CorrectionArtifact,
) -> bool:
    if evidence.hypothesis_id == registry.primary.hypothesis_id:
        return one_sided_alpha(evidence.one_sided_p_value)
    matches = tuple(item for item in holm.results
        if item.hypothesis_id == evidence.hypothesis_id)
    return len(matches) == 1 and matches[0].correction_passed


def validation_verdict(evidence: VerdictEvidence) -> ValidationVerdictArtifact:
    if evidence.signal_days < 60 or evidence.completed_trades < 150:
        verdict = ValidationVerdict.INCONCLUSIVE
    elif not evidence.integrity_valid or evidence.baseline_return <= 0 \
            or evidence.stress_return <= 0 or evidence.ci_upper <= 0:
        verdict = ValidationVerdict.REJECT
    else:
        verdict = ValidationVerdict.PASS
    body = ValidationVerdictBody(schema_version="v14.validation_verdict.1",
        evidence_hash=evidence.evidence_hash, verdict=verdict)
    return ValidationVerdictArtifact(schema_version=body.schema_version,
        evidence_hash=body.evidence_hash, verdict=body.verdict,
        verdict_hash=canonical_hash(model_json(body)))


def holdout_verdict(
    evidence: VerdictEvidence, correction_passed: bool
) -> HoldoutVerdictArtifact:
    if not evidence.integrity_valid:
        verdict = HoldoutVerdict.INVALID_EXPERIMENT
    elif evidence.signal_days < 100 or evidence.completed_trades < 300:
        verdict = HoldoutVerdict.INSUFFICIENT_SAMPLE
    elif evidence.ci_upper <= 0:
        verdict = HoldoutVerdict.NO_EDGE
    elif evidence.stress_return <= 0:
        verdict = HoldoutVerdict.COST_FRAGILE
    elif evidence.ci_lower <= 0 or evidence.baseline_return <= 0:
        verdict = HoldoutVerdict.INCONCLUSIVE
    elif not correction_passed:
        verdict = HoldoutVerdict.MULTIPLE_TESTING
    else:
        verdict = HoldoutVerdict.PASS
    body = HoldoutVerdictBody(schema_version="v14.holdout_verdict.1",
        evidence_hash=evidence.evidence_hash,
        correction_passed=correction_passed, verdict=verdict)
    return HoldoutVerdictArtifact(schema_version=body.schema_version,
        evidence_hash=body.evidence_hash,
        correction_passed=body.correction_passed, verdict=body.verdict,
        verdict_hash=canonical_hash(model_json(body)))


def holdout_outcome_id(verdict: HoldoutVerdict) -> OutcomeId:
    match verdict:  # noqa: MATCH_OK - exhaustive cases end in assert_never below
        case HoldoutVerdict.PASS:
            return "pass"
        case HoldoutVerdict.NO_EDGE:
            return "no_edge"
        case HoldoutVerdict.COST_FRAGILE:
            return "cost_fragile"
        case HoldoutVerdict.MULTIPLE_TESTING:
            return "multiple_testing"
        case HoldoutVerdict.INCONCLUSIVE:
            return "inconclusive"
        case HoldoutVerdict.INSUFFICIENT_SAMPLE:
            return "insufficient_sample"
        case HoldoutVerdict.INVALID_EXPERIMENT:
            return "invalid_experiment"
    assert_never(verdict)


def validation_outcome_id(verdict: ValidationVerdict) -> ValidationOutcomeId:
    match verdict:  # noqa: MATCH_OK - exhaustive cases end in assert_never below
        case ValidationVerdict.PASS:
            return "validation_pass"
        case ValidationVerdict.REJECT:
            return "validation_reject"
        case ValidationVerdict.INCONCLUSIVE:
            return "validation_inconclusive"
    assert_never(verdict)
