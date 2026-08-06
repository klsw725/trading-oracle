from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum, unique
from pathlib import Path
import re
from typing import Final, Protocol

from src.v4.evidence import ArtifactAssessment, ArtifactType, EvidenceReason, EvidenceReasonCode, EvidenceRecord
from src.v4.models import ArtifactId, ContentHash, GateState, JsonValue, canonical_hash, sha256_bytes


@unique
class ReviewLane(StrEnum):
    MANUAL_READ = "manual_read"
    DETERMINISTIC_PARSER = "deterministic_parser"
    FIXTURE_MUTATION = "fixture_mutation"
    INDEPENDENT_REVIEW = "independent_review"
    RESUME_REVIEW = "resume_review"


@dataclass(frozen=True, slots=True)
class RegisteredArtifact:
    artifact_id: ArtifactId
    path: Path
    artifact_type: ArtifactType
    schema_version: str
    content_hash: ContentHash
    canonical_body: bytes
    state: GateState
    semantic_reasons: tuple[EvidenceReason, ...]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class RegisteredReview:
    review_id: ArtifactId
    lane: ReviewLane
    reviewer_identity: str
    reviewer_key_fingerprint: str
    reviewer_run_id: str
    path: Path
    schema_version: str
    content_hash: ContentHash
    canonical_body: bytes
    reviewed_artifact_id: ArtifactId
    reviewed_content_hash: ContentHash
    state: GateState
    semantic_reasons: tuple[EvidenceReason, ...]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    state: GateState
    reasons: tuple[EvidenceReason, ...]


@dataclass(frozen=True, slots=True)
class ProvenanceExpectation:
    generated_at: datetime
    worktree_hash: ContentHash
    config_hash: ContentHash


@dataclass(frozen=True, slots=True)
class ReviewSemanticRequest:
    lane: ReviewLane
    body: bytes
    provenance: ProvenanceExpectation
    reviewed_artifact_id: ArtifactId
    reviewed_content_hash: ContentHash


class SemanticValidator(Protocol):
    def artifact_state(self, artifact_type: ArtifactType, body: bytes, provenance: ProvenanceExpectation) -> SemanticAssessment: ...
    def review_state(self, request: ReviewSemanticRequest) -> SemanticAssessment: ...


@dataclass(frozen=True, slots=True)
class ArtifactRegistrationRequest:
    path: Path
    artifact_type: ArtifactType
    schema_version: str
    generated_at: datetime
    worktree_hash: ContentHash
    config_hash: ContentHash


@dataclass(frozen=True, slots=True)
class ArtifactRegistry:
    entries: tuple[RegisteredArtifact, ...]


@dataclass(frozen=True, slots=True)
class ReviewRegistry:
    entries: tuple[RegisteredReview, ...]


@dataclass(frozen=True, slots=True)
class TrustedReviewer:
    identity: str
    key_fingerprint: str
    allowed_lanes: frozenset[ReviewLane]


@dataclass(frozen=True, slots=True)
class TrustedReviewerRegistry:
    entries: tuple[TrustedReviewer, ...]


