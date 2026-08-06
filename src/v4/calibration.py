from collections.abc import Sequence
from decimal import Decimal

from .calibration_models import (
    ONE,
    ZERO,
    ActionDenominator,
    AttributionSchemaVersion,
    CalibrationBucket,
    CalibrationCohortKey,
    CalibrationCohortSamples,
    CalibrationConfig,
    CalibrationContractVersion,
    CalibrationObservation,
    CalibrationReport,
    CalibrationSample,
    Exchange,
    ExcludedCalibrationSample,
    FillId,
    HoldTradeLinkageError,
    MalformedCalibrationInputError,
    MixedCalibrationCohortError,
    NonPolicyAcceptanceArithmetic,
    PromptBundleVersion,
    Regime,
    SampleBuildResult,
    SampleConstructionReport,
    SampleId,
    ScorerVersion,
    SnapshotSchemaVersion,
    TradeLinkage,
    WeightsVersion,
    validate_calibration_cohort,
    validate_calibration_config,
    validate_calibration_sample,
)
from src.v4.models import Action, MeasurementState

__all__ = (
    "AttributionSchemaVersion", "CalibrationCohortKey", "CalibrationConfig",
    "CalibrationContractVersion", "CalibrationObservation", "CalibrationReport",
    "CalibrationSample", "Exchange", "FillId",
    "HoldTradeLinkageError", "MalformedCalibrationInputError",
    "MixedCalibrationCohortError", "PromptBundleVersion", "Regime", "SampleId",
    "ScorerVersion", "SnapshotSchemaVersion", "TradeLinkage", "WeightsVersion",
    "NonPolicyAcceptanceArithmetic", "build_calibration_sample",
    "build_calibration_samples", "calculate_calibration",
    "calculate_non_policy_acceptance_arithmetic", "group_calibration_samples",
)


def build_calibration_sample(
    observation: CalibrationObservation, config: CalibrationConfig
) -> SampleBuildResult:
    validate_calibration_config(config)
    validate_calibration_cohort(observation.cohort)
    action = observation.cohort.action
    if action is Action.HOLD and not observation.trade_linkage.is_empty:
        raise HoldTradeLinkageError(observation.sample_id)
    match action:  # noqa: MATCH_OK
        case Action.BLOCKED | Action.CANDIDATE_REJECTED:
            return ExcludedCalibrationSample(
                observation.sample_id, action, "action_not_calibrated"
            )
        case Action.BUY | Action.SELL | Action.HOLD:
            pass
    if not observation.native_v4:
        return ExcludedCalibrationSample(
            observation.sample_id, action, "legacy_audit_only"
        )
    match observation.measurement_state:  # noqa: MATCH_OK
        case MeasurementState.MATURED:
            pass
        case MeasurementState.PENDING:
            return ExcludedCalibrationSample(
                observation.sample_id, action, "outcome_pending"
            )
        case MeasurementState.INSUFFICIENT_DATA:
            return ExcludedCalibrationSample(
                observation.sample_id, action, "insufficient_data"
            )
        case MeasurementState.INSUFFICIENT_CONTEXT:
            return ExcludedCalibrationSample(
                observation.sample_id, action, "insufficient_context"
            )
    probability = observation.confidence_probability
    if probability is None or not probability.is_finite() or not ZERO <= probability <= ONE:
        raise MalformedCalibrationInputError(
            "confidence_probability", "must be finite and in [0, 1]", observation.sample_id
        )
    if not observation.sample_weight.is_finite() or observation.sample_weight <= ZERO:
        raise MalformedCalibrationInputError(
            "sample_weight", "must be positive and finite", observation.sample_id
        )
    instrument_return = observation.instrument_return
    benchmark_return = observation.benchmark_return
    if instrument_return is None or benchmark_return is None:
        raise MalformedCalibrationInputError(
            "outcome_return", "matured outcome requires both returns", observation.sample_id
        )
    if not instrument_return.is_finite() or not benchmark_return.is_finite():
        raise MalformedCalibrationInputError(
            "outcome_return", "returns must be finite", observation.sample_id
        )
    buy_edge = instrument_return - benchmark_return
    sell_edge = -buy_edge
    opportunity_cost: Decimal | None = None
    avoided_loss: Decimal | None = None
    match action:  # noqa: MATCH_OK
        case Action.BUY:
            outcome = int(buy_edge >= config.buy_success_threshold)
        case Action.SELL:
            outcome = int(sell_edge >= config.sell_success_threshold)
        case Action.HOLD:
            buy_cost = max(ZERO, buy_edge - config.buy_success_threshold)
            sell_cost = (
                max(ZERO, sell_edge - config.sell_success_threshold)
                if observation.held_position_sell_eligible
                else ZERO
            )
            opportunity_cost = buy_cost + sell_cost
            avoided_loss = max(ZERO, sell_edge)
            outcome = int(opportunity_cost == ZERO)
    return CalibrationSample(
        observation.sample_id,
        observation.cohort,
        probability,
        f"Y_{action}_{observation.cohort.horizon}",
        outcome,
        observation.sample_weight,
        buy_edge,
        sell_edge,
        observation.held_position_sell_eligible,
        opportunity_cost,
        avoided_loss,
    )


def build_calibration_samples(
    observations: Sequence[CalibrationObservation], config: CalibrationConfig
) -> SampleConstructionReport:
    counts = {action: 0 for action in Action}
    samples: list[CalibrationSample] = []
    excluded: list[ExcludedCalibrationSample] = []
    for observation in observations:
        counts[observation.cohort.action] += 1
        result = build_calibration_sample(observation, config)
        match result:  # noqa: MATCH_OK
            case CalibrationSample():
                samples.append(result)
            case ExcludedCalibrationSample():
                excluded.append(result)
    return SampleConstructionReport(
        tuple(ActionDenominator(action, counts[action]) for action in Action),
        tuple(samples),
        tuple(excluded),
    )


