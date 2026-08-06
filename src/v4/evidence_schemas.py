from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
import re
from typing import ClassVar, Final

from pydantic import ConfigDict, RootModel, ValidationError

from src.v4.evidence import ArtifactType, EvidenceReason, EvidenceReasonCode
from src.v4.evidence_validation import ProvenanceExpectation, ReviewSemanticRequest, SemanticAssessment
from src.v4.models import GateState, JsonValue


_HASH: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TRUE_CHECKS: Final[dict[ArtifactType, tuple[str, ...]]] = {
    ArtifactType.MEASUREMENT_REPORT: ("entry_session_valid", "exit_session_valid", "stale_latest_close_rejected", "corporate_action_provenance"),
    ArtifactType.MEASUREMENT_FIXTURE_RESULT: ("entry_session_valid", "exit_session_valid", "stale_latest_close_rejected", "corporate_action_provenance", "mutation_failed"),
    ArtifactType.SNAPSHOT_MANIFEST: ("schema_valid", "hash_match", "redaction_before_hash", "freshness_visible", "parser_version_present"),
    ArtifactType.SNAPSHOT_SCHEMA_VALIDATION: ("schema_valid", "required_fields_present", "parser_version_present"),
    ArtifactType.SNAPSHOT_HASH_REPORT: ("hash_match", "redaction_before_hash", "section_hashes_match"),
    ArtifactType.LEGACY_COVERAGE_REPORT: ("legacy_audit_only", "source_immutable", "coverage_complete"),
    ArtifactType.INVALID_LEGACY_REPORT: ("legacy_audit_only", "source_immutable", "invalid_marking_present"),
    ArtifactType.LEGACY_SOURCE_INVENTORY: ("legacy_audit_only", "source_immutable", "inventory_complete"),
    ArtifactType.MARKET_CONTEXT_REPORT: ("context_mapping_valid", "benchmark_separated", "fx_provenance", "regime_source_valid"),
    ArtifactType.BLOCKED_DEGRADED_FIELD_REPORT: ("blocked_fields_valid", "degraded_fields_explicit", "market_contamination_rejected"),
    ArtifactType.ATTRIBUTION_LEDGER_REPORT: ("five_action_denominator", "ledger_hash_valid", "rejected_preserved"),
    ArtifactType.DENOMINATOR_REPORT: ("five_action_denominator", "rejected_preserved", "blocked_preserved"),
    ArtifactType.LEDGER_HASH_CHAIN_REPORT: ("ledger_hash_valid", "append_only", "correction_chain_valid"),
    ArtifactType.REPLAY_REPORT: ("modes_separated", "full_workflow", "stale_state_rejected", "clean_worktree"),
    ArtifactType.CHECKPOINT_REPORT: ("checkpoint_valid", "same_input_hash", "same_idempotency_key"),
    ArtifactType.RESUME_REPORT: ("resume_idempotent", "same_input_hash", "same_idempotency_key", "no_duplicate_side_effect"),
    ArtifactType.CALIBRATION_REPORT: ("numeric_confidence", "labels_separated", "cohort_separated", "metrics_recomputed"),
    ArtifactType.CALIBRATION_FIXTURE_RESULT: ("numeric_confidence", "labels_separated", "cohort_separated", "metrics_recomputed", "mutation_failed"),
    ArtifactType.PROMOTION_NOOP_REPORT: ("noop_applied", "weights_unchanged", "legacy_excluded"),
    ArtifactType.REVIEW_MATRIX: ("manual_read", "deterministic_parser", "fixture_mutation", "independent_review", "resume_review"),
    ArtifactType.RELEASE_MANIFEST: ("manifest_complete", "hashes_match", "reviews_complete"),
    ArtifactType.GATE_DECISION_REPORT: ("manifest_referenced", "v4_only", "precedence_applied"),
}
_FALSE_CHECKS: Final[dict[ArtifactType, tuple[str, ...]]] = {
    ArtifactType.LEGACY_COVERAGE_REPORT: ("native_v4_eligible", "canonical_metric_eligible", "calibration_eligible"),
    ArtifactType.INVALID_LEGACY_REPORT: ("native_v4_eligible", "canonical_metric_eligible", "calibration_eligible"),
    ArtifactType.LEGACY_SOURCE_INVENTORY: ("native_v4_eligible", "canonical_metric_eligible", "calibration_eligible"),
    ArtifactType.ATTRIBUTION_LEDGER_REPORT: ("hold_has_order",),
    ArtifactType.CALIBRATION_REPORT: ("hold_trade_pnl", "legacy_included"),
    ArtifactType.CALIBRATION_FIXTURE_RESULT: ("hold_trade_pnl", "legacy_included"),
}
_MATCH_FIELDS: Final[dict[ArtifactType, tuple[tuple[str, str], ...]]] = {
    ArtifactType.MEASUREMENT_REPORT: (("expected_gross_benchmark_excess_return", "actual_gross_benchmark_excess_return"),),
    ArtifactType.MEASUREMENT_FIXTURE_RESULT: (("expected_gross_benchmark_excess_return", "actual_gross_benchmark_excess_return"),),
    ArtifactType.SNAPSHOT_MANIFEST: (("expected_snapshot_hash", "actual_snapshot_hash"), ("expected_sections", "actual_sections")),
    ArtifactType.SNAPSHOT_SCHEMA_VALIDATION: (("expected_schema_fields", "actual_schema_fields"),),
    ArtifactType.SNAPSHOT_HASH_REPORT: (("expected_content_hash", "actual_content_hash"),),
    ArtifactType.LEGACY_COVERAGE_REPORT: (("expected_source_hashes", "actual_source_hashes"),),
    ArtifactType.INVALID_LEGACY_REPORT: (("expected_source_hash", "actual_source_hash"),),
    ArtifactType.LEGACY_SOURCE_INVENTORY: (("expected_source_hashes", "actual_source_hashes"),),
    ArtifactType.MARKET_CONTEXT_REPORT: (("expected_market_mapping", "actual_market_mapping"),),
    ArtifactType.BLOCKED_DEGRADED_FIELD_REPORT: (("expected_blocked_fields", "actual_blocked_fields"),),
    ArtifactType.ATTRIBUTION_LEDGER_REPORT: (("expected_actions", "actual_actions"), ("expected_tail_hash", "actual_tail_hash")),
    ArtifactType.DENOMINATOR_REPORT: (("expected_actions", "actual_actions"),),
    ArtifactType.LEDGER_HASH_CHAIN_REPORT: (("expected_tail_hash", "actual_tail_hash"),),
    ArtifactType.REPLAY_REPORT: (("expected_modes", "actual_modes"),),
    ArtifactType.CHECKPOINT_REPORT: (("expected_input_hash", "actual_input_hash"),),
    ArtifactType.RESUME_REPORT: (("expected_output_hash", "actual_output_hash"),),
    ArtifactType.CALIBRATION_REPORT: (("expected_brier", "actual_brier"), ("expected_ece", "actual_ece")),
    ArtifactType.CALIBRATION_FIXTURE_RESULT: (("expected_brier", "actual_brier"), ("expected_ece", "actual_ece")),
    ArtifactType.PROMOTION_NOOP_REPORT: (("expected_weights_hash", "actual_weights_hash"),),
    ArtifactType.REVIEW_MATRIX: (("expected_lanes", "actual_lanes"),),
    ArtifactType.RELEASE_MANIFEST: (("expected_artifact_set_hash", "actual_artifact_set_hash"),),
    ArtifactType.GATE_DECISION_REPORT: (("expected_manifest_hash", "actual_manifest_hash"),),
}
_ACTIONS: Final[list[JsonValue]] = ["BUY", "SELL", "HOLD", "BLOCKED", "CANDIDATE_REJECTED"]
_REPLAY_MODES: Final[list[JsonValue]] = ["verbatim", "outcome", "recompute"]
_REVIEW_LANES: Final[list[JsonValue]] = ["manual_read", "deterministic_parser", "fixture_mutation", "independent_review", "resume_review"]


