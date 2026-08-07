from decimal import Decimal, ROUND_CEILING
from typing import Literal

from .candidate_artifact import CandidateArtifact
from .models import ExistingPerspective, Verdict
from .offline_evidence import FrozenEvaluationInput, SampleBatchRecord
from .offline_metrics import baseline_edge, bootstrap_lower, calibration, decimal6, expanded_decimal, mean, pearson
from .offline_models import BaselineKind, BaselineMetric, OfflineSummary, PerspectiveCorrelation


def _eligible(value: FrozenEvaluationInput) -> tuple[SampleBatchRecord, ...]:
    return tuple(record for record in value.records if record.body.split == "holdout_window" and record.body.outcome.adapter_available and record.body.outcome.candidate_edge is not None)


def _expanded_int(records: tuple[SampleBatchRecord, ...], selector: Literal["candidate_hit", "candidate_direction"], threshold: Decimal) -> tuple[int, ...]:
    values: list[int] = []
    for record in records:
        match selector:  # noqa: MATCH_OK - internal closed selector
            case "candidate_hit":
                edge = record.body.outcome.candidate_edge
                selected = int(Decimal(edge) >= threshold) if edge is not None else 0
            case "candidate_direction":
                selected = record.body.candidate.verdict_direction
        values.extend(selected for _ in range(record.body.sample_count))
    return tuple(values)


def _perspective_values(records: tuple[SampleBatchRecord, ...], perspective: ExistingPerspective, threshold: Decimal) -> tuple[tuple[int, ...], tuple[int, ...]]:
    hits: list[int] = []
    directions: list[int] = []
    for record in records:
        edge = next(Decimal(item.edge) for item in record.body.outcome.perspective_edges if item.perspective is perspective)
        direction = next(item.verdict_direction for item in record.body.perspectives if item.perspective is perspective)
        hits.extend(int(edge >= threshold) for _ in range(record.body.sample_count))
        directions.extend(direction for _ in range(record.body.sample_count))
    return tuple(hits), tuple(directions)


def _probabilities(records: tuple[SampleBatchRecord, ...], baseline: bool) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for record in records:
        probability = next(item.confidence for item in record.body.baselines if item.kind is BaselineKind.CONSENSUS) if baseline else record.body.candidate.confidence
        values.extend(Decimal(probability) for _ in range(record.body.sample_count))
    return tuple(values)


def _p95(values: tuple[int, ...]) -> int:
    ordered = sorted(values)
    index = int((Decimal(len(ordered)) * Decimal("0.95")).to_integral_value(rounding=ROUND_CEILING)) - 1
    return ordered[index]


