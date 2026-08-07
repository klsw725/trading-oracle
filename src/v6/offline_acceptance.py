from dataclasses import replace
from decimal import Decimal

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash

from .models import JsonBoundary
from .offline_artifact import OfflineArtifactBody, OfflineEvaluationArtifact, build_offline_artifact, offline_body_json
from .offline_evaluator import evaluate_evidence
from .offline_evidence import FrozenEvaluationInput, OfflineFixture, boundary_json, expected_input_hash, sample_ids
from .offline_metrics import derive_hand_metrics
from .offline_models import MutationName, OfflineCode
from .offline_mutations import mutate_evidence, seal_input
from .offline_validation import evidence_failures


def _artifact_rejected(artifact: OfflineEvaluationArtifact) -> bool:
    try:
        _ = OfflineEvaluationArtifact.model_validate(artifact.model_dump(mode="json"))
    except ValidationError:
        return True
    return False


def _fixture_rejected(fixture: OfflineFixture) -> bool:
    try:
        _ = OfflineFixture.model_validate(fixture.model_dump(mode="json"))
    except ValidationError:
        return True
    return False


def _extra_metric_rejected(value: FrozenEvaluationInput) -> bool:
    raw = value.model_dump(mode="json")
    raw["holdout_incremental_lift_5"] = "-1.000000"
    raw["holdout_lift_bootstrap_lower_90"] = "0.999999"
    try:
        _ = FrozenEvaluationInput.model_validate(raw)
    except ValidationError:
        return True
    return False