@unique
class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    INCONCLUSIVE = "inconclusive"


@unique
class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    code: str
    severity: FindingSeverity
    detail: str


@dataclass(frozen=True, slots=True)
class SubstantiveReviewEvidence:
    observed_sections: tuple[str, ...]
    findings: tuple[ReviewFinding, ...]
    no_findings_rationale: str | None
    decision: ReviewDecision
    review_scope: str | None
    constraints: tuple[str, ...]


class _JsonDocument(RootModel[JsonValue]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


@dataclass(frozen=True, slots=True)
class EvidenceSchemas:
    def artifact_state(self, artifact_type: ArtifactType, body: bytes, provenance: ProvenanceExpectation) -> SemanticAssessment:
        return derive_artifact_state(artifact_type, body, provenance)

    def review_state(self, request: ReviewSemanticRequest) -> SemanticAssessment:
        return derive_review_state(request)


def derive_artifact_state(artifact_type: ArtifactType, body: bytes, provenance: ProvenanceExpectation) -> SemanticAssessment:
    root, reasons = _parse_envelope(body, artifact_type.value, provenance)
    checks = _mapping(root.get("checks"))
    for field in _TRUE_CHECKS[artifact_type]:
        if checks.get(field) is not True:
            reasons.append(EvidenceReason(EvidenceReasonCode.SEMANTIC_FAILURE, f"{artifact_type.value}.{field}"))
    for field in _FALSE_CHECKS.get(artifact_type, ()):
        if checks.get(field) is not False:
            code = EvidenceReasonCode.LEGACY_PROMOTED_TO_NATIVE if field == "native_v4_eligible" else EvidenceReasonCode.SEMANTIC_FAILURE
            reasons.append(EvidenceReason(code, f"{artifact_type.value}.{field}"))
    for expected_field, actual_field in _MATCH_FIELDS[artifact_type]:
        expected = checks.get(expected_field)
        actual = checks.get(actual_field)
        if expected is None or expected != actual:
            reasons.append(EvidenceReason(EvidenceReasonCode.SEMANTIC_FAILURE, f"{artifact_type.value}.{actual_field}_mismatch"))
        if actual_field.endswith("hash") and (not isinstance(actual, str) or not _HASH.fullmatch(actual)):
            reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_HASH, f"{artifact_type.value}.{actual_field}"))
    if artifact_type in {ArtifactType.ATTRIBUTION_LEDGER_REPORT, ArtifactType.DENOMINATOR_REPORT} and checks.get("actual_actions") != _ACTIONS:
        reasons.append(EvidenceReason(EvidenceReasonCode.SEMANTIC_FAILURE, "attribution.action_taxonomy"))
    if artifact_type is ArtifactType.REPLAY_REPORT and checks.get("actual_modes") != _REPLAY_MODES:
        reasons.append(EvidenceReason(EvidenceReasonCode.SEMANTIC_FAILURE, "replay.mode_taxonomy"))
    if artifact_type is ArtifactType.REVIEW_MATRIX and checks.get("actual_lanes") != _REVIEW_LANES:
        reasons.append(EvidenceReason(EvidenceReasonCode.MISSING_REVIEW_LANE, "review_matrix"))
    complete = root.get("complete")
    if complete is not True and complete is not False:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "complete must be boolean"))
    state = GateState.FAIL if reasons else GateState.PASS if complete else GateState.INCONCLUSIVE
    return SemanticAssessment(state, tuple(reasons))