def group_calibration_samples(
    samples: Sequence[CalibrationSample],
) -> tuple[CalibrationCohortSamples, ...]:
    grouped: dict[CalibrationCohortKey, list[CalibrationSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.cohort, []).append(sample)
    return tuple(
        CalibrationCohortSamples(cohort, tuple(members))
        for cohort, members in grouped.items()
    )


def calculate_calibration(
    samples: Sequence[CalibrationSample], config: CalibrationConfig
) -> CalibrationReport:
    validate_calibration_config(config)
    if not samples:
        return CalibrationReport(None, "inconclusive", 0, ZERO, None, None, ())
    for sample in samples:
        validate_calibration_sample(sample, config)
    cohort = samples[0].cohort
    for sample in samples[1:]:
        if sample.cohort != cohort:
            raise MixedCalibrationCohortError(cohort, sample.cohort, sample.sample_id)
    weighted_count = sum((sample.sample_weight for sample in samples), ZERO)
    brier = sum(
        (sample.sample_weight * (sample.confidence_probability - sample.correctness_outcome) ** 2 for sample in samples),
        ZERO,
    ) / weighted_count
    grouped: list[list[CalibrationSample]] = [[] for _ in config.bucket_edges[1:]]
    final_index = len(grouped) - 1
    for sample in samples:
        index = next(
            index
            for index, (lower, upper) in enumerate(zip(config.bucket_edges, config.bucket_edges[1:]))
            if lower <= sample.confidence_probability < upper
            or (index == final_index and sample.confidence_probability == upper)
        )
        grouped[index].append(sample)
    buckets: list[CalibrationBucket] = []
    ece = ZERO
    has_small_bucket = False
    for index, members in enumerate(grouped):
        weight = sum((sample.sample_weight for sample in members), ZERO)
        if not members:
            buckets.append(CalibrationBucket(config.bucket_edges[index], config.bucket_edges[index + 1], 0, ZERO, None, None, None, ZERO))
            continue
        confidence = sum((sample.sample_weight * sample.confidence_probability for sample in members), ZERO) / weight
        accuracy = sum((sample.sample_weight * sample.correctness_outcome for sample in members), ZERO) / weight
        gap = abs(accuracy - confidence)
        component = weight / weighted_count * gap
        ece += component
        has_small_bucket = has_small_bucket or len(members) < config.minimum_bucket_samples
        buckets.append(CalibrationBucket(config.bucket_edges[index], config.bucket_edges[index + 1], len(members), weight, confidence, accuracy, gap, component))
    insufficient = len(samples) < config.minimum_total_samples or has_small_bucket
    return CalibrationReport(cohort, "insufficient_sample_no_op" if insufficient else "ready", len(samples), weighted_count, brier, ece, tuple(buckets))


def calculate_non_policy_acceptance_arithmetic(
    reports: Sequence[CalibrationReport], config: CalibrationConfig
) -> NonPolicyAcceptanceArithmetic:
    validate_calibration_config(config)
    measured: list[tuple[CalibrationReport, Decimal]] = []
    cohorts: list[CalibrationCohortKey] = []
    for report in reports:
        if report.cohort is None or report.brier_score is None or report.ece is None:
            raise MalformedCalibrationInputError("report", "acceptance arithmetic requires a measured cohort report")
        if report.cohort in cohorts:
            raise MalformedCalibrationInputError("report.cohort", "acceptance arithmetic requires distinct cohorts")
        cohorts.append(report.cohort)
        measured.append((report, report.brier_score))
    if len(measured) < 2:
        raise MalformedCalibrationInputError("reports", "acceptance arithmetic requires multiple cohorts")
    if any(len(report.buckets) != len(config.bucket_edges) - 1 for report, _ in measured):
        raise MalformedCalibrationInputError("report.buckets", "must match configured edges")
    weighted_count = sum((report.weighted_count for report, _ in measured), ZERO)
    brier = sum((score * report.weighted_count for report, score in measured), ZERO) / weighted_count
    buckets: list[CalibrationBucket] = []
    ece = ZERO
    for index in range(len(config.bucket_edges) - 1):
        sources = tuple(report.buckets[index] for report, _ in measured)
        count = sum(bucket.sample_count for bucket in sources)
        weight = sum((bucket.weighted_count for bucket in sources), ZERO)
        if count == 0:
            buckets.append(CalibrationBucket(config.bucket_edges[index], config.bucket_edges[index + 1], 0, ZERO, None, None, None, ZERO))
            continue
        if any(bucket.average_confidence is None or bucket.empirical_accuracy is None for bucket in sources if bucket.sample_count):
            raise MalformedCalibrationInputError("report.bucket", "non-empty bucket lacks metrics")
        confidence = sum((bucket.average_confidence * bucket.weighted_count for bucket in sources if bucket.average_confidence is not None), ZERO) / weight
        accuracy = sum((bucket.empirical_accuracy * bucket.weighted_count for bucket in sources if bucket.empirical_accuracy is not None), ZERO) / weight
        gap = abs(accuracy - confidence)
        component = weight / weighted_count * gap
        ece += component
        buckets.append(CalibrationBucket(config.bucket_edges[index], config.bucket_edges[index + 1], count, weight, confidence, accuracy, gap, component))
    return NonPolicyAcceptanceArithmetic(
        tuple(cohorts),
        sum(report.sample_count for report, _ in measured),
        weighted_count,
        brier,
        ece,
        tuple(buckets),
    )