def derive_summary(candidate: CandidateArtifact, value: FrozenEvaluationInput) -> OfflineSummary:
    records = _eligible(value)
    holdout_records = tuple(record for record in value.records if record.body.split == "holdout_window")
    threshold = Decimal(value.config.body.success_threshold)
    candidate_edges = expanded_decimal(records, "candidate")
    consensus_edges = expanded_decimal(records, "consensus")
    gains = expanded_decimal(records, "gain")
    target_records = tuple(record for record in records if record.body.target_error)
    target_gains = expanded_decimal(target_records, "gain")
    non_target_gains = expanded_decimal(tuple(record for record in records if not record.body.target_error), "gain")
    candidate_hits = _expanded_int(records, "candidate_hit", threshold)
    candidate_errors = tuple(1 - hit for hit in candidate_hits)
    baseline_hits = tuple(int(edge >= threshold) for edge in consensus_edges)
    baseline_errors = tuple(1 - hit for hit in baseline_hits)
    baseline_metrics = tuple(BaselineMetric(kind=kind, mean_edge=decimal6(mean(tuple(edge for record in records for edge in (baseline_edge(record, kind),) * record.body.sample_count))), incremental_lift=decimal6(mean(tuple(candidate_edge - baseline for candidate_edge, baseline in zip(candidate_edges, tuple(edge for record in records for edge in (baseline_edge(record, kind),) * record.body.sample_count), strict=True))))) for kind in BaselineKind)
    correlations: list[PerspectiveCorrelation] = []
    candidate_directions = _expanded_int(records, "candidate_direction", threshold)
    for perspective in ExistingPerspective:
        perspective_hits, directions = _perspective_values(records, perspective, threshold)
        correlations.append(PerspectiveCorrelation(perspective=perspective, error_correlation=decimal6(pearson(candidate_errors, tuple(1 - hit for hit in perspective_hits))), verdict_correlation=decimal6(pearson(candidate_directions, directions)), shared_samples=len(candidate_hits)))
    candidate_brier, candidate_ece, overconfident, minimum_bucket = calibration(_probabilities(records, False), candidate_hits)
    baseline_brier, baseline_ece, _, _ = calibration(_probabilities(records, True), baseline_hits)
    misses = sum(baseline_errors)
    recovered = sum(int(base == 0 and hit == 1) for base, hit in zip(baseline_hits, candidate_hits, strict=True))
    eligible_count = sum(record.body.sample_count for record in records)
    holdout_count = sum(record.body.sample_count for record in holdout_records)
    target_count = sum(record.body.sample_count for record in records if record.body.target_error)
    target_holdout_count = sum(record.body.sample_count for record in holdout_records if record.body.target_error)
    na_count = sum(record.body.sample_count for record in holdout_records if record.body.candidate.verdict is Verdict.NA)
    target_na = sum(record.body.sample_count for record in holdout_records if record.body.target_error and record.body.candidate.verdict is Verdict.NA)
    wall_values = tuple(record.body.candidate.wall_ms for record in holdout_records for _ in range(record.body.sample_count))
    identity = candidate.candidate_proposal
    overlap = max(Decimal(str(item.overlap_score)) for item in identity.overlap_matrix)
    non_target_harm = Decimal(sum(int(gain <= Decimal("-0.020000")) for gain in non_target_gains)) / Decimal(len(non_target_gains)) if non_target_gains else Decimal()
    return OfflineSummary(schema_version="v6.offline-evaluation-summary.2", candidate_id=candidate.candidate_id, candidate_version=candidate.candidate_version, hypothesis_id=candidate.hypothesis_id, input_hash=value.input_hash, manifest_hash=value.manifest.manifest_hash, dataset_manifest_id=value.manifest.body.dataset_manifest_id, baselines=baseline_metrics, holdout_eligible_samples=eligible_count, target_error_samples=target_count, kr_samples=sum(record.body.sample_count for record in records if record.body.market == "KR"), us_samples=sum(record.body.sample_count for record in records if record.body.market == "US"), buy_samples=sum(record.body.sample_count for record in records if record.body.candidate.verdict is Verdict.BUY), sell_samples=sum(record.body.sample_count for record in records if record.body.candidate.verdict is Verdict.SELL), hold_samples=sum(record.body.sample_count for record in records if record.body.candidate.verdict is Verdict.HOLD), minimum_pair_correlation_samples=len(candidate_hits), minimum_calibration_bucket_samples=minimum_bucket, holdout_incremental_lift_5=decimal6(mean(gains)), holdout_lift_bootstrap_lower_90=decimal6(bootstrap_lower(gains, value.config.body.bootstrap_iterations, value.config.body.bootstrap_seed + ":holdout")), target_error_lift_5=decimal6(mean(target_gains)), target_error_lift_bootstrap_lower_90=decimal6(bootstrap_lower(target_gains, value.config.body.bootstrap_iterations, value.config.body.bootstrap_seed + ":target")), harm_rate=decimal6(Decimal(sum(int(gain <= Decimal("-0.020000")) for gain in gains)) / Decimal(len(gains))), non_target_harm_rate=decimal6(non_target_harm), baseline_miss_recovery_rate=decimal6(Decimal(recovered) / Decimal(misses)) if misses else "0.000000", correlations=tuple(correlations), max_error_correlation=max(item.error_correlation for item in correlations), max_verdict_correlation=max(item.verdict_correlation for item in correlations), candidate_brier=decimal6(candidate_brier), baseline_brier=decimal6(baseline_brier), candidate_ece=decimal6(candidate_ece), baseline_ece=decimal6(baseline_ece), overconfident_error_bucket_count=overconfident, overall_na_rate=decimal6(Decimal(na_count) / Decimal(holdout_count)), target_error_na_rate=decimal6(Decimal(target_na) / Decimal(target_holdout_count)), missing_required_input_as_hold_count=sum(record.body.sample_count for record in holdout_records if record.body.candidate.missing_required_input and record.body.candidate.verdict is not Verdict.NA), timeout_as_verdict_count=sum(record.body.sample_count for record in holdout_records if record.body.candidate.timed_out and record.body.candidate.verdict is not Verdict.NA), p95_wall_ms_per_ticker=_p95(wall_values), mean_wall_ms_per_ticker=int(mean(tuple(Decimal(item) for item in wall_values))), llm_calls_per_ticker=max(record.body.candidate.llm_calls for record in holdout_records), prompt_tokens_per_ticker=max(record.body.candidate.prompt_tokens for record in holdout_records), extra_fetches_per_ticker=max(record.body.candidate.extra_fetches for record in holdout_records), timeout_rate=decimal6(Decimal(sum(record.body.sample_count for record in holdout_records if record.body.candidate.timed_out)) / Decimal(holdout_count)), ablation_remove_novel_observations_lift_drop=decimal6(mean(expanded_decimal(records, "novel_drop"))), existing_signal_only_overlap=decimal6(overlap), shuffle_candidate_outputs_lift=decimal6(mean(expanded_decimal(records, "shuffle_gain"))), outcome_adapter_available=all(record.body.outcome.adapter_available for record in holdout_records))
