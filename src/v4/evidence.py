from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, Protocol

from src.v4.models import ArtifactId, ContentHash, GateState, JsonValue, canonical_hash, canonical_json, sha256_bytes


@unique
class ArtifactType(StrEnum):
    MEASUREMENT_REPORT = "measurement_report"
    MEASUREMENT_FIXTURE_RESULT = "measurement_fixture_result"
    SNAPSHOT_MANIFEST = "snapshot_manifest"
    SNAPSHOT_SCHEMA_VALIDATION = "snapshot_schema_validation"
    SNAPSHOT_HASH_REPORT = "snapshot_hash_report"
    LEGACY_COVERAGE_REPORT = "legacy_coverage_report"
    INVALID_LEGACY_REPORT = "invalid_legacy_report"
    LEGACY_SOURCE_INVENTORY = "legacy_source_inventory"
    MARKET_CONTEXT_REPORT = "market_context_report"
    BLOCKED_DEGRADED_FIELD_REPORT = "blocked_degraded_field_report"
    ATTRIBUTION_LEDGER_REPORT = "attribution_ledger_report"
    DENOMINATOR_REPORT = "denominator_report"
    LEDGER_HASH_CHAIN_REPORT = "ledger_hash_chain_report"
    REPLAY_REPORT = "replay_report"
    CHECKPOINT_REPORT = "checkpoint_report"
    RESUME_REPORT = "resume_report"
    CALIBRATION_REPORT = "calibration_report"
    CALIBRATION_FIXTURE_RESULT = "calibration_fixture_result"
    PROMOTION_NOOP_REPORT = "promotion_noop_report"
    RELEASE_MANIFEST = "release_manifest"
    REVIEW_MATRIX = "review_matrix"
    GATE_DECISION_REPORT = "gate_decision_report"