@dataclass(frozen=True, slots=True)
class ValidationContext:
    artifacts: ArtifactRegistry
    reviews: ReviewRegistry
    evaluated_at: datetime
    freshness_window: timedelta
    worktree_hash: ContentHash
    config_hash: ContentHash
    schemas: SemanticValidator
    trusted_reviewers: TrustedReviewerRegistry

    def validate(self, record: EvidenceRecord) -> ArtifactAssessment:
        failures: list[EvidenceReason] = []
        inconclusive: list[EvidenceReason] = []
        if not record.schema_version or not record.producer_tool or not record.producer_tool_version or not _ID_PATTERN.fullmatch(record.artifact_id):
            failures.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "artifact identity is malformed"))
        if record.generated_at.utcoffset() is None or self.evaluated_at.utcoffset() is None:
            failures.append(EvidenceReason(EvidenceReasonCode.INVALID_TIMESTAMP, "evidence timestamps must include timezones"))
        if record.generated_at > self.evaluated_at or self.evaluated_at - record.generated_at > self.freshness_window:
            failures.append(EvidenceReason(EvidenceReasonCode.STALE_EVIDENCE, str(record.artifact_id)))
        if not _HASH_PATTERN.fullmatch(record.content_hash) or not _HASH_PATTERN.fullmatch(record.tool_config_hash):
            failures.append(EvidenceReason(EvidenceReasonCode.INVALID_HASH, "artifact hash is malformed"))
        if sha256_bytes(record.canonical_body) != record.content_hash:
            failures.append(EvidenceReason(EvidenceReasonCode.MUTATION_DETECTED, "artifact body differs from its immutable hash"))
        persisted = tuple(entry for entry in self.artifacts.entries if entry.artifact_id == record.artifact_id)
        if len(persisted) != 1:
            failures.append(EvidenceReason(EvidenceReasonCode.UNKNOWN_INPUT_REF, f"unregistered artifact: {record.artifact_id}"))
        elif persisted[0].canonical_body != record.canonical_body:
            failures.append(EvidenceReason(EvidenceReasonCode.REGISTRY_BODY_MISMATCH, str(persisted[0].path)))
        else:
            failures.extend(_artifact_failures(persisted[0], self))
        semantic_record = self.schemas.artifact_state(record.artifact_type, record.canonical_body, ProvenanceExpectation(record.generated_at, self.worktree_hash, self.config_hash))
        failures.extend(semantic_record.reasons)
        if semantic_record.state is GateState.INCONCLUSIVE:
            inconclusive.append(EvidenceReason(EvidenceReasonCode.MISSING_PROVENANCE, f"artifact is inconclusive: {record.artifact_id}"))
        if record.self_describing and record.artifact_type not in _SELF_DESCRIBING:
            failures.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, "artifact type cannot be self-describing"))
        if not record.input_refs and not record.self_describing:
            inconclusive.append(EvidenceReason(EvidenceReasonCode.MISSING_PROVENANCE, "input_refs are missing"))
        for input_ref in record.input_refs:
            matches = tuple(entry for entry in self.artifacts.entries if entry.artifact_id == input_ref.artifact_id)
            if len(matches) != 1:
                failures.append(EvidenceReason(EvidenceReasonCode.UNKNOWN_INPUT_REF, str(input_ref.artifact_id)))
                continue
            registered = matches[0]
            if (registered.path, registered.artifact_type, registered.schema_version, registered.content_hash) != (input_ref.path, input_ref.artifact_type, input_ref.schema_version, input_ref.expected_hash):
                failures.append(EvidenceReason(EvidenceReasonCode.INPUT_REF_MISMATCH, str(input_ref.artifact_id)))
            failures.extend(_artifact_failures(registered, self))
            semantic = self.schemas.artifact_state(registered.artifact_type, registered.canonical_body, ProvenanceExpectation(registered.generated_at, self.worktree_hash, self.config_hash))
            if semantic.state is GateState.INCONCLUSIVE:
                inconclusive.append(EvidenceReason(EvidenceReasonCode.MISSING_PROVENANCE, f"input is inconclusive: {registered.artifact_id}"))
            if semantic.state is GateState.FAIL:
                failures.append(EvidenceReason(EvidenceReasonCode.INPUT_REF_MISMATCH, f"input failed: {registered.artifact_id}"))
        if not record.review_refs:
            inconclusive.append(EvidenceReason(EvidenceReasonCode.MISSING_PROVENANCE, "review_refs are missing"))
        independent_reviewer = False
        for review_id in record.review_refs:
            matches = tuple(entry for entry in self.reviews.entries if entry.review_id == review_id)
            if len(matches) != 1:
                failures.append(EvidenceReason(EvidenceReasonCode.UNKNOWN_REVIEW_REF, str(review_id)))
                continue
            review = matches[0]
            trusted = tuple(item for item in self.trusted_reviewers.entries if item.identity == review.reviewer_identity and item.key_fingerprint == review.reviewer_key_fingerprint and review.lane in item.allowed_lanes)
            if len(trusted) != 1:
                failures.append(EvidenceReason(EvidenceReasonCode.UNKNOWN_REVIEW_REF, f"untrusted reviewer: {review.reviewer_identity}"))
            independent_reviewer = independent_reviewer or (review.reviewer_identity != record.producer_tool and review.reviewer_run_id != record.producer_run_id)
            failures.extend(_review_failures(review, record, self))
            semantic = self.schemas.review_state(ReviewSemanticRequest(review.lane, review.canonical_body, ProvenanceExpectation(review.generated_at, self.worktree_hash, self.config_hash), review.reviewed_artifact_id, review.reviewed_content_hash))
            if semantic.state is GateState.INCONCLUSIVE:
                inconclusive.append(EvidenceReason(EvidenceReasonCode.MISSING_PROVENANCE, f"review is inconclusive: {review_id}"))
            if semantic.state is GateState.FAIL:
                failures.append(EvidenceReason(EvidenceReasonCode.REVIEW_REF_MISMATCH, f"review failed: {review_id}"))
        if record.review_refs and not independent_reviewer:
            failures.append(EvidenceReason(EvidenceReasonCode.SELF_REVIEW, "artifact producer is the only reviewer"))
        reasons = tuple(failures or inconclusive)
        state = GateState.FAIL if failures else GateState.INCONCLUSIVE if inconclusive else GateState.PASS
        return ArtifactAssessment(record.artifact_id, state, reasons)

    def review_lane_reasons(self, records: Sequence[EvidenceRecord]) -> tuple[EvidenceReason, ...]:
        referenced = {review_id for record in records for review_id in record.review_refs}
        lanes = {review.lane for review in self.reviews.entries if review.review_id in referenced and self.schemas.review_state(ReviewSemanticRequest(review.lane, review.canonical_body, ProvenanceExpectation(review.generated_at, self.worktree_hash, self.config_hash), review.reviewed_artifact_id, review.reviewed_content_hash)).state is GateState.PASS}
        return tuple(EvidenceReason(EvidenceReasonCode.MISSING_REVIEW_LANE, lane.value) for lane in sorted(REQUIRED_REVIEW_LANES - lanes, key=str))


