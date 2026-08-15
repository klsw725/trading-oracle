from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json

from .contract import V14ContractError
from .hypothesis_models import CorrectionArtifact, FrozenHypothesisRegistry
from .metric_models import MetricsArtifact
from .observed_models import (
    ObservedStrategyVerdictArtifact,
    ObservedStrategyVerdictBody,
)
from .series_models import ResearchSegment
from .verdict_models import ValidationVerdict
from .verdicts import (
    confirmatory_gate,
    evidence_from_metrics,
    holdout_verdict,
    validation_verdict,
)


def build_strategy_verdict(
    registry: FrozenHypothesisRegistry,
    metrics: MetricsArtifact,
    correction: CorrectionArtifact,
) -> ObservedStrategyVerdictArtifact:
    if correction.market is not metrics.market \
            or correction.segment is not metrics.segment:
        raise V14ContractError("V14_CORRECTION_SCOPE", metrics.metrics_hash)
    evidence = evidence_from_metrics(metrics, integrity_valid=True)
    correction_passed = confirmatory_gate(registry, evidence, correction)
    validation_raw = validation_verdict(evidence).verdict
    validation_result = ValidationVerdict.REJECT \
        if validation_raw is ValidationVerdict.PASS and not correction_passed \
        else validation_raw
    verdict = {
        ResearchSegment.VALIDATION: validation_result,
        ResearchSegment.HOLDOUT: holdout_verdict(evidence, correction_passed).verdict,
    }[metrics.segment]
    correction_hash = None if metrics.hypothesis_id \
        == registry.primary.hypothesis_id else correction.correction_hash
    body = ObservedStrategyVerdictBody(
        schema_version="v14.observed_strategy_verdict.1",
        plan_manifest_hash=metrics.plan_manifest_hash,
        registry_hash=registry.registry_hash, market=metrics.market,
        segment=metrics.segment, hypothesis_id=metrics.hypothesis_id,
        configuration_id=metrics.configuration_id,
        metrics_hash=metrics.metrics_hash,
        bootstrap_hash=metrics.baseline.bootstrap.bootstrap_hash,
        correction_hash=correction_hash, evidence_hash=evidence.evidence_hash,
        correction_passed=correction_passed, verdict=verdict)
    return ObservedStrategyVerdictArtifact(schema_version=body.schema_version,
        plan_manifest_hash=body.plan_manifest_hash,
        registry_hash=body.registry_hash, market=body.market,
        segment=body.segment, hypothesis_id=body.hypothesis_id,
        configuration_id=body.configuration_id, metrics_hash=body.metrics_hash,
        bootstrap_hash=body.bootstrap_hash, correction_hash=body.correction_hash,
        evidence_hash=body.evidence_hash,
        correction_passed=body.correction_passed, verdict=body.verdict,
        verdict_hash=canonical_hash(model_json(body)))
