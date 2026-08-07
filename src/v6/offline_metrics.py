from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from random import Random
from typing import Literal

from .offline_evidence import FrozenEvaluationInput, SampleBatchRecord
from .offline_models import BaselineKind, Decimal6


_SIX = Decimal("0.000001")


def decimal6(value: Decimal) -> Decimal6:
    return format(value.quantize(_SIX, rounding=ROUND_HALF_EVEN), ".6f")


def mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal()) / Decimal(len(values))


def baseline_edge(record: SampleBatchRecord, kind: BaselineKind) -> Decimal:
    return next(Decimal(item.edge) for item in record.body.outcome.baseline_edges if item.kind is kind)


def expanded_decimal(records: tuple[SampleBatchRecord, ...], selector: Literal["candidate", "consensus", "gain", "novel_drop", "shuffle_gain"]) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for record in records:
        candidate = record.body.outcome.candidate_edge
        consensus = baseline_edge(record, BaselineKind.CONSENSUS)
        match selector:  # noqa: MATCH_OK - internal closed selector
            case "candidate":
                selected = Decimal(candidate) if candidate is not None else None
            case "consensus":
                selected = consensus
            case "gain":
                selected = Decimal(candidate) - consensus if candidate is not None else None
            case "novel_drop":
                ablated = record.body.ablation.remove_novel_observations_edge
                selected = Decimal(candidate) - Decimal(ablated) if candidate is not None and ablated is not None else None
            case "shuffle_gain":
                shuffled = record.body.ablation.shuffled_candidate_edge
                selected = Decimal(shuffled) - consensus if shuffled is not None else None
        if selected is not None:
            values.extend(selected for _ in range(record.body.sample_count))
    return tuple(values)


def pearson(left: tuple[int, ...], right: tuple[int, ...]) -> Decimal:
    left_mean = mean(tuple(Decimal(value) for value in left))
    right_mean = mean(tuple(Decimal(value) for value in right))
    numerator = sum(((Decimal(x) - left_mean) * (Decimal(y) - right_mean) for x, y in zip(left, right, strict=True)), Decimal())
    left_square = sum(((Decimal(value) - left_mean) ** 2 for value in left), Decimal())
    right_square = sum(((Decimal(value) - right_mean) ** 2 for value in right), Decimal())
    denominator = (left_square * right_square).sqrt()
    return Decimal() if denominator == 0 else numerator / denominator


def bootstrap_lower(values: tuple[Decimal, ...], iterations: int, seed: str) -> Decimal:
    random = Random(seed)
    size = len(values)
    estimates = sorted(mean(tuple(values[random.randrange(size)] for _ in range(size))) for _ in range(iterations))
    return estimates[iterations // 10]


def calibration(probabilities: tuple[Decimal, ...], hits: tuple[int, ...]) -> tuple[Decimal, Decimal, int, int]:
    brier = mean(tuple((probability - Decimal(hit)) ** 2 for probability, hit in zip(probabilities, hits, strict=True)))
    ece = Decimal()
    overconfident = 0
    minimum_bucket = len(probabilities)
    boundaries = ((Decimal("0.0"), Decimal("0.2")), (Decimal("0.2"), Decimal("0.4")), (Decimal("0.4"), Decimal("0.6")), (Decimal("0.6"), Decimal("0.8")), (Decimal("0.8"), Decimal("1.000001")))
    for lower, upper in boundaries:
        indexes = tuple(index for index, value in enumerate(probabilities) if lower <= value < upper)
        if indexes:
            accuracy = mean(tuple(Decimal(hits[index]) for index in indexes))
            confidence = mean(tuple(probabilities[index] for index in indexes))
            gap = abs(accuracy - confidence)
            ece += Decimal(len(indexes)) / Decimal(len(probabilities)) * gap
            minimum_bucket = min(minimum_bucket, len(indexes))
            overconfident += int(len(indexes) >= 20 and gap > Decimal("0.200000"))
    return brier, ece, overconfident, minimum_bucket


@dataclass(frozen=True, slots=True)
class HandMetrics:
    mean_baseline_edge: Decimal6
    mean_candidate_edge: Decimal6
    incremental_lift: Decimal6
    closest_incremental_lift: Decimal6
    equal_weight_incremental_lift: Decimal6
    candidate_hits: int
    candidate_errors: int
    harm_rate: Decimal6
    baseline_miss_recovery_rate: Decimal6
    error_correlation: Decimal6
    verdict_correlation: Decimal6
    brier: Decimal6
    ece: Decimal6


def derive_hand_metrics(value: FrozenEvaluationInput) -> HandMetrics:
    records = value.records
    threshold = Decimal(value.config.body.success_threshold)
    candidate = expanded_decimal(records, "candidate")
    consensus = expanded_decimal(records, "consensus")
    gains = expanded_decimal(records, "gain")
    closest = tuple(edge for record in records for edge in (baseline_edge(record, BaselineKind.CLOSEST),) * record.body.sample_count)
    equal_weight = tuple(edge for record in records for edge in (baseline_edge(record, BaselineKind.EQUAL_WEIGHT),) * record.body.sample_count)
    probabilities = tuple(Decimal(record.body.candidate.confidence) for record in records for _ in range(record.body.sample_count) if record.body.outcome.candidate_edge is not None)
    candidate_hits = tuple(int(edge >= threshold) for edge in candidate)
    baseline_hits = tuple(int(edge >= threshold) for edge in consensus)
    candidate_errors = tuple(1 - hit for hit in candidate_hits)
    baseline_errors = tuple(1 - hit for hit in baseline_hits)
    recovered = sum(int(base == 0 and candidate_hit == 1) for base, candidate_hit in zip(baseline_hits, candidate_hits, strict=True))
    misses = sum(baseline_errors)
    brier, ece, _, _ = calibration(probabilities, candidate_hits)
    candidate_directions = tuple(record.body.candidate.verdict_direction for record in records for _ in range(record.body.sample_count) if record.body.outcome.candidate_edge is not None)
    nearest_directions = tuple(next(item.verdict_direction for item in record.body.baselines if item.kind is BaselineKind.CLOSEST) for record in records for _ in range(record.body.sample_count) if record.body.outcome.candidate_edge is not None)
    return HandMetrics(decimal6(mean(consensus)), decimal6(mean(candidate)), decimal6(mean(gains)), decimal6(mean(tuple(edge - base for edge, base in zip(candidate, closest, strict=True)))), decimal6(mean(tuple(edge - base for edge, base in zip(candidate, equal_weight, strict=True)))), sum(candidate_hits), sum(candidate_errors), decimal6(Decimal(sum(int(gain <= Decimal("-0.020000")) for gain in gains)) / Decimal(len(gains))), decimal6(Decimal(recovered) / Decimal(misses)), decimal6(pearson(candidate_errors, baseline_errors)), decimal6(pearson(candidate_directions, nearest_directions)), decimal6(brier), decimal6(ece))
