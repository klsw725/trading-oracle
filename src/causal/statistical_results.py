from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.v4.models import JsonValue

from .statistical_engine import PairProblem, PreparedPair, split_evidence
from .statistical_math import WindowEvidence
from .statistical_models import ContractValueError, VerificationInput
from .statistical_types import PairContext, Status, TestedPair, decimal_text, evidence_json


@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    run_config_hash: str
    correction_scope_hash: str
    split_policy_hash: str
    window_policy_hash: str
    tested_hypotheses: int
    corrected_alpha: Decimal


@dataclass(frozen=True, slots=True)
class FinalPair:
    result: JsonValue
    mutation: JsonValue | None
    status: Status
    context: PairContext


def _base(context: PairContext, policy: PolicyEvidence) -> dict[str, JsonValue]:
    return {
        "pair_id": context.pair_id,
        "subject_node_id": context.subject_node_id,
        "object_node_id": context.object_node_id,
        "subject_label": context.subject_label,
        "object_label": context.object_label,
        "relation": context.relation,
        "subject_series_id": context.subject_series_id,
        "object_series_id": context.object_series_id,
        "subject_mapping_hash": context.subject_mapping_hash,
        "object_mapping_hash": context.object_mapping_hash,
        "mapping_expires_at": context.mapping_expires_at,
        "verification_expires_at": context.verification_expires_at,
        "verification_cutoff": context.verification_cutoff,
        "declared_lag_grid": list(context.declared_lag_grid),
        "input_fingerprint": context.input_fingerprint,
        "run_config_hash": policy.run_config_hash,
        "correction_scope_hash": policy.correction_scope_hash,
        "split_policy_hash": policy.split_policy_hash,
        "window_policy_hash": policy.window_policy_hash,
        "method": "granger_predictive_lead",
        "claim_label": "statistical_lead_evidence",
    }


def mutation(status: Status, context: PairContext, reason: str, evidence: JsonValue, build: VerificationInput) -> JsonValue | None:
    names = {
        Status.INCONCLUSIVE: "mark_inconclusive",
        Status.IN_SAMPLE: "reject_in_sample_only",
        Status.P_HACKING: "reject_p_hacking",
        Status.LEAKAGE: "reject_leakage",
        Status.FLAKY: "reject_flaky",
        Status.MALFORMED: "reject_malformed",
    }
    name = names.get(status)
    if name is None:
        return None
    return {
        "mutation": name,
        "pair_id": context.pair_id,
        "from_status": "train_pass" if status is Status.IN_SAMPLE else "candidate",
        "to_status": status.value,
        "reason": reason,
        "evidence": evidence,
        "mutated_at": build.generated_at.isoformat(),
        "mutated_by": "statistical-verifier.1",
    }


def problem_result(problem: PairProblem, build: VerificationInput, policy: PolicyEvidence) -> FinalPair:
    result: dict[str, JsonValue] = {
        **_base(problem.context, policy),
        "verification_status": problem.status.value,
        "selected_lag": None,
        "train": None,
        "holdout": None,
        "stationarity": None,
        "train_lag_table": [],
        "multiple_testing": None,
        "split": None,
        "stability": None,
        "confidence": "0.000000",
        "rejection_reason": problem.reason,
    }
    record = mutation(problem.status, problem.context, problem.reason, {"reason": problem.reason}, build)
    return FinalPair(result, record, problem.status, problem.context)


def _status(tested: TestedPair, corrected: Decimal, build: VerificationInput) -> tuple[Status, str | None]:
    threshold = float(corrected)
    if tested.selected.p_value >= threshold:
        return Status.MULTIPLE, "train_p_value_above_corrected_alpha"
    if not tested.selected.direction_match:
        return Status.DIRECTION, "train_direction_mismatch"
    if tested.holdout.p_value >= threshold:
        return Status.IN_SAMPLE, "holdout_p_value_above_corrected_alpha"
    if not tested.holdout.direction_match:
        return Status.IN_SAMPLE, "holdout_direction_mismatch"
    if tested.inconclusive_windows > build.config.max_inconclusive_windows:
        return Status.INCONCLUSIVE, "too_many_inconclusive_windows"
    if tested.structural_break:
        return Status.BREAK, "structural_break_threshold_failed"
    return Status.VERIFIED, None


def _window_json(window: WindowEvidence) -> JsonValue:
    return {
        "window_id": window.window_id,
        "rows": window.rows,
        "p_value": decimal_text(window.p_value, 6),
        "direction_match": window.direction_match,
        "mean_shift": decimal_text(window.mean_shift, 6),
        "variance_ratio": decimal_text(window.variance_ratio, 6),
        "status": window.status,
    }


def tested_result(prepared: PreparedPair, tested: TestedPair, build: VerificationInput, policy: PolicyEvidence) -> FinalPair:
    status, reason = _status(tested, policy.corrected_alpha, build)
    confidence = max(0.0, 1.0 - max(tested.selected.p_value, tested.holdout.p_value) / float(policy.corrected_alpha))
    train_json = evidence_json(tested.selected)
    holdout_json = evidence_json(tested.holdout)
    split = split_evidence(prepared)
    if not isinstance(split, dict):
        raise ContractValueError("split", "evidence must be an object")
    windows: list[JsonValue] = [_window_json(item) for item in tested.windows]
    rolling = tuple(item for item in tested.windows if item.window_id.startswith("rolling_"))
    checked = len(rolling)
    passed = sum(item.status == "pass" for item in rolling)
    result: dict[str, JsonValue] = {
        **_base(tested.context, policy),
        "verification_status": status.value,
        "selected_lag": tested.selected.lag,
        "train": train_json,
        "holdout": holdout_json,
        "stationarity": {
            "subject_diff_order": tested.subject_diff_order,
            "object_diff_order": tested.object_diff_order,
            "subject_adf_p_value": decimal_text(tested.subject_adf_p, 6),
            "object_adf_p_value": decimal_text(tested.object_adf_p, 6),
            "stationarity_alpha": decimal_text(build.config.stationarity_alpha, 6),
        },
        "train_lag_table": [{"lag": item.lag, **evidence_json(item)} for item in tested.lag_table],
        "multiple_testing": {
            "alpha": decimal_text(build.config.alpha, 6),
            "tested_hypotheses": policy.tested_hypotheses,
            "corrected_alpha": decimal_text(policy.corrected_alpha, 12),
            "correction_method": "bonferroni",
            "correction_scope_hash": policy.correction_scope_hash,
        },
        "split": {"policy": build.config.split_policy, **split},
        "stability": {
            "structural_break_check": "fail" if tested.structural_break else "pass",
            "predeclared_windows": windows,
            "rolling_windows_checked": checked,
            "rolling_windows_passed": passed,
            "inconclusive_windows": tested.inconclusive_windows,
            "oos_stability": "pass" if status is Status.VERIFIED else "fail",
        },
        "confidence": decimal_text(confidence, 6),
        "rejection_reason": reason,
    }
    evidence: JsonValue = {
        "train_p_value": train_json["p_value"],
        "holdout_p_value": holdout_json["p_value"],
        "corrected_alpha": decimal_text(policy.corrected_alpha, 12),
        "selected_lag": tested.selected.lag,
    }
    return FinalPair(result, mutation(status, tested.context, reason or status.value, evidence, build), status, tested.context)
