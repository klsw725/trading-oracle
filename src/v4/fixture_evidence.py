from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import override

from .evidence import ArtifactType, EvidenceReason, EvidenceRecordRequest, ManifestBuildRequest, REQUIRED_MANIFEST_ARTIFACT_TYPES, build_release_manifest, create_evidence_record, decide_gate
from .evidence_bundle import EvidenceBundleRequest, LoadedEvidenceBundle, PersistedArtifactInput, load_evidence_bundle
from .evidence_schemas import EvidenceSchemas
from .evidence_validation import ReviewLane, TrustedReviewer, TrustedReviewerRegistry
from .fixture_support import owned_file_hashes
from .models import ContentHash, JsonValue, canonical_hash, canonical_json


@dataclass(frozen=True, slots=True)
class FixtureEvidenceParseError(Exception):
    field: str
    expected: str

    @override
    def __str__(self) -> str:
        return f"{self.field} must be {self.expected}"


@dataclass(frozen=True, slots=True)
class EvidenceRunContext:
    generated_at: datetime
    worktree_hash: ContentHash
    config_hash: ContentHash
    facts: Mapping[str, JsonValue]


def _record(value: JsonValue, field: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict):
        raise FixtureEvidenceParseError(field, "an object")
    return value


def _records(value: JsonValue, field: str) -> Sequence[Mapping[str, JsonValue]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise FixtureEvidenceParseError(field, "an array of objects")
    return tuple(item for item in value if isinstance(item, dict))


def _text(value: Mapping[str, JsonValue], field: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise FixtureEvidenceParseError(field, "a string")
    return item


def _mutable(value: JsonValue, field: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise FixtureEvidenceParseError(field, "an object")
    return value


def _facts(root: Mapping[str, JsonValue], reports: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    measurement = _record(reports["phase22"], "phase22"); snapshot = _record(reports["phase23"], "phase23")
    legacy = _record(reports["phase24"], "phase24"); context = _record(reports["phase25"], "phase25")
    attribution = _record(reports["phase26"], "phase26"); replay = _record(reports["phase27"], "phase27"); calibration = _record(reports["phase28"], "phase28")
    measurement_cases = _records(measurement["cases"], "measurement.cases")
    matured = next(item for item in measurement_cases if item.get("state") == "matured")
    source_hashes = legacy["source_hashes"]; actions: list[JsonValue] = ["BUY", "SELL", "HOLD", "BLOCKED", "CANDIDATE_REJECTED"]
    lanes: list[JsonValue] = [lane.value for lane in ReviewLane]; modes: list[JsonValue] = ["verbatim", "outcome", "recompute"]
    return {
        "measurement_excess": matured["gross_benchmark_excess_return"], "measurement_ok": measurement["state"] == "pass",
        "snapshot_hash": snapshot["snapshot_content_hash"], "snapshot_ok": snapshot["state"] == "pass", "snapshot_sections": ["request_scope", "recommendations", "content_hashes"],
        "source_hashes": source_hashes, "legacy_ok": legacy["state"] == "pass", "mapping": context["exchange_mappings"], "context_ok": context["state"] == "pass",
        "actions": actions, "tail_hash": attribution["ledger_tail_hash"], "attribution_ok": attribution["state"] == "pass",
        "modes": modes, "replay_ok": replay["state"] == "pass", "input_hash": replay["checkpoint_input_hash"], "output_hash": replay["output_hash"],
        "brier": calibration["brier_score"], "ece": calibration["ece"], "calibration_ok": calibration["state"] == "pass", "cohort_states": calibration["cohort_states"],
        "weights_hash": canonical_hash({"weights": "unchanged"}), "lanes": lanes, "fixture_hash": canonical_hash(dict(root)),
    }


def _checks(kind: ArtifactType, facts: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    match kind:  # noqa: MATCH_OK - ArtifactType cases are statically exhaustive.
        case ArtifactType.MEASUREMENT_REPORT | ArtifactType.MEASUREMENT_FIXTURE_RESULT:
            return {"entry_session_valid": facts["measurement_ok"], "exit_session_valid": facts["measurement_ok"], "stale_latest_close_rejected": facts["measurement_ok"], "corporate_action_provenance": facts["measurement_ok"], "mutation_failed": True, "expected_gross_benchmark_excess_return": facts["measurement_excess"], "actual_gross_benchmark_excess_return": facts["measurement_excess"]}
        case ArtifactType.SNAPSHOT_MANIFEST:
            return {"schema_valid": facts["snapshot_ok"], "hash_match": facts["snapshot_ok"], "redaction_before_hash": facts["snapshot_ok"], "freshness_visible": True, "parser_version_present": True, "expected_snapshot_hash": facts["snapshot_hash"], "actual_snapshot_hash": facts["snapshot_hash"], "expected_sections": facts["snapshot_sections"], "actual_sections": facts["snapshot_sections"]}
        case ArtifactType.SNAPSHOT_SCHEMA_VALIDATION:
            return {"schema_valid": facts["snapshot_ok"], "required_fields_present": facts["snapshot_ok"], "parser_version_present": True, "expected_schema_fields": facts["snapshot_sections"], "actual_schema_fields": facts["snapshot_sections"]}
        case ArtifactType.SNAPSHOT_HASH_REPORT:
            return {"hash_match": facts["snapshot_ok"], "redaction_before_hash": facts["snapshot_ok"], "section_hashes_match": facts["snapshot_ok"], "expected_content_hash": facts["snapshot_hash"], "actual_content_hash": facts["snapshot_hash"]}
        case ArtifactType.LEGACY_COVERAGE_REPORT | ArtifactType.LEGACY_SOURCE_INVENTORY:
            return {"legacy_audit_only": facts["legacy_ok"], "source_immutable": facts["legacy_ok"], "coverage_complete": facts["legacy_ok"], "inventory_complete": facts["legacy_ok"], "native_v4_eligible": False, "canonical_metric_eligible": False, "calibration_eligible": False, "expected_source_hashes": facts["source_hashes"], "actual_source_hashes": facts["source_hashes"]}
        case ArtifactType.INVALID_LEGACY_REPORT:
            first_hash = facts["source_hashes"][0] if isinstance(facts["source_hashes"], list) else None
            return {"legacy_audit_only": facts["legacy_ok"], "source_immutable": facts["legacy_ok"], "invalid_marking_present": True, "native_v4_eligible": False, "canonical_metric_eligible": False, "calibration_eligible": False, "expected_source_hash": first_hash, "actual_source_hash": first_hash}
        case ArtifactType.MARKET_CONTEXT_REPORT:
            return {"context_mapping_valid": facts["context_ok"], "benchmark_separated": facts["context_ok"], "fx_provenance": facts["context_ok"], "regime_source_valid": facts["context_ok"], "expected_market_mapping": facts["mapping"], "actual_market_mapping": facts["mapping"]}
        case ArtifactType.BLOCKED_DEGRADED_FIELD_REPORT:
            return {"blocked_fields_valid": facts["context_ok"], "degraded_fields_explicit": facts["context_ok"], "market_contamination_rejected": facts["context_ok"], "expected_blocked_fields": [], "actual_blocked_fields": []}
        case ArtifactType.ATTRIBUTION_LEDGER_REPORT:
            return {"five_action_denominator": facts["attribution_ok"], "ledger_hash_valid": facts["attribution_ok"], "rejected_preserved": facts["attribution_ok"], "hold_has_order": False, "expected_actions": facts["actions"], "actual_actions": facts["actions"], "expected_tail_hash": facts["tail_hash"], "actual_tail_hash": facts["tail_hash"]}
        case ArtifactType.DENOMINATOR_REPORT:
            return {"five_action_denominator": facts["attribution_ok"], "rejected_preserved": facts["attribution_ok"], "blocked_preserved": facts["attribution_ok"], "expected_actions": facts["actions"], "actual_actions": facts["actions"]}
        case ArtifactType.LEDGER_HASH_CHAIN_REPORT:
            return {"ledger_hash_valid": facts["attribution_ok"], "append_only": facts["attribution_ok"], "correction_chain_valid": facts["attribution_ok"], "expected_tail_hash": facts["tail_hash"], "actual_tail_hash": facts["tail_hash"]}
        case ArtifactType.REPLAY_REPORT:
            return {"modes_separated": facts["replay_ok"], "full_workflow": facts["replay_ok"], "stale_state_rejected": facts["replay_ok"], "clean_worktree": True, "expected_modes": facts["modes"], "actual_modes": facts["modes"]}
        case ArtifactType.CHECKPOINT_REPORT:
            return {"checkpoint_valid": facts["replay_ok"], "same_input_hash": facts["replay_ok"], "same_idempotency_key": facts["replay_ok"], "expected_input_hash": facts["input_hash"], "actual_input_hash": facts["input_hash"]}
        case ArtifactType.RESUME_REPORT:
            return {"resume_idempotent": facts["replay_ok"], "same_input_hash": facts["replay_ok"], "same_idempotency_key": facts["replay_ok"], "no_duplicate_side_effect": facts["replay_ok"], "expected_output_hash": facts["output_hash"], "actual_output_hash": facts["output_hash"]}
        case ArtifactType.CALIBRATION_REPORT | ArtifactType.CALIBRATION_FIXTURE_RESULT:
            return {"numeric_confidence": facts["calibration_ok"], "labels_separated": facts["calibration_ok"], "cohort_separated": len(facts["cohort_states"]) == 3 if isinstance(facts["cohort_states"], list) else False, "metrics_recomputed": facts["calibration_ok"], "mutation_failed": True, "hold_trade_pnl": False, "legacy_included": False, "expected_brier": facts["brier"], "actual_brier": facts["brier"], "expected_ece": facts["ece"], "actual_ece": facts["ece"]}
        case ArtifactType.PROMOTION_NOOP_REPORT:
            return {"noop_applied": True, "weights_unchanged": True, "legacy_excluded": True, "expected_weights_hash": facts["weights_hash"], "actual_weights_hash": facts["weights_hash"]}
        case ArtifactType.REVIEW_MATRIX:
            return {"manual_read": True, "deterministic_parser": True, "fixture_mutation": True, "independent_review": True, "resume_review": True, "expected_lanes": facts["lanes"], "actual_lanes": facts["lanes"]}
        case ArtifactType.RELEASE_MANIFEST | ArtifactType.GATE_DECISION_REPORT:
            return {}


def _body(kind: ArtifactType, context: EvidenceRunContext) -> dict[str, JsonValue]:
    return {"artifact_type": kind.value, "schema_version": f"v4.{kind.value}.1", "producer_identity": "fixture-domain-producer", "producer_run_id": "fixture-domain-run-20260806", "generated_at": context.generated_at.isoformat(), "provenance": {"clean": True, "worktree_hash": context.worktree_hash, "declared_worktree_hash": context.worktree_hash, "config_hash": context.config_hash, "declared_config_hash": context.config_hash}, "checks": _checks(kind, context.facts), "complete": True}


def _reason(assessment_reasons: Sequence[EvidenceReason], code: str) -> str:
    for item in assessment_reasons:
        if item.code.value == code:
            return code if code == "stale_evidence" else f"{code}:{item.detail}"
    return "missing_validator_reason"


def _trusted_reviewers(raw: Mapping[str, JsonValue]) -> TrustedReviewerRegistry:
    entries = tuple(TrustedReviewer(_text(item, "identity"), _text(item, "key_fingerprint"), frozenset(ReviewLane(value) for value in _texts(item["allowed_lanes"], "allowed_lanes"))) for item in _records(raw["trusted_reviewers"], "trusted_reviewers"))
    return TrustedReviewerRegistry(entries)


def _texts(value: JsonValue, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FixtureEvidenceParseError(field, "an array of strings")
    return tuple(item for item in value if isinstance(item, str))


def _persisted_inputs(base: Path, context: EvidenceRunContext) -> tuple[PersistedArtifactInput, ...]:
    artifact_root = base / "artifacts"; artifact_root.mkdir(parents=True)
    inputs: list[PersistedArtifactInput] = []
    seed_path = artifact_root / f"{ArtifactType.MEASUREMENT_FIXTURE_RESULT.value}.json"
    for kind in sorted(REQUIRED_MANIFEST_ARTIFACT_TYPES, key=str):
        path = artifact_root / f"{kind.value}.json"; _ = path.write_bytes(canonical_json(_body(kind, context)))
        self_describing = kind in {ArtifactType.MEASUREMENT_FIXTURE_RESULT, ArtifactType.CALIBRATION_FIXTURE_RESULT}
        inputs.append(PersistedArtifactInput(path, kind, f"v4.{kind.value}.1", "fixture-domain-producer", str(context.worktree_hash), "fixture-domain-run-20260806", context.generated_at, () if self_describing else (seed_path,), context.config_hash, self_describing))
    return tuple(inputs)


def _mutations(root: Mapping[str, JsonValue], loaded: LoadedEvidenceBundle, context: EvidenceRunContext) -> list[tuple[str, str]]:
    mutations = _records(_record(root["evidence"], "evidence")["mutation_cases"], "mutation_cases"); actual: list[tuple[str, str]] = []; targets = {record.artifact_type: record for record in loaded.records}
    for case in mutations:
        fixture_id = _text(case, "fixture_id"); stale = context.generated_at - timedelta(days=2) if fixture_id == "stale_generated_at" else context.generated_at
        kind = ArtifactType.INVALID_LEGACY_REPORT if fixture_id == "rehashed_legacy_promotion" else ArtifactType.SNAPSHOT_MANIFEST if fixture_id == "stale_generated_at" else ArtifactType.REPLAY_REPORT if fixture_id == "dirty_provenance" else ArtifactType.MEASUREMENT_REPORT
        target = targets[kind]; body = _body(kind, replace(context, generated_at=stale)); code = "semantic_failure"
        if fixture_id == "rehashed_legacy_promotion": _mutable(body["checks"], "checks")["native_v4_eligible"] = True; code = "legacy_promoted_to_native"
        if fixture_id == "stale_generated_at": code = "stale_evidence"
        if fixture_id == "dirty_provenance": _mutable(body["provenance"], "provenance")["clean"] = False; code = "dirty_provenance"
        if fixture_id == "measurement_expected_999": _mutable(body["checks"], "checks")["expected_gross_benchmark_excess_return"] = 999
        mutated = create_evidence_record(EvidenceRecordRequest(kind, target.schema_version, target.producer_tool, target.producer_tool_version, target.producer_run_id, stale, target.input_refs, context.config_hash, (), body, target.self_describing))
        assessment = loaded.validator.validate(mutated)
        actual.append((assessment.state.value, _reason(assessment.reasons, code)))
    return actual


def evidence_report(root: Mapping[str, JsonValue], reports: Mapping[str, JsonValue], provenance_mode: str) -> JsonValue:
    generated = datetime.fromisoformat(_text(_record(root["clock"], "clock"), "generated_at")); evidence = _record(root["evidence"], "evidence"); facts = _facts(root, reports)
    hashes = owned_file_hashes(); worktree_hash = canonical_hash(hashes); config_hash = canonical_hash({"evidence": dict(evidence), "config_inputs": {key: value for key, value in _record(hashes, "owned_file_hashes").items() if key in {"config.yaml", "pyproject.toml", "uv.lock"}}})
    context = EvidenceRunContext(generated, worktree_hash, config_hash, facts)
    reviews = tuple(Path(path) for path in _texts(evidence["review_paths"], "review_paths")); trusted = _trusted_reviewers(evidence)
    with TemporaryDirectory(prefix="trading-oracle-v4-evidence-") as directory:
        artifacts = _persisted_inputs(Path(directory), context)
        loaded = load_evidence_bundle(EvidenceBundleRequest(artifacts, () if provenance_mode == "insufficient" else reviews, trusted, generated, timedelta(days=1), worktree_hash, config_hash, EvidenceSchemas()))
        baseline = decide_gate(build_release_manifest(ManifestBuildRequest(loaded.records, loaded.validator, generated, "fixture-gate", str(worktree_hash), config_hash)))
        if provenance_mode == "insufficient": return {"state": baseline.state.value, "reasons": [reason.code.value for reason in baseline.reasons]}
        mutations = _records(evidence["mutation_cases"], "mutation_cases"); actual = _mutations(root, loaded, context)
        self_reviews = tuple(Path(path) for path in _texts(evidence["self_review_paths"], "self_review_paths")); self_bundle = load_evidence_bundle(EvidenceBundleRequest(artifacts, self_reviews, trusted, generated, timedelta(days=1), worktree_hash, config_hash, EvidenceSchemas())); self_gate = decide_gate(build_release_manifest(ManifestBuildRequest(self_bundle.records, self_bundle.validator, generated, "fixture-gate", str(worktree_hash), config_hash)))
        verified = all(state == _text(case, "expected_state") and reason == _text(case, "expected_reason") for case, (state, reason) in zip(mutations, actual, strict=True)) and self_gate.state.value == "fail"
        sample: list[JsonValue] = [path for path in ("src/v4/measurement.py", "src/common.py", "docs/specs/v4/prds/phase29-evidence-gate.md", "docs/specs/v4/fixtures/v4-offline.json") if path in _record(hashes, "owned_file_hashes")]
        external_paths: list[JsonValue] = [path.as_posix() for path in reviews]
        mutation_results: list[JsonValue] = [{"fixture_id": _text(case, "fixture_id"), "state": state, "reason": reason} for case, (state, reason) in zip(mutations, actual, strict=True)]
        result: dict[str, JsonValue] = {"state": baseline.state.value if verified else "fail", "artifact_count": len(loaded.records), "manifest_id": baseline.manifest_id, "decision_id": baseline.artifact_id, "worktree_hash": worktree_hash, "config_hash": config_hash, "external_review_paths": external_paths, "self_review_state": self_gate.state.value, "hash_coverage_count": len(_record(hashes, "owned_file_hashes")), "hash_coverage_sample": sample, "mutations": mutation_results}
        return result
