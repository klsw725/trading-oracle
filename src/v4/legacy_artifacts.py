from dataclasses import dataclass
from pathlib import Path
from typing import NewType, override

from .legacy import (
    POLICY_VERSION,
    build_legacy_derived_audit,
    legacy_derived_body,
)
from .legacy_coverage import (
    coverage_document as _coverage_document,
    legacy_derived_path as _derived_path,
    quarantine_document as _quarantine_document,
)
from .legacy_models import LegacyDerivedAudit, LegacyInventoryReport, LegacyParseState
from src.v4.models import (
    ArtifactWriteStatus,
    ContentHash,
    JsonValue,
    canonical_hash,
    sha256_bytes,
    write_immutable_json,
)


LegacyRunId = NewType("LegacyRunId", str)
LegacyArtifactSetId = NewType("LegacyArtifactSetId", str)


@dataclass(frozen=True, slots=True)
class LegacyArtifactWriteRequest:
    inventory: LegacyInventoryReport
    derived_root: Path
    generated_at: str


@dataclass(frozen=True, slots=True)
class LegacyArtifactWrite:
    path: Path
    content_hash: ContentHash
    status: ArtifactWriteStatus


@dataclass(frozen=True, slots=True)
class LegacyArtifactWriteReport:
    run_id: LegacyRunId
    artifact_set_id: LegacyArtifactSetId
    coverage_complete: bool
    audit_overlay_eligible: bool
    writes: tuple[LegacyArtifactWrite, ...]
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class LegacySourceChangedError(Exception):
    source_path: Path
    expected_hash: ContentHash
    actual_hash: ContentHash

    @override
    def __str__(self) -> str:
        return (
            f"legacy source changed during run: {self.source_path} "
            f"expected={self.expected_hash}, actual={self.actual_hash}"
        )


def _derived_document(audit: LegacyDerivedAudit) -> JsonValue:
    body = legacy_derived_body(audit)
    return {
        **body,
        "content_hashes": {
            "derived_artifact_hash": audit.derived_artifact_hash,
            "source_link_hash": audit.source_link_hash,
        },
    }


def _write(path: Path, value: JsonValue) -> LegacyArtifactWrite:
    return LegacyArtifactWrite(path, canonical_hash(value), write_immutable_json(path, value))


def write_legacy_artifacts(
    request: LegacyArtifactWriteRequest,
) -> LegacyArtifactWriteReport:
    for source in request.inventory.records:
        actual_hash = sha256_bytes(source.source_path.read_bytes())
        if actual_hash != source.source_hash:
            raise LegacySourceChangedError(source.source_path, source.source_hash, actual_hash)

    audits = tuple(build_legacy_derived_audit(source) for source in request.inventory.records)
    artifact_set_hash = canonical_hash(
        {
            "inputs": [
                {"source_path": source.source_path.as_posix(), "source_sha256": source.source_hash}
                for source in request.inventory.records
            ],
            "policy_version": POLICY_VERSION,
        }
    )
    artifact_set_id = LegacyArtifactSetId(
        f"legacy_set_{artifact_set_hash.removeprefix('sha256:')[:20]}"
    )
    run_hash = canonical_hash(
        {"artifact_set_id": artifact_set_id, "generated_at": request.generated_at}
    )
    run_id = LegacyRunId(f"legacy_run_{run_hash.removeprefix('sha256:')[:20]}")
    writes: list[LegacyArtifactWrite] = []
    for audit in audits:
        if audit.parse_state is LegacyParseState.PARSED:
            writes.append(_write(_derived_path(request.derived_root, audit), _derived_document(audit)))

    coverage = _coverage_document(request.inventory, request.derived_root, audits)
    quarantine = _quarantine_document(request.inventory)
    writes.append(_write(request.derived_root / "reports" / f"coverage.{artifact_set_id}.json", coverage))
    writes.append(_write(request.derived_root / "reports" / f"quarantine.{artifact_set_id}.json", quarantine))
    manifest_path = request.derived_root / "manifests" / f"{run_id}.json"
    manifest: JsonValue = {
        "audit_only": True,
        "artifact_set_id": artifact_set_id,
        "generated_at": request.generated_at,
        "inputs": [
            {"source_path": source.source_path.as_posix(), "source_sha256": source.source_hash}
            for source in request.inventory.records
        ],
        "outputs": [
            {"artifact_path": write.path.as_posix(), "artifact_sha256": write.content_hash}
            for write in writes
        ],
        "policy_version": POLICY_VERSION,
        "run_id": run_id,
        "schema_version": "v4.legacy_backfill.manifest.phase24.1",
    }
    writes.append(_write(manifest_path, manifest))
    return LegacyArtifactWriteReport(
        run_id=run_id,
        artifact_set_id=artifact_set_id,
        coverage_complete=request.inventory.coverage_complete,
        audit_overlay_eligible=request.inventory.audit_overlay_eligible,
        writes=tuple(writes),
        manifest_path=manifest_path,
    )
