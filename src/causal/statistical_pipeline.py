from __future__ import annotations

from dataclasses import dataclass

from src.v4.models import JsonValue, canonical_json

from .statistical_engine import (
    PairProblem,
    PreparedPair,
    correction,
    prepare_pair,
    split_evidence,
    test_pair,
    window_policy_evidence,
)
from .statistical_hashes import (
    input_fingerprint,
    result_fingerprint,
    run_config_hash,
    split_policy_hash,
    source_node_artifact_hash,
    window_policy_hash,
)
from .statistical_models import VerificationInput
from .statistical_output_models import PAIR_RESULT_ADAPTER
from .statistical_results import FinalPair, PolicyEvidence, mutation, problem_result, tested_result
from .statistical_types import Status, decimal_text


@dataclass(frozen=True, slots=True)
class VerificationBuildResult:
    artifact: JsonValue


def _audit_problem(build: VerificationInput, prepared: tuple[PreparedPair, ...], fingerprint: str, policy: PolicyEvidence) -> tuple[Status, str] | None:
    locks = (
        (build.audit.locked_input_fingerprint, fingerprint, "input_fingerprint_changed_after_result_inspection"),
        (build.audit.locked_run_config_hash, policy.run_config_hash, "run_config_changed_after_result_inspection"),
        (build.audit.locked_correction_scope_hash, policy.correction_scope_hash, "correction_scope_changed_after_result_inspection"),
        (build.audit.locked_split_policy_hash, policy.split_policy_hash, "split_policy_changed_after_result_inspection"),
        (build.audit.locked_window_policy_hash, policy.window_policy_hash, "window_policy_changed_after_result_inspection"),
    )
    for locked, observed, reason in locks:
        if locked is not None and locked != observed:
            return Status.P_HACKING, reason
    if prepared:
        holdout_start = min(item.split.holdout.timestamps[0] for item in prepared)
        if any(timestamp >= holdout_start for timestamp in build.audit.train_decision_timestamps):
            return Status.LEAKAGE, "holdout_timestamp_used_in_train_decision"
    return None


def _as_flaky(final: FinalPair, build: VerificationInput, reason: str, prior_hash: str | None) -> FinalPair:
    if not isinstance(final.result, dict):
        return final
    current_hash = result_fingerprint(final.result)
    result: dict[str, JsonValue] = {
        **final.result,
        "verification_status": Status.FLAKY.value,
        "confidence": "0.000000",
        "rejection_reason": reason,
    }
    evidence: JsonValue = {"prior_result_fingerprint": prior_hash, "current_result_fingerprint": current_hash}
    record = mutation(Status.FLAKY, final.context, reason, evidence, build)
    return FinalPair(result, record, Status.FLAKY, final.context)


def _apply_flaky_audit(finals: list[FinalPair], build: VerificationInput, fingerprint: str) -> list[FinalPair]:
    priors = tuple(item for item in build.audit.prior_pair_results if item.input_fingerprint == fingerprint)
    if not priors:
        return finals
    prior_by_id = {item.pair_id: item for item in priors}
    current_ids = {item.context.pair_id for item in finals}
    if set(prior_by_id) != current_ids:
        return [_as_flaky(item, build, "same_input_changed_pair_ids", None) for item in finals]
    audited: list[FinalPair] = []
    for final in finals:
        prior = prior_by_id[final.context.pair_id]
        current_hash = result_fingerprint(final.result)
        audited.append(final if prior.result_fingerprint == current_hash else _as_flaky(final, build, "same_input_changed_terminal_evidence", prior.result_fingerprint))
    return audited


def build_verification_artifact(build: VerificationInput) -> VerificationBuildResult:
    fingerprint = input_fingerprint(build)
    config_hash = run_config_hash(build)
    triples = sorted(build.source_node_artifact.triples, key=lambda item: (item.subject_node_id, item.object_node_id, item.relation))
    outcomes = tuple(prepare_pair(build, triple, fingerprint) for triple in triples)
    prepared = tuple(item for item in outcomes if isinstance(item, PreparedPair))
    problems = tuple(item for item in outcomes if isinstance(item, PairProblem))
    hypotheses, corrected, scope_hash = correction(prepared, build.config.alpha)
    split_seed: list[JsonValue] = [split_evidence(item) for item in prepared]
    window_seed: list[JsonValue] = [window_policy_evidence(item, build) for item in prepared]
    split_hash = split_policy_hash(build, split_seed)
    window_hash = window_policy_hash(build, window_seed)
    policy = PolicyEvidence(config_hash, scope_hash, split_hash, window_hash, hypotheses, corrected)
    audited = _audit_problem(build, prepared, fingerprint, policy)
    finals: list[FinalPair] = []
    for problem in problems:
        if audited is not None and problem.status is Status.INCONCLUSIVE:
            status, reason = audited
            finals.append(problem_result(PairProblem(problem.context, status, reason), build, policy))
        else:
            finals.append(problem_result(problem, build, policy))
    for item in prepared:
        if audited is not None:
            status, reason = audited
            finals.append(problem_result(PairProblem(item.context, status, reason), build, policy))
            continue
        tested = test_pair(item, build)
        final = problem_result(tested, build, policy) if isinstance(tested, PairProblem) else tested_result(item, tested, build, policy)
        finals.append(final)
    finals = _apply_flaky_audit(finals, build, fingerprint)
    finals.sort(key=lambda item: canonical_json(item.result))
    for final in finals:
        _ = PAIR_RESULT_ADAPTER.validate_python(final.result)
    mutations: list[JsonValue] = sorted([item.mutation for item in finals if item.mutation is not None], key=canonical_json)
    statuses = [item.status for item in finals]
    metadata: JsonValue = {
        "alpha": decimal_text(build.config.alpha, 6),
        "tested_hypotheses": hypotheses,
        "corrected_alpha": decimal_text(corrected, 12),
        "correction_method": "bonferroni",
        "eligible_pairs": len(prepared),
        "verified_stable": statuses.count(Status.VERIFIED),
        "rejected": sum(status.value.startswith("rejected_") for status in statuses),
        "inconclusive": statuses.count(Status.INCONCLUSIVE),
    }
    artifact: dict[str, JsonValue] = {
        "schema_version": "causal-statistical-verification.1",
        "source_node_schema_version": "causal-node-canonicalization.1",
        "source_mapping_schema_version": "causal-series-mapping.1",
        "source_node_artifact_hash": source_node_artifact_hash(build),
        "verification_policy_version": "statistical-verifier.1",
        "generated_at": build.generated_at.isoformat(),
        "verification_cutoff": build.verification_cutoff.isoformat(),
        "input_fingerprint": fingerprint,
        "run_config_hash": config_hash,
        "correction_scope_hash": scope_hash,
        "split_policy_hash": split_hash,
        "window_policy_hash": window_hash,
        "metadata": metadata,
        "pair_results": [item.result for item in finals],
        "verification_mutations": mutations,
        "qa": {
            "read_checks": ["canonical_ids", "approved_non_expired_mappings", "mapping_hash_recomputed", "explicit_series_observations"],
            "json_checks": ["strict_full_pair_result", "numeric_ranges", "statistical_lead_only"],
            "mutation_checks": ["in_sample_only", "p_hacking", "leakage", "flaky", "malformed"],
        },
    }
    return VerificationBuildResult(artifact)
