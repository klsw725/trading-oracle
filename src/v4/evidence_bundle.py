from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import ClassVar, override

from pydantic import ConfigDict, RootModel, ValidationError

from src.v4.evidence import ArtifactType, EvidenceInputRef, EvidenceRecord, EvidenceValidator
from src.v4.evidence_validation import ArtifactRegistrationRequest, ArtifactRegistry, ProvenanceExpectation, RegisteredArtifact, RegisteredReview, ReviewLane, ReviewRegistry, ReviewSemanticRequest, SemanticValidator, TrustedReviewerRegistry, ValidationContext, register_artifact
from src.v4.models import ArtifactId, ContentHash, JsonValue, canonical_hash, sha256_bytes


@dataclass(frozen=True, slots=True)
class PersistedArtifactInput:
    path: Path
    artifact_type: ArtifactType
    schema_version: str
    producer_identity: str
    producer_version: str
    producer_run_id: str
    generated_at: datetime
    input_paths: tuple[Path, ...]
    tool_config_hash: ContentHash
    self_describing: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceBundleRequest:
    artifacts: tuple[PersistedArtifactInput, ...]
    review_paths: tuple[Path, ...]
    trusted_reviewers: TrustedReviewerRegistry
    evaluated_at: datetime
    freshness_window: timedelta
    worktree_hash: ContentHash
    config_hash: ContentHash
    schemas: SemanticValidator


@dataclass(frozen=True, slots=True)
class LoadedEvidenceBundle:
    records: tuple[EvidenceRecord, ...]
    validator: EvidenceValidator


@dataclass(frozen=True, slots=True)
class EvidenceBundleError(Exception):
    path: Path
    detail: str

    @override
    def __str__(self) -> str:
        return f"invalid persisted evidence at {self.path}: {self.detail}"


class _JsonDocument(RootModel[JsonValue]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ID_PREFIX = "artifact_v4_"


def load_evidence_bundle(request: EvidenceBundleRequest) -> LoadedEvidenceBundle:
    registrations = tuple(register_artifact(ArtifactRegistrationRequest(item.path, item.artifact_type, item.schema_version, item.generated_at, request.worktree_hash, request.config_hash), request.schemas) for item in request.artifacts)
    records = tuple(_load_artifact(item, registrations) for item in request.artifacts)
    reviews = tuple(_load_review(path, records, request) for path in request.review_paths)
    reviewed_records = tuple(replace(record, review_refs=tuple(review.review_id for review in reviews if review.reviewed_artifact_id == record.artifact_id)) for record in records)
    validator = ValidationContext(ArtifactRegistry(registrations), ReviewRegistry(reviews), request.evaluated_at, request.freshness_window, request.worktree_hash, request.config_hash, request.schemas, request.trusted_reviewers)
    return LoadedEvidenceBundle(reviewed_records, validator)


def _load_artifact(item: PersistedArtifactInput, registrations: tuple[RegisteredArtifact, ...]) -> EvidenceRecord:
    body = item.path.read_bytes()
    root = _root(item.path, body)
    if root.get("schema_version") != item.schema_version or root.get("producer_identity") != item.producer_identity or root.get("producer_run_id") != item.producer_run_id:
        raise EvidenceBundleError(item.path, "producer or schema metadata mismatch")
    registration = tuple(entry for entry in registrations if entry.path == item.path)
    if len(registration) != 1:
        raise EvidenceBundleError(item.path, "artifact path is duplicated")
    inputs: list[EvidenceInputRef] = []
    for input_path in item.input_paths:
        matched = tuple(entry for entry in registrations if entry.path == input_path)
        if len(matched) != 1:
            raise EvidenceBundleError(item.path, f"input path is absent or duplicated: {input_path}")
        source = matched[0]
        inputs.append(EvidenceInputRef(source.path, source.artifact_id, source.artifact_type, source.schema_version, source.content_hash))
    stored = registration[0]
    return EvidenceRecord(stored.artifact_id, item.artifact_type, item.schema_version, item.producer_identity, item.producer_version, item.producer_run_id, item.generated_at, tuple(inputs), stored.content_hash, item.tool_config_hash, (), body, item.self_describing)


def _load_review(path: Path, records: tuple[EvidenceRecord, ...], request: EvidenceBundleRequest) -> RegisteredReview:
    body = path.read_bytes()
    root = _root(path, body)
    lane_text = _text(root, "lane", path)
    try:
        lane = ReviewLane(lane_text)
        generated_at = datetime.fromisoformat(_text(root, "generated_at", path))
    except ValueError as error:
        raise EvidenceBundleError(path, str(error)) from error
    reviewer_identity = _text(root, "reviewer_identity", path)
    fingerprint = _text(root, "reviewer_key_fingerprint", path)
    reviewer_run_id = _text(root, "reviewer_run_id", path)
    schema_version = _text(root, "schema_version", path)
    reviewed_id = ArtifactId(_text(root, "reviewed_artifact_id", path))
    reviewed_hash = ContentHash(_text(root, "reviewed_content_hash", path))
    if not _HASH.fullmatch(fingerprint) or not _HASH.fullmatch(reviewed_hash):
        raise EvidenceBundleError(path, "review fingerprint or target hash is malformed")
    target = tuple(record for record in records if record.artifact_id == reviewed_id and record.content_hash == reviewed_hash)
    if len(target) != 1:
        raise EvidenceBundleError(path, "review target does not exist in bundle")
    content_hash = sha256_bytes(body)
    identity: JsonValue = {"lane": lane.value, "schema_version": schema_version, "content_hash": content_hash, "reviewed_artifact_id": reviewed_id, "reviewed_content_hash": reviewed_hash}
    review_id = ArtifactId(f"{_ID_PREFIX}{canonical_hash(identity).removeprefix('sha256:')[:20]}")
    provenance = ProvenanceExpectation(generated_at, request.worktree_hash, request.config_hash)
    semantic = request.schemas.review_state(ReviewSemanticRequest(lane, body, provenance, reviewed_id, reviewed_hash))
    return RegisteredReview(review_id, lane, reviewer_identity, fingerprint, reviewer_run_id, path, schema_version, content_hash, body, reviewed_id, reviewed_hash, semantic.state, semantic.reasons, generated_at)


def _root(path: Path, body: bytes) -> Mapping[str, JsonValue]:
    try:
        value = _JsonDocument.model_validate_json(body).root
    except ValidationError as error:
        raise EvidenceBundleError(path, "invalid JSON") from error
    if not isinstance(value, dict):
        raise EvidenceBundleError(path, "root must be an object")
    return value


def _text(root: Mapping[str, JsonValue], field: str, path: Path) -> str:
    value = root.get(field)
    if not isinstance(value, str) or not value:
        raise EvidenceBundleError(path, f"{field} must be a non-empty string")
    return value
