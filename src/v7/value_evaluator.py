from dataclasses import dataclass
from decimal import Decimal

from .models import ProvenanceContractError
from .provenance import verify_artifact as verify_provenance
from .quality_artifact import verify_quality_artifact
from .quality_models import QualityContractError
from .value_derivation import ValueMetrics, derive_metrics
from .value_models import SourceBinding, ValueCode, ValueContractError, canonical_thresholds
from .value_observations import PairedObservation, fact_audit_hash, observation_hash, outcome_hash, output_hash
from .value_trust import ValueTrustContext, require_value_context


@dataclass(frozen=True, slots=True)
class ValueEvaluation:
    metrics: ValueMetrics
    code: ValueCode
    reasons: tuple[str, ...]
    policy_no_op: bool
    promotion_eligible: bool


def _lineage(binding: SourceBinding, context: ValueTrustContext) -> None:
    bundle = binding.provenance_bundle
    try:
        provenance = verify_provenance(bundle.artifact.model_dump(mode="json"), context.provenance_context)
    except ProvenanceContractError as error:
        raise ValueContractError("PRD01_LINEAGE_INVALID", str(error)) from error
    try:
        quality = verify_quality_artifact(binding.quality_artifact.model_dump(mode="json"), context.quality_context)
    except QualityContractError as error:
        raise ValueContractError("PRD02_LINEAGE_INVALID", str(error)) from error
    embedded = tuple(item.bundle for item in quality.build_input.sources)
    if bundle not in embedded or binding.adapter_id != provenance.adapter_id:
        raise ValueContractError("SOURCE_LINEAGE_MISMATCH", "quality does not bind the trusted provenance bundle")
    if quality.source_registry_root != str(context.quality_context.registry_root):
        raise ValueContractError("SOURCE_LINEAGE_MISMATCH", "quality registry root differs")
    if quality.result_label != "pass" or quality.quality_label not in ("high", "usable"):
        raise ValueContractError("PRD02_LINEAGE_INVALID", "quality artifact is not source eligible")


def _arm(sample: PairedObservation, arm_name: str, context: ValueTrustContext) -> None:
    arm = {"off": sample.off, "on": sample.on, "masked": sample.masked}[arm_name]
    manifest = context.cohort_manifest
    identity = (sample.sample_id, sample.market, sample.ticker, sample.action, sample.horizon, sample.prompt_bundle, sample.scorer_version, sample.portfolio_hash, sample.decision_cutoff, sample.outcome_cutoff)
    arm_identity = (arm.sample_id, arm.market, arm.ticker, arm.action, arm.horizon, arm.prompt_bundle, arm.scorer_version, arm.portfolio_hash, arm.decision_cutoff, arm.outcome_cutoff)
    if identity != arm_identity or arm.arm != arm_name:
        raise ValueContractError("IDENTITY_MISMATCH", f"{sample.sample_id}:{arm_name}")
    if (arm.prompt_bundle, arm.scorer_version, arm.portfolio_hash, arm.decision_cutoff, arm.outcome_cutoff) != (manifest.prompt_bundle, manifest.scorer_version, manifest.portfolio_hash, manifest.decision_cutoff, manifest.outcome_cutoff):
        raise ValueContractError("IDENTITY_MISMATCH", f"{sample.sample_id}:{arm_name}")
    if arm.latest_feature_at > arm.decision_cutoff:
        raise ValueContractError("FUTURE_FEATURE_LEAKAGE", sample.sample_id)
    if output_hash(arm) != arm.output_hash:
        raise ValueContractError("OBSERVATION_HASH_MISMATCH", f"{sample.sample_id}:{arm_name}")