@unique
class EvidenceReasonCode(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    INVALID_HASH = "invalid_hash"
    INVALID_TIMESTAMP = "invalid_timestamp"
    MISSING_PROVENANCE = "missing_provenance"
    MUTATION_DETECTED = "mutation_detected"
    UNKNOWN_INPUT_REF = "unknown_input_ref"
    INPUT_REF_MISMATCH = "input_ref_mismatch"
    REGISTRY_BODY_MISMATCH = "registry_body_mismatch"
    STALE_EVIDENCE = "stale_evidence"
    UNKNOWN_REVIEW_REF = "unknown_review_ref"
    REVIEW_REF_MISMATCH = "review_ref_mismatch"
    SELF_REVIEW = "self_review"
    MISSING_REVIEW_LANE = "missing_review_lane"
    SEMANTIC_FAILURE = "semantic_failure"
    LEGACY_PROMOTED_TO_NATIVE = "legacy_promoted_to_native"
    DIRTY_PROVENANCE = "dirty_provenance"
    DECLARED_STATE_MISMATCH = "declared_state_mismatch"
    DUPLICATE_ARTIFACT = "duplicate_artifact"
    MISSING_REQUIRED_ARTIFACT = "missing_required_artifact"
    DOWNSTREAM_CYCLE_INPUT = "downstream_cycle_input"


@dataclass(frozen=True, slots=True)
class EvidenceReason:
    code: EvidenceReasonCode
    detail: str


@dataclass(frozen=True, slots=True)
class EvidenceInputRef:
    path: Path
    artifact_id: ArtifactId
    artifact_type: ArtifactType
    schema_version: str
    expected_hash: ContentHash


@dataclass(frozen=True, slots=True)
class EvidenceRecordRequest:
    artifact_type: ArtifactType
    schema_version: str
    producer_tool: str
    producer_tool_version: str
    producer_run_id: str
    generated_at: datetime
    input_refs: tuple[EvidenceInputRef, ...]
    tool_config_hash: ContentHash
    review_refs: tuple[ArtifactId, ...]
    body: JsonValue
    self_describing: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    artifact_id: ArtifactId
    artifact_type: ArtifactType
    schema_version: str
    producer_tool: str
    producer_tool_version: str
    producer_run_id: str
    generated_at: datetime
    input_refs: tuple[EvidenceInputRef, ...]
    content_hash: ContentHash
    tool_config_hash: ContentHash
    review_refs: tuple[ArtifactId, ...]
    canonical_body: bytes
    self_describing: bool


@dataclass(frozen=True, slots=True)
class ArtifactAssessment:
    artifact_id: ArtifactId
    state: GateState
    reasons: tuple[EvidenceReason, ...]


class EvidenceValidator(Protocol):
    def validate(self, record: EvidenceRecord) -> ArtifactAssessment: ...
    def review_lane_reasons(self, records: Sequence[EvidenceRecord]) -> tuple[EvidenceReason, ...]: ...


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    artifact_id: ArtifactId
    artifact_type: ArtifactType
    schema_version: str
    producer_tool: str
    producer_tool_version: str
    generated_at: datetime
    content_hash: ContentHash
    tool_config_hash: ContentHash
    review_refs: tuple[ArtifactId, ...]
    state: GateState
    reasons: tuple[EvidenceReason, ...]


@dataclass(frozen=True, slots=True)
class ManifestBuildRequest:
    records: tuple[EvidenceRecord, ...]
    validator: EvidenceValidator
    generated_at: datetime
    producer_tool: str
    producer_tool_version: str
    tool_config_hash: ContentHash


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    artifact_id: ArtifactId
    generated_at: datetime
    producer_tool: str
    producer_tool_version: str
    tool_config_hash: ContentHash
    entries: tuple[ManifestEntry, ...]
    state: GateState
    reasons: tuple[EvidenceReason, ...]
    content_hash: ContentHash
    canonical_body: bytes


@dataclass(frozen=True, slots=True)
class GateDecision:
    artifact_id: ArtifactId
    manifest_id: ArtifactId
    manifest_hash: ContentHash
    state: GateState
    reasons: tuple[EvidenceReason, ...]
    content_hash: ContentHash


_ID_PREFIX: Final = "artifact_v4_"
_SELF_DESCRIBING: Final = frozenset({ArtifactType.MEASUREMENT_FIXTURE_RESULT, ArtifactType.CALIBRATION_FIXTURE_RESULT})
REQUIRED_MANIFEST_ARTIFACT_TYPES: Final = frozenset(artifact_type for artifact_type in ArtifactType if artifact_type not in {ArtifactType.RELEASE_MANIFEST, ArtifactType.GATE_DECISION_REPORT})


def create_evidence_record(request: EvidenceRecordRequest) -> EvidenceRecord:
    body = canonical_json(request.body)
    content_hash = sha256_bytes(body)
    identity: JsonValue = {"artifact_type": request.artifact_type.value, "schema_version": request.schema_version, "content_hash": content_hash}
    digest = canonical_hash(identity).removeprefix("sha256:")
    return EvidenceRecord(ArtifactId(f"{_ID_PREFIX}{digest[:20]}"), request.artifact_type, request.schema_version, request.producer_tool, request.producer_tool_version, request.producer_run_id, request.generated_at, request.input_refs, content_hash, request.tool_config_hash, request.review_refs, body, request.self_describing)


def validate_artifact(record: EvidenceRecord, validator: EvidenceValidator) -> ArtifactAssessment:
    return validator.validate(record)


def detect_artifact_mutation(record: EvidenceRecord, observed_body: JsonValue, validator: EvidenceValidator) -> ArtifactAssessment:
    observed_hash = canonical_hash(observed_body)
    if observed_hash != record.content_hash:
        reason = EvidenceReason(EvidenceReasonCode.MUTATION_DETECTED, f"expected {record.content_hash}, observed {observed_hash}")
        return ArtifactAssessment(record.artifact_id, GateState.FAIL, (reason,))
    return validator.validate(record)


def aggregate_gate_state(assessments: Sequence[ArtifactAssessment]) -> GateState:
    states = {assessment.state for assessment in assessments}
    if GateState.FAIL in states:
        return GateState.FAIL
    if GateState.INCONCLUSIVE in states:
        return GateState.INCONCLUSIVE
    return GateState.PASS


def build_release_manifest(request: ManifestBuildRequest) -> ReleaseManifest:
    entries: list[ManifestEntry] = []
    failures: list[EvidenceReason] = []
    inconclusive: list[EvidenceReason] = []
    seen_ids: set[ArtifactId] = set()
    seen_types: set[ArtifactType] = set()
    if request.generated_at.utcoffset() is None or not request.producer_tool or not request.producer_tool_version:
        failures.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "manifest identity is malformed"))
    for record in request.records:
        if record.artifact_type in {ArtifactType.RELEASE_MANIFEST, ArtifactType.GATE_DECISION_REPORT}:
            failures.append(EvidenceReason(EvidenceReasonCode.DOWNSTREAM_CYCLE_INPUT, record.artifact_type.value))
            continue
        assessment = request.validator.validate(record)
        if record.artifact_id in seen_ids or record.artifact_type in seen_types:
            failures.append(EvidenceReason(EvidenceReasonCode.DUPLICATE_ARTIFACT, record.artifact_type.value))
        seen_ids.add(record.artifact_id)
        seen_types.add(record.artifact_type)
        entries.append(ManifestEntry(record.artifact_id, record.artifact_type, record.schema_version, record.producer_tool, record.producer_tool_version, record.generated_at, record.content_hash, record.tool_config_hash, record.review_refs, assessment.state, assessment.reasons))
    for missing in sorted(REQUIRED_MANIFEST_ARTIFACT_TYPES - seen_types, key=str):
        failures.append(EvidenceReason(EvidenceReasonCode.MISSING_REQUIRED_ARTIFACT, missing.value))
    inconclusive.extend(request.validator.review_lane_reasons(request.records))
    entries.sort(key=lambda entry: (entry.artifact_type.value, entry.artifact_id))
    entry_state = aggregate_gate_state(tuple(ArtifactAssessment(entry.artifact_id, entry.state, entry.reasons) for entry in entries))
    state = GateState.FAIL if failures or entry_state is GateState.FAIL else GateState.INCONCLUSIVE if inconclusive or entry_state is GateState.INCONCLUSIVE else GateState.PASS
    reasons = tuple(failures or inconclusive)
    body: JsonValue = {"artifact_type": ArtifactType.RELEASE_MANIFEST.value, "schema_version": "v4.evidence_gate.release_manifest.phase29.1", "generated_at": request.generated_at.isoformat(), "producer_tool": request.producer_tool, "producer_tool_version": request.producer_tool_version, "tool_config_hash": request.tool_config_hash, "artifact_entries": [{"artifact_id": entry.artifact_id, "artifact_type": entry.artifact_type.value, "schema_version": entry.schema_version, "producer_tool": entry.producer_tool, "producer_tool_version": entry.producer_tool_version, "generated_at": entry.generated_at.isoformat(), "content_hash": entry.content_hash, "tool_config_hash": entry.tool_config_hash, "review_refs": list(entry.review_refs), "state": entry.state.value, "reasons": [f"{reason.code.value}:{reason.detail}" for reason in entry.reasons]} for entry in entries], "state": state.value, "reasons": [f"{reason.code.value}:{reason.detail}" for reason in reasons]}
    content_hash = canonical_hash(body)
    digest = content_hash.removeprefix("sha256:")
    return ReleaseManifest(ArtifactId(f"{_ID_PREFIX}{digest[:20]}"), request.generated_at, request.producer_tool, request.producer_tool_version, request.tool_config_hash, tuple(entries), state, reasons, content_hash, canonical_json(body))


def decide_gate(manifest: ReleaseManifest) -> GateDecision:
    integrity = () if sha256_bytes(manifest.canonical_body) == manifest.content_hash else (EvidenceReason(EvidenceReasonCode.MUTATION_DETECTED, "release manifest body differs from content_hash"),)
    reasons = integrity + manifest.reasons + tuple(reason for entry in manifest.entries for reason in entry.reasons)
    state = GateState.FAIL if integrity else manifest.state
    body: JsonValue = {"manifest_id": manifest.artifact_id, "manifest_hash": manifest.content_hash, "state": state.value, "reasons": [f"{reason.code.value}:{reason.detail}" for reason in reasons]}
    content_hash = canonical_hash(body)
    digest = content_hash.removeprefix("sha256:")
    return GateDecision(ArtifactId(f"{_ID_PREFIX}{digest[:20]}"), manifest.artifact_id, manifest.content_hash, state, reasons, content_hash)
