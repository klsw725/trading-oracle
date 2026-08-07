from decimal import Decimal
from typing import Final

from .candidate_artifact import CandidateArtifact
from .models import ExistingPerspective, Verdict
from .offline_evidence import FrozenEvaluationInput, expected_config_hash, expected_input_hash, expected_manifest_hash, expected_record_hash, sample_ids
from .offline_models import BaselineKind


_BASELINES: Final = frozenset(BaselineKind)
_PERSPECTIVES: Final = frozenset(ExistingPerspective)
_LEAKAGE_FIELDS: Final = frozenset({"exit_close", "future_return", "post_cutoff_article"})


def evidence_failures(value: FrozenEvaluationInput, candidate: CandidateArtifact, required_repeat_runs: int) -> tuple[str, ...]:
    failures: list[str] = []
    records = value.records
    if value.candidate_artifact_hash != candidate.artifact_hash:
        failures.append("candidate_artifact_hash_mismatch")
    if value.config.config_hash != expected_config_hash(value.config):
        failures.append("config_hash_mismatch")
    if any(record.record_hash != expected_record_hash(record) for record in records):
        failures.append("sample_record_hash_mismatch")
    record_hashes = tuple(record.record_hash for record in records)
    if value.manifest.body.record_hashes != record_hashes or len(set(record_hashes)) != len(record_hashes):
        failures.append("manifest_record_set_mismatch")
    if value.manifest.manifest_hash != expected_manifest_hash(value.manifest):
        failures.append("manifest_hash_mismatch")
    if value.input_hash != expected_input_hash(value):
        failures.append("input_hash_mismatch")
    identifiers = tuple(sample_id for record in records for sample_id in sample_ids(record))
    if len(identifiers) != len(set(identifiers)):
        failures.append("duplicate_sample_id")
    batch_ids = tuple(record.body.batch_id for record in records)
    if len(batch_ids) != len(set(batch_ids)):
        failures.append("duplicate_batch_id")
    source_identities = tuple((record.body.ticker_prefix, record.body.emitted_at, record.body.source_hash_seed) for record in records)
    if len(source_identities) != len(set(source_identities)):
        failures.append("duplicate_source_identity")
    if value.manifest.body.embargo_sessions < 20:
        failures.append("embargo_too_short")
    for record in records:
        body = record.body
        baseline_names = tuple(item.kind for item in body.baselines)
        baseline_edges = tuple(item.kind for item in body.outcome.baseline_edges)
        perspective_names = tuple(item.perspective for item in body.perspectives)
        perspective_edges = tuple(item.perspective for item in body.outcome.perspective_edges)
        if frozenset(baseline_names) != _BASELINES or len(set(baseline_names)) != 3 or frozenset(baseline_edges) != _BASELINES or len(set(baseline_edges)) != 3:
            failures.append("incomplete_baseline_record")
        if frozenset(perspective_names) != _PERSPECTIVES or len(set(perspective_names)) != 5 or frozenset(perspective_edges) != _PERSPECTIVES or len(set(perspective_edges)) != 5:
            failures.append("incomplete_perspective_record")
        if body.emitted_at > body.decision_input_cutoff or body.feature_generated_at > body.decision_input_cutoff or body.decision_input_cutoff > value.manifest.body.feature_cutoff or body.decision_input_cutoff >= body.outcome_cutoff:
            failures.append("stale_or_leaking_timestamp")
        if _LEAKAGE_FIELDS.intersection(body.feature_fields):
            failures.append("leakage_feature")
        candidate_output = body.candidate
        resources = (candidate_output.wall_ms, candidate_output.llm_calls, candidate_output.prompt_tokens, candidate_output.extra_fetches, body.sample_count)
        if any(resource < 0 for resource in resources):
            failures.append("negative_resource")
        if candidate_output.missing_required_input or candidate_output.timed_out:
            if candidate_output.verdict is not Verdict.NA:
                failures.append("na_or_timeout_disguised")
        match candidate_output.verdict:  # noqa: MATCH_OK - every Verdict member is explicit
            case Verdict.NA:
                if candidate_output.confidence != "0.000000" or candidate_output.verdict_direction != 0 or body.outcome.candidate_edge is not None:
                    failures.append("malformed_na")
            case Verdict.BUY | Verdict.SELL | Verdict.HOLD:
                if body.outcome.adapter_available and (body.outcome.candidate_edge is None or body.ablation.remove_novel_observations_edge is None or body.ablation.existing_signal_only_edge is None or body.ablation.shuffled_candidate_edge is None):
                    failures.append("missing_outcome_or_ablation")
    budget = candidate.candidate_proposal.budget
    wall_values = sorted(record.body.candidate.wall_ms for record in records for _ in range(record.body.sample_count))
    if wall_values:
        p95 = wall_values[(95 * len(wall_values) + 99) // 100 - 1]
        if p95 > min(budget.max_wall_ms_per_ticker, 6000):
            failures.append("p95_budget_exceeded")
    if any(record.body.candidate.llm_calls > budget.max_llm_calls_per_ticker or record.body.candidate.prompt_tokens > budget.max_prompt_tokens_per_ticker or record.body.candidate.extra_fetches > budget.max_extra_fetches_per_ticker for record in records):
        failures.append("candidate_budget_exceeded")
    total_samples = sum(record.body.sample_count for record in records)
    timed_out = sum(record.body.sample_count for record in records if record.body.candidate.timed_out)
    if total_samples and Decimal(timed_out) / Decimal(total_samples) > Decimal("0.020000"):
        failures.append("timeout_rate_exceeded")
    expected_runs = value.config.body.expected_repeat_runs
    if expected_runs != required_repeat_runs:
        failures.append("required_repeat_count_mismatch")
    if len(value.repeated_runs) != expected_runs or tuple(run.run_index for run in value.repeated_runs) != tuple(range(1, expected_runs + 1)):
        failures.append("repeat_run_set_mismatch")
    if any(run.input_hash != value.input_hash or run.config_hash != value.config.config_hash for run in value.repeated_runs):
        failures.append("repeat_run_binding_mismatch")
    if Decimal(value.config.body.holdout_lift_lower_minimum) > Decimal(value.config.body.target_lift_lower_minimum):
        failures.append("threshold_order_invalid")
    return tuple(dict.fromkeys(failures))