def verify_offline_fixture(fixture: OfflineFixture) -> JsonValue:
    candidate = fixture.candidate_artifact
    artifact = build_offline_artifact(candidate, fixture.threshold_input, fixture.hand_input)
    metrics = derive_hand_metrics(fixture.hand_input)
    expected = fixture.hand_expected
    summary = artifact.summary
    if summary is None:
        return {"state": "fail", "reason": "threshold_summary_missing"}
    mutation_results = tuple((item.name, evaluate_evidence(candidate, mutate_evidence(fixture.threshold_input, item.name)).decision.code, item.code) for item in fixture.expected_mutations)
    mutation_actual = {name: actual for name, actual, _ in mutation_results}
    hand_checks = {
        "hand_mean_baseline": metrics.mean_baseline_edge == expected.mean_baseline_edge,
        "hand_mean_candidate": metrics.mean_candidate_edge == expected.mean_candidate_edge,
        "hand_incremental_lift": metrics.incremental_lift == expected.incremental_lift,
        "hand_candidate_hits": metrics.candidate_hits == expected.candidate_hits,
        "hand_candidate_errors": metrics.candidate_errors == expected.candidate_errors,
        "hand_brier": metrics.brier == expected.brier,
        "hand_ece": metrics.ece == expected.ece,
        "three_baselines_derived": len(summary.baselines) == 3,
    }
    derived_checks = {
        "threshold_fixture_pass": artifact.terminal_code is OfflineCode.PASS,
        "summary_input_hash_bound": summary.input_hash == fixture.threshold_input.input_hash,
        "manifest_hash_bound": summary.manifest_hash == fixture.threshold_input.manifest.manifest_hash,
        "point_bound_consistent": Decimal(summary.holdout_lift_bootstrap_lower_90) <= Decimal(summary.holdout_incremental_lift_5) and Decimal(summary.target_error_lift_bootstrap_lower_90) <= Decimal(summary.target_error_lift_5),
        "holdout_lift_gate": Decimal(summary.holdout_lift_bootstrap_lower_90) >= Decimal("0.003000"),
        "target_lift_gate": Decimal(summary.target_error_lift_bootstrap_lower_90) >= Decimal("0.007000"),
        "harm_gate": Decimal(summary.harm_rate) <= Decimal("0.200000") and Decimal(summary.non_target_harm_rate) <= Decimal("0.250000"),
        "recovery_gate": Decimal(summary.baseline_miss_recovery_rate) >= Decimal("0.100000"),
        "correlation_gate": Decimal(summary.max_error_correlation) < Decimal("0.800000") and Decimal(summary.max_verdict_correlation) < Decimal("0.900000"),
        "calibration_gate": Decimal(summary.candidate_ece) <= Decimal("0.100000") and Decimal(summary.candidate_brier) - Decimal(summary.baseline_brier) < Decimal("0.020000"),
        "coverage_gate": Decimal(summary.overall_na_rate) <= Decimal("0.150000") and Decimal(summary.target_error_na_rate) <= Decimal("0.200000"),
        "cost_latency_gate": summary.p95_wall_ms_per_ticker <= 3000 and summary.llm_calls_per_ticker == 0 and summary.prompt_tokens_per_ticker == 0 and summary.extra_fetches_per_ticker == 0,
        "ablation_gate": Decimal(summary.ablation_remove_novel_observations_lift_drop) >= Decimal("0.007000") and abs(Decimal(summary.shuffle_candidate_outputs_lift)) <= Decimal("0.003000"),
        "sample_minima_gate": summary.holdout_eligible_samples >= 300 and summary.target_error_samples >= 100 and summary.kr_samples >= 100 and summary.us_samples >= 100,
        "repeat_runs_current_pass": all(run.terminal_code is OfflineCode.PASS for run in fixture.threshold_input.repeated_runs),
        "eligible_counts_exclude_outcomeless": summary.holdout_eligible_samples == 328 and summary.kr_samples == 164 and summary.us_samples == 164 and summary.target_error_samples == 140,
    }
    sample_id_values = tuple(sample_id for record in fixture.threshold_input.records for sample_id in sample_ids(record))
    evidence_checks = {
        "hand_evidence_integrity": not evidence_failures(fixture.hand_input, candidate, 0),
        "threshold_evidence_integrity": not evidence_failures(fixture.threshold_input, candidate, 20),
        "threshold_records_content_addressed": all(record.record_hash == canonical_hash(boundary_json(record.body)) for record in fixture.threshold_input.records),
        "manifest_record_set_bound": fixture.threshold_input.manifest.body.record_hashes == tuple(record.record_hash for record in fixture.threshold_input.records),
        "sample_ids_derived_360": len(sample_id_values) == 360 and len(set(sample_id_values)) == 360,
        "three_baselines_per_record": all(len(record.body.baselines) == 3 and len(record.body.outcome.baseline_edges) == 3 for record in fixture.threshold_input.records),
        "five_perspectives_per_record": all(len(record.body.perspectives) == 5 and len(record.body.outcome.perspective_edges) == 5 for record in fixture.threshold_input.records),
        "cost_records_nonnegative": all(min(record.body.candidate.wall_ms, record.body.candidate.llm_calls, record.body.candidate.prompt_tokens, record.body.candidate.extra_fetches) >= 0 for record in fixture.threshold_input.records),
        "outcome_records_present": all(record.body.outcome.adapter_available for record in fixture.threshold_input.records),
        "ablation_records_present": all(record.body.outcome.candidate_edge is None or record.body.ablation.remove_novel_observations_edge is not None for record in fixture.threshold_input.records),
        "repeat_runs_hash_bound": all(run.input_hash == fixture.threshold_input.input_hash and run.config_hash == fixture.threshold_input.config.config_hash for run in fixture.threshold_input.repeated_runs),
    }
    names = tuple(item.name for item in fixture.expected_mutations)
    mutation_checks = {
        "mutation_corpus_nonempty": bool(names),
        "mutation_corpus_exact": set(names) == set(MutationName) and len(names) == len(MutationName),
        "mutation_corpus_unique": len(names) == len(set(names)),
        "mutation_codes_match": all(actual is expected_code for _, actual, expected_code in mutation_results),
    }
    fake_manifest = fixture.threshold_input.manifest.model_copy(update={"manifest_hash": f"sha256:{'f' * 64}"})
    fake_shell = fixture.threshold_input.model_copy(update={"manifest": fake_manifest})
    fake_equal_hashes = fake_shell.model_copy(update={"input_hash": expected_input_hash(fake_shell)})
    wrong_repeats = seal_input(fixture.threshold_input, fixture.threshold_input.records, OfflineCode.PASS, tuple(OfflineCode.NO_LIFT for _ in fixture.threshold_input.repeated_runs))
    first = fixture.threshold_input.records[0]
    negative_candidate = first.body.candidate.model_copy(update={"wall_ms": -1, "llm_calls": -1})
    negative_body = first.body.model_copy(update={"candidate": negative_candidate})
    negative_record = first.model_copy(update={"body": negative_body, "record_hash": canonical_hash(boundary_json(negative_body))})
    negative_input = seal_input(fixture.threshold_input, (negative_record, *fixture.threshold_input.records[1:]), OfflineCode.MALFORMED)
    duplicate_body = fixture.threshold_input.records[1].body.model_copy(update={"sample_id_prefix": fixture.threshold_input.records[0].body.sample_id_prefix})
    duplicate_record = fixture.threshold_input.records[1].model_copy(update={"body": duplicate_body, "record_hash": canonical_hash(boundary_json(duplicate_body))})
    duplicate_input = seal_input(fixture.threshold_input, (fixture.threshold_input.records[0], duplicate_record, *fixture.threshold_input.records[2:]), OfflineCode.MALFORMED)
    forged_metrics = replace(artifact.hand_metrics, brier="0.999999")
    forged_body = OfflineArtifactBody.model_validate({**artifact.model_dump(mode="json", exclude={"artifact_hash"}), "hand_metrics": forged_metrics})
    forged_artifact = artifact.model_copy(update={"hand_metrics": forged_metrics, "artifact_hash": canonical_hash(offline_body_json(forged_body))})
    forged_summary = summary.model_copy(update={"holdout_incremental_lift_5": "0.999999"})
    summary_body = OfflineArtifactBody.model_validate({**artifact.model_dump(mode="json", exclude={"artifact_hash"}), "summary": forged_summary})
    summary_artifact = artifact.model_copy(update={"summary": forged_summary, "artifact_hash": canonical_hash(offline_body_json(summary_body))})
    empty_fixture = fixture.model_copy(update={"expected_mutations": ()})
    bypass_checks = {
        "arbitrary_equal_manifest_hashes_rejected": evaluate_evidence(candidate, fake_equal_hashes).decision.code is OfflineCode.MALFORMED,
        "empty_mutation_corpus_rejected": _fixture_rejected(empty_fixture),
        "wrong_repeated_decisions_rejected": evaluate_evidence(candidate, wrong_repeats).decision.code is OfflineCode.FLAKY,
        "negative_resources_rejected": evaluate_evidence(candidate, negative_input).decision.code is OfflineCode.MALFORMED,
        "caller_point_bound_fields_rejected": _extra_metric_rejected(fixture.threshold_input),
        "rehashed_hand_metrics_forgery_rejected": _artifact_rejected(forged_artifact),
        "rehashed_summary_forgery_rejected": _artifact_rejected(summary_artifact),
        "duplicate_samples_rejected": evaluate_evidence(candidate, duplicate_input).decision.code is OfflineCode.MALFORMED,
        "all_train_window_inconclusive": mutation_actual[MutationName.ALL_TRAIN] is OfflineCode.INSUFFICIENT,
        "over_budget_resource_malformed": mutation_actual[MutationName.OVER_BUDGET] is OfflineCode.MALFORMED,
        "zero_threshold_repeats_malformed": mutation_actual[MutationName.ZERO_REPEATS] is OfflineCode.MALFORMED,
        "missing_all_outcomes_inconclusive": mutation_actual[MutationName.MISSING_OUTCOMES] is OfflineCode.MISSING_ADAPTER,
        "missing_target_error_cohort_inconclusive": mutation_actual[MutationName.MISSING_TARGET] is OfflineCode.INSUFFICIENT,
    }
    artifact_checks = {
        "artifact_roundtrip": OfflineEvaluationArtifact.model_validate(artifact.model_dump(mode="json")) == artifact,
        "artifact_hash_tamper": _artifact_rejected(artifact.model_copy(update={"artifact_hash": f"sha256:{'0' * 64}"})),
        "input_hash_pointer_tamper": _artifact_rejected(artifact.model_copy(update={"evaluation_input_hash": f"sha256:{'0' * 64}"})),
        "lineage_tamper": _artifact_rejected(artifact.model_copy(update={"hypothesis_id": "hyp_v6_other_candidate_001"})),
    }
    checks = {**hand_checks, **derived_checks, **evidence_checks, **mutation_checks, **bypass_checks, **artifact_checks}
    hand_json = {"mean_baseline_edge": metrics.mean_baseline_edge, "mean_candidate_edge": metrics.mean_candidate_edge, "incremental_lift": metrics.incremental_lift, "closest_incremental_lift": metrics.closest_incremental_lift, "equal_weight_incremental_lift": metrics.equal_weight_incremental_lift, "candidate_hits": metrics.candidate_hits, "candidate_errors": metrics.candidate_errors, "harm_rate": metrics.harm_rate, "baseline_miss_recovery_rate": metrics.baseline_miss_recovery_rate, "error_correlation": metrics.error_correlation, "verdict_correlation": metrics.verdict_correlation, "brier": metrics.brier, "ece": metrics.ece}
    result = {"state": "pass" if all(checks.values()) else "fail", "schema_version": fixture.schema_version, "pass_count": sum(int(value) for value in checks.values()), "total": len(checks), "hand_metrics": hand_json, "summary": JsonBoundary.model_validate(summary.model_dump(mode="json")).root, "terminal_code": artifact.terminal_code.value, "artifact_hash": artifact.artifact_hash, "checks": checks, "mutations": [{"name": name.value, "actual": actual.value, "expected": expected_code.value} for name, actual, expected_code in mutation_results]}
    return JsonBoundary.model_validate(result).root