def _sample(sample: PairedObservation, expected_index: int, context: ValueTrustContext) -> None:
    expected = context.cohort_manifest.samples[expected_index]
    manifest = context.cohort_manifest
    actual_identity = (sample.sample_id, sample.market, sample.ticker, sample.action, sample.target_error, sample.fact_audit.audit_class)
    expected_identity = (expected.sample_id, expected.market, expected.ticker, expected.action, expected.target_error, expected.fact_audit_class)
    if actual_identity != expected_identity:
        raise ValueContractError("INVENTORY_MISMATCH", expected.sample_id)
    if (sample.horizon, sample.prompt_bundle, sample.scorer_version, sample.portfolio_hash, sample.decision_cutoff, sample.outcome_cutoff) != (manifest.horizon, manifest.prompt_bundle, manifest.scorer_version, manifest.portfolio_hash, manifest.decision_cutoff, manifest.outcome_cutoff):
        raise ValueContractError("IDENTITY_MISMATCH", sample.sample_id)
    for arm_name in ("off", "on", "masked"):
        _arm(sample, arm_name, context)
    declared_hashes = (sample.fact_audit.fact_audit_hash, sample.off.output_hash, sample.on.output_hash, sample.masked.output_hash)
    expected_hashes = (expected.fact_audit_hash, expected.off_output_hash, expected.on_output_hash, expected.masked_output_hash)
    if declared_hashes != expected_hashes or fact_audit_hash(sample.fact_audit) != sample.fact_audit.fact_audit_hash:
        raise ValueContractError("OBSERVATION_HASH_MISMATCH", sample.sample_id)
    if observation_hash(sample) != sample.content_hash:
        raise ValueContractError("OBSERVATION_HASH_MISMATCH", f"content:{sample.sample_id}")
    if sample.outcome.outcome_hash != expected.outcome_hash:
        raise ValueContractError("OUTCOME_HASH_MISMATCH", f"manifest:{sample.sample_id}")
    if outcome_hash(sample.outcome) != sample.outcome.outcome_hash:
        raise ValueContractError("OUTCOME_HASH_MISMATCH", sample.sample_id)
    if sample.outcome.observed_at < max(sample.off.emitted_at, sample.on.emitted_at, sample.masked.emitted_at) or sample.outcome.observed_at > manifest.outcome_cutoff:
        raise ValueContractError("FUTURE_OUTCOME_LEAKAGE", sample.sample_id)
    edges = (sample.off.edge_5, sample.on.edge_5, sample.masked.edge_5)
    outcome_edges = (sample.outcome.off_correctness_edge_5, sample.outcome.on_correctness_edge_5, sample.outcome.masked_correctness_edge_5)
    if edges != outcome_edges:
        raise ValueContractError("OUTCOME_HASH_MISMATCH", f"edge:{sample.sample_id}")
    if context.outcome_registry is not None:
        trusted = context.outcome_registry.outcomes[expected_index]
        if sample.outcome != trusted or sample.outcome.adapter_body_hash != context.outcome_registry.adapter.body_hash:
            raise ValueContractError("OUTCOME_HASH_MISMATCH", f"trusted:{sample.sample_id}")


def validate_observations(binding: SourceBinding, observations: tuple[PairedObservation, ...], context: ValueTrustContext | None) -> None:
    trusted = require_value_context(context)
    _lineage(binding, trusted)
    expected_ids = tuple(item.sample_id for item in trusted.cohort_manifest.samples)
    actual_ids = tuple(item.sample_id for item in observations)
    if len(set(actual_ids)) != len(actual_ids):
        raise ValueContractError("DUPLICATE_SAMPLE_ID", "sample ids must be unique")
    if actual_ids != expected_ids:
        raise ValueContractError("INVENTORY_MISMATCH", "observation set differs from trusted manifest")
    for index, sample in enumerate(observations):
        _sample(sample, index, trusted)
    binding_values = (binding.provenance_bundle.artifact.provenance_hash, binding.provenance_bundle.trusted_payload_manifest.manifest_hash, binding.quality_artifact.artifact_hash, binding.quality_artifact.source_registry_root)
    if any((item.source_provenance_hash, item.source_manifest_root, item.source_quality_hash, item.quality_registry_root) != binding_values for item in observations):
        raise ValueContractError("SOURCE_LINEAGE_MISMATCH", "sample lineage differs from trusted source roots")
    if not any(item.on.source_eligible for item in observations):
        raise ValueContractError("MISSING_ON_COVERAGE", "no eligible ON observations")
    threshold = canonical_thresholds()
    if any(item.on.fetches - item.off.fetches > threshold.added_fetches_per_ticker_max for item in observations):
        raise ValueContractError("FETCH_BUDGET_EXCEEDED", "added fetches exceed canonical budget")


