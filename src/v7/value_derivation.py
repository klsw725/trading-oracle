from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256

from src.v6.models import BoundaryModel

from .value_models import ValueThresholds
from .value_observations import PairedObservation

ZERO = Decimal("0")


class ValueMetrics(BoundaryModel):
    verdict_lift_5: Decimal
    verdict_lift_lower_90: Decimal
    masked_lift_5: Decimal
    factual_recovery_rate: Decimal
    correction_precision: Decimal
    correction_recall: Decimal
    unsupported_correction_rate: Decimal
    new_false_fact_rate: Decimal
    verdict_flip_precision: Decimal
    off_brier: Decimal
    on_brier: Decimal
    calibration_brier_delta: Decimal
    off_ece: Decimal
    on_ece: Decimal
    calibration_ece_delta: Decimal
    coverage_rate: Decimal
    target_coverage_rate: Decimal
    p95_added_wall_ms: int
    mean_added_wall_ms: int
    added_prompt_tokens_per_ticker: int
    added_fetches_per_ticker: Decimal
    timeout_rate: Decimal
    harm_rate: Decimal
    severe_harm_rate: Decimal
    coverage_gap_harm_rate: Decimal
    eligible_pairs: int
    target_pairs: int
    known_error_pairs: int
    calibration_bucket_min: int


def _ratio(numerator: int | Decimal, denominator: int) -> Decimal:
    return ZERO if denominator == 0 else Decimal(numerator) / Decimal(denominator)


def _bootstrap_lower(gains: tuple[Decimal, ...]) -> Decimal:
    means: list[Decimal] = []
    count = len(gains)
    for repeat in range(200):
        total = ZERO
        for draw in range(count):
            digest = sha256(f"prd03:{repeat}:{draw}".encode()).digest()
            total += gains[int.from_bytes(digest[:4]) % count]
        means.append(total / count)
    return sorted(means)[19]


def _calibration(rows: tuple[tuple[Decimal, bool], ...]) -> tuple[Decimal, Decimal, int]:
    brier = sum(
        ((confidence - Decimal(int(correct))) ** 2 for confidence, correct in rows),
        start=ZERO,
    ) / len(rows)
    buckets: dict[int, list[tuple[Decimal, bool]]] = defaultdict(list)
    for confidence, correct in rows:
        buckets[int(confidence * 10)].append((confidence, correct))
    ece = sum(
        (
            Decimal(len(bucket))
            / len(rows)
            * abs(
                sum((item[0] for item in bucket), start=ZERO) / len(bucket)
                - _ratio(sum(item[1] for item in bucket), len(bucket))
            )
            for bucket in buckets.values()
        ),
        start=ZERO,
    )
    return brier, ece, min(len(bucket) for bucket in buckets.values())


def derive_metrics(
    observations: tuple[PairedObservation, ...], thresholds: ValueThresholds
) -> ValueMetrics:
    eligible = tuple(item for item in observations if item.on.source_eligible)
    gains = tuple(item.on.edge_5 - item.off.edge_5 for item in eligible)
    masked = tuple(item.masked.edge_5 - item.off.edge_5 for item in eligible)
    claimed = tuple(item for item in eligible if item.fact_audit.correction_claimed)
    errors = tuple(item for item in observations if item.fact_audit.known_baseline_error)
    true_corrections = tuple(item for item in claimed if item.fact_audit.correction_true)
    target = tuple(item for item in observations if item.target_error)
    target_eligible = tuple(item for item in target if item.on.source_eligible)
    flips = tuple(item for item in eligible if (item.off.edge_5 >= thresholds.success_threshold_5) != (item.on.edge_5 >= thresholds.success_threshold_5))
    beneficial = tuple(item for item in flips if item.on.edge_5 >= thresholds.success_threshold_5)
    off_rows = tuple((item.off.confidence, item.off.edge_5 >= thresholds.success_threshold_5) for item in eligible)
    on_rows = tuple((item.on.confidence, item.on.edge_5 >= thresholds.success_threshold_5) for item in eligible)
    off_brier, off_ece, off_bucket = _calibration(off_rows)
    on_brier, on_ece, on_bucket = _calibration(on_rows)
    added_wall = sorted(item.on.wall_ms - item.off.wall_ms for item in eligible)
    p95_index = int((Decimal("0.95") * len(added_wall)).to_integral_value(rounding=ROUND_CEILING)) - 1
    harms = tuple(gain for gain in gains if gain <= Decimal("-0.02"))
    severe = tuple(gain for gain in gains if gain <= Decimal("-0.05"))
    coverage_gap_harms = sum(
        not item.on.source_eligible
        and item.on.source_fact_visible
        and item.on.edge_5 - item.off.edge_5 <= Decimal("-0.02")
        for item in observations
    )
    recovered = sum(item.fact_audit.correction_true and item.on.edge_5 >= thresholds.success_threshold_5 for item in errors)
    return ValueMetrics(
        verdict_lift_5=sum(gains, start=ZERO) / len(gains), verdict_lift_lower_90=_bootstrap_lower(gains),
        masked_lift_5=sum(masked, start=ZERO) / len(masked), factual_recovery_rate=_ratio(recovered, len(errors)),
        correction_precision=_ratio(len(true_corrections), len(claimed)), correction_recall=_ratio(len(true_corrections), len(errors)),
        unsupported_correction_rate=_ratio(sum(not item.fact_audit.correction_supported for item in claimed), len(claimed)),
        new_false_fact_rate=_ratio(sum(item.fact_audit.new_false_fact for item in eligible), len(eligible)),
        verdict_flip_precision=_ratio(len(beneficial), len(flips)), off_brier=off_brier, on_brier=on_brier,
        calibration_brier_delta=on_brier - off_brier, off_ece=off_ece, on_ece=on_ece,
        calibration_ece_delta=on_ece - off_ece, coverage_rate=_ratio(len(eligible), len(observations)),
        target_coverage_rate=_ratio(len(target_eligible), len(target)), p95_added_wall_ms=added_wall[p95_index],
        mean_added_wall_ms=sum(added_wall) // len(added_wall),
        added_prompt_tokens_per_ticker=sum(item.on.prompt_tokens - item.off.prompt_tokens for item in eligible) // len(eligible),
        added_fetches_per_ticker=_ratio(sum(item.on.fetches - item.off.fetches for item in eligible), len(eligible)),
        timeout_rate=_ratio(sum(item.on.timeout for item in eligible), len(eligible)), harm_rate=_ratio(len(harms), len(eligible)),
        severe_harm_rate=_ratio(len(severe), len(eligible)), coverage_gap_harm_rate=_ratio(coverage_gap_harms, len(observations)),
        eligible_pairs=len(eligible), target_pairs=len(target), known_error_pairs=len(errors),
        calibration_bucket_min=min(off_bucket, on_bucket),
    )