def derive_review_state(request: ReviewSemanticRequest) -> SemanticAssessment:
    root, reasons = _parse_envelope(request.body, "review_evidence", request.provenance)
    checks = _mapping(root.get("checks"))
    if root.get("lane") != request.lane.value:
        reasons.append(EvidenceReason(EvidenceReasonCode.REVIEW_REF_MISMATCH, "review lane mismatch"))
    if root.get("reviewed_artifact_id") != request.reviewed_artifact_id or root.get("reviewed_content_hash") != request.reviewed_content_hash:
        reasons.append(EvidenceReason(EvidenceReasonCode.REVIEW_REF_MISMATCH, "review target mismatch"))
    required = {"manual_read": "completed", "deterministic_parser": "parser_verified", "fixture_mutation": "mutation_verified", "independent_review": "independent", "resume_review": "resume_verified"}.get(request.lane.value)
    if required is None or checks.get(required) is not True:
        reasons.append(EvidenceReason(EvidenceReasonCode.SEMANTIC_FAILURE, f"review.{request.lane.value}"))
    evidence = _parse_substantive_review(root, reasons)
    if evidence is None:
        return SemanticAssessment(GateState.FAIL, tuple(reasons))
    if request.lane.value == "independent_review" and (evidence.review_scope is None or not evidence.constraints):
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "independent review requires scope and constraints"))
    complete = root.get("complete")
    if evidence.decision is ReviewDecision.APPROVE and complete is not True:
        reasons.append(EvidenceReason(EvidenceReasonCode.SEMANTIC_FAILURE, "approved review must be complete"))
    if evidence.decision is ReviewDecision.REJECT:
        reasons.append(EvidenceReason(EvidenceReasonCode.SEMANTIC_FAILURE, "review decision is reject"))
    state = GateState.FAIL if reasons else {ReviewDecision.APPROVE: GateState.PASS, ReviewDecision.REJECT: GateState.FAIL, ReviewDecision.INCONCLUSIVE: GateState.INCONCLUSIVE}[evidence.decision]
    return SemanticAssessment(state, tuple(reasons))