def _minimums(observations: tuple[PairedObservation, ...], metrics: ValueMetrics) -> bool:
    markets = {market: sum(item.market == market and item.on.source_eligible for item in observations) for market in ("KR", "US")}
    actions = {action: sum(item.action == action and item.on.source_eligible for item in observations) for action in ("BUY", "SELL", "HOLD")}
    return metrics.eligible_pairs >= 300 and metrics.target_pairs >= 100 and metrics.known_error_pairs >= 80 and metrics.calibration_bucket_min >= 20 and all(count >= 100 for count in markets.values()) and all(count >= 50 for count in actions.values())


def evaluate_value(binding: SourceBinding, observations: tuple[PairedObservation, ...], context: ValueTrustContext | None) -> ValueEvaluation:
    trusted = require_value_context(context)
    validate_observations(binding, observations, trusted)
    threshold = canonical_thresholds()
    metrics = derive_metrics(observations, threshold)
    if trusted.outcome_registry is None:
        return ValueEvaluation(metrics, "INCONCLUSIVE_MISSING_OUTCOME_ADAPTER", ("trusted outcome adapter is absent",), True, False)
    if not _minimums(observations, metrics):
        return ValueEvaluation(metrics, "INCONCLUSIVE_INSUFFICIENT_SAMPLE", ("minimum sample gate failed",), True, False)
    if metrics.harm_rate > threshold.harm_rate_max or metrics.severe_harm_rate > threshold.severe_harm_rate_max or metrics.coverage_gap_harm_rate > 0:
        return ValueEvaluation(metrics, "REJECT_HARMFUL_SOURCE", ("harm threshold failed",), True, False)
    factual = metrics.correction_precision >= threshold.correction_precision_min and metrics.correction_recall >= threshold.correction_recall_min and metrics.unsupported_correction_rate <= threshold.unsupported_correction_rate_max and metrics.new_false_fact_rate <= threshold.new_false_fact_rate_max
    verdict = metrics.verdict_lift_lower_90 >= threshold.verdict_lift_lower_90_min and metrics.factual_recovery_rate >= threshold.factual_recovery_rate_min and metrics.verdict_flip_precision >= threshold.verdict_flip_precision_min
    if metrics.verdict_lift_5 <= 0 and metrics.correction_recall == 0 and (metrics.mean_added_wall_ms < 0 or metrics.added_prompt_tokens_per_ticker < 0):
        return ValueEvaluation(metrics, "REJECT_LATENCY_ONLY", ("only latency or cost improved",), True, False)
    calibration = (metrics.calibration_brier_delta <= Decimal("-0.010") or (metrics.calibration_brier_delta <= Decimal("0.005") and verdict)) and (metrics.calibration_ece_delta <= Decimal("-0.010") or metrics.on_ece <= Decimal("0.10"))
    operational = metrics.coverage_rate >= threshold.coverage_rate_min and metrics.target_coverage_rate >= threshold.target_coverage_rate_min and metrics.p95_added_wall_ms <= threshold.p95_added_wall_ms_max and metrics.mean_added_wall_ms <= threshold.mean_added_wall_ms_max and metrics.added_prompt_tokens_per_ticker <= threshold.added_prompt_tokens_per_ticker_max and metrics.added_fetches_per_ticker <= threshold.added_fetches_per_ticker_max and metrics.timeout_rate <= threshold.timeout_rate_max
    masked = metrics.masked_lift_5 < metrics.verdict_lift_5 and metrics.masked_lift_5 < threshold.verdict_lift_lower_90_min
    if factual and verdict and calibration and operational and masked:
        return ValueEvaluation(metrics, "PASS_INCREMENTAL_VALUE_EVALUATION", (), False, True)
    return ValueEvaluation(metrics, "REJECT_NO_INCREMENTAL_VALUE", ("one or more value gates failed",), True, False)


def terminal_code_for(binding: SourceBinding, observations: tuple[PairedObservation, ...], context: ValueTrustContext | None) -> ValueCode:
    try:
        return evaluate_value(binding, observations, context).code
    except ValueContractError:
        return "REJECT_MALFORMED_EVALUATION_INPUT"