_HASH_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ID_PATTERN: Final = re.compile(r"artifact_v4_[0-9a-f]{20}\Z")
_ID_PREFIX: Final = "artifact_v4_"
_SELF_DESCRIBING: Final = frozenset({ArtifactType.MEASUREMENT_FIXTURE_RESULT, ArtifactType.CALIBRATION_FIXTURE_RESULT})
REQUIRED_REVIEW_LANES: Final = frozenset(ReviewLane)


def register_artifact(request: ArtifactRegistrationRequest, schemas: SemanticValidator) -> RegisteredArtifact:
    body = request.path.read_bytes()
    content_hash = sha256_bytes(body)
    identity: JsonValue = {"artifact_type": request.artifact_type.value, "schema_version": request.schema_version, "content_hash": content_hash}
    digest = canonical_hash(identity).removeprefix("sha256:")
    semantic = schemas.artifact_state(request.artifact_type, body, ProvenanceExpectation(request.generated_at, request.worktree_hash, request.config_hash))
    return RegisteredArtifact(ArtifactId(f"{_ID_PREFIX}{digest[:20]}"), request.path, request.artifact_type, request.schema_version, content_hash, body, semantic.state, semantic.reasons, request.generated_at)


def _artifact_failures(entry: RegisteredArtifact, context: ValidationContext) -> list[EvidenceReason]:
    semantic = context.schemas.artifact_state(entry.artifact_type, entry.canonical_body, ProvenanceExpectation(entry.generated_at, context.worktree_hash, context.config_hash))
    reasons = list(semantic.reasons)
    identity: JsonValue = {"artifact_type": entry.artifact_type.value, "schema_version": entry.schema_version, "content_hash": entry.content_hash}
    expected_id = ArtifactId(f"{_ID_PREFIX}{canonical_hash(identity).removeprefix('sha256:')[:20]}")
    if entry.artifact_id != expected_id:
        reasons.append(EvidenceReason(EvidenceReasonCode.INVALID_SCHEMA, f"non-deterministic registry id: {entry.artifact_id}"))
    if entry.generated_at.utcoffset() is None or context.evaluated_at.utcoffset() is None or entry.generated_at > context.evaluated_at or context.evaluated_at - entry.generated_at > context.freshness_window:
        reasons.append(EvidenceReason(EvidenceReasonCode.STALE_EVIDENCE, str(entry.artifact_id)))
    if entry.state is not semantic.state:
        reasons.append(EvidenceReason(EvidenceReasonCode.DECLARED_STATE_MISMATCH, str(entry.artifact_id)))
    if sha256_bytes(entry.canonical_body) != entry.content_hash or _persisted_body(entry.path) != entry.canonical_body:
        reasons.append(EvidenceReason(EvidenceReasonCode.REGISTRY_BODY_MISMATCH, str(entry.path)))
    return reasons


def _review_failures(entry: RegisteredReview, record: EvidenceRecord, context: ValidationContext) -> list[EvidenceReason]:
    semantic = context.schemas.review_state(ReviewSemanticRequest(entry.lane, entry.canonical_body, ProvenanceExpectation(entry.generated_at, context.worktree_hash, context.config_hash), entry.reviewed_artifact_id, entry.reviewed_content_hash))
    reasons = list(semantic.reasons)
    identity: JsonValue = {"lane": entry.lane.value, "schema_version": entry.schema_version, "content_hash": entry.content_hash, "reviewed_artifact_id": entry.reviewed_artifact_id, "reviewed_content_hash": entry.reviewed_content_hash}
    expected_id = ArtifactId(f"{_ID_PREFIX}{canonical_hash(identity).removeprefix('sha256:')[:20]}")
    if entry.review_id != expected_id or entry.reviewed_artifact_id != record.artifact_id or entry.reviewed_content_hash != record.content_hash or not entry.schema_version:
        reasons.append(EvidenceReason(EvidenceReasonCode.REVIEW_REF_MISMATCH, str(entry.review_id)))
    if entry.generated_at.utcoffset() is None or context.evaluated_at.utcoffset() is None or entry.generated_at > context.evaluated_at or context.evaluated_at - entry.generated_at > context.freshness_window:
        reasons.append(EvidenceReason(EvidenceReasonCode.STALE_EVIDENCE, str(entry.review_id)))
    if entry.state is not semantic.state:
        reasons.append(EvidenceReason(EvidenceReasonCode.DECLARED_STATE_MISMATCH, str(entry.review_id)))
    if sha256_bytes(entry.canonical_body) != entry.content_hash or _persisted_body(entry.path) != entry.canonical_body:
        reasons.append(EvidenceReason(EvidenceReasonCode.REGISTRY_BODY_MISMATCH, str(entry.path)))
    return reasons


def _persisted_body(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""