def _parse_substantive_review(root: Mapping[str, JsonValue], reasons: list[EvidenceReason]) -> SubstantiveReviewEvidence | None:
    observed_sections = _string_tuple(root.get("observed_sections"))
    if not observed_sections:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "observed_sections must be non-empty"))
    raw_findings = root.get("findings")
    findings: list[ReviewFinding] = []
    if not isinstance(raw_findings, list):
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "findings must be an array"))
    else:
        for raw_finding in raw_findings:
            finding = _mapping(raw_finding)
            code = finding.get("code")
            severity = finding.get("severity")
            detail = finding.get("detail")
            try:
                parsed_severity = FindingSeverity(severity) if isinstance(severity, str) else None
            except ValueError:
                parsed_severity = None
            if not isinstance(code, str) or not code or parsed_severity is None or not isinstance(detail, str) or not detail:
                reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "finding fields are malformed"))
            else:
                findings.append(ReviewFinding(code, parsed_severity, detail))
    rationale_value = root.get("no_findings_rationale")
    rationale = rationale_value if isinstance(rationale_value, str) and rationale_value else None
    if isinstance(raw_findings, list) and not raw_findings and rationale is None:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "empty findings require no_findings_rationale"))
    decision_value = root.get("decision")
    try:
        decision = ReviewDecision(decision_value) if isinstance(decision_value, str) else None
    except ValueError:
        decision = None
    if decision is None:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "decision must be approve, reject, or inconclusive"))
        return None
    if decision is ReviewDecision.REJECT and not findings:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "reject decision requires a finding"))
    scope_value = root.get("review_scope")
    scope = scope_value if isinstance(scope_value, str) and scope_value else None
    constraints = _string_tuple(root.get("constraints"))
    return SubstantiveReviewEvidence(observed_sections, tuple(findings), rationale, decision, scope, constraints)


def _parse_envelope(body: bytes, expected_type: str, provenance_expectation: ProvenanceExpectation) -> tuple[Mapping[str, JsonValue], list[EvidenceReason]]:
    reasons: list[EvidenceReason] = []
    try:
        value = _JsonDocument.model_validate_json(body).root
    except ValidationError:
        return {}, [EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "body is not valid JSON")]
    root = _mapping(value)
    if root.get("artifact_type") != expected_type:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "artifact_type mismatch"))
    raw_generated = root.get("generated_at")
    try:
        body_generated = datetime.fromisoformat(raw_generated) if isinstance(raw_generated, str) else None
    except ValueError:
        body_generated = None
    if body_generated != provenance_expectation.generated_at or body_generated is None or body_generated.utcoffset() is None:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_TIMESTAMP, "generated_at mismatch"))
    provenance = _mapping(root.get("provenance"))
    worktree = provenance.get("worktree_hash")
    declared_worktree = provenance.get("declared_worktree_hash")
    config = provenance.get("config_hash")
    declared_config = provenance.get("declared_config_hash")
    if provenance.get("clean") is not True or not isinstance(worktree, str) or not _HASH.fullmatch(worktree) or worktree != declared_worktree or worktree != provenance_expectation.worktree_hash or not isinstance(config, str) or not _HASH.fullmatch(config) or config != declared_config or config != provenance_expectation.config_hash:
        reasons.append(EvidenceReason(EvidenceReasonCode.DIRTY_PROVENANCE, "source/config provenance is dirty or mismatched"))
    return root, reasons


def _mapping(value: JsonValue | None) -> Mapping[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _string_tuple(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return ()
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            items.append(item)
    return tuple(items)
