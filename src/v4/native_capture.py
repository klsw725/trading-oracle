from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from .models import (
    ArtifactConflictError,
    ArtifactWriteStatus,
    CanonicalJsonError,
    JsonValue,
    SnapshotId,
)
from .native_recommendation import (
    build_recommendations,
    missing_provenance,
    record,
    text,
)
from .snapshot import build_snapshot, write_snapshot
from .snapshot_validation import (
    ContractRefs,
    RequestScope,
    RetentionPolicy,
    SnapshotInput,
)


@dataclass(frozen=True, slots=True)
class NativeCaptureInput:
    multi_results: Mapping[str, JsonValue]
    signals_data: Sequence[Mapping[str, JsonValue]]
    market_data: Mapping[str, JsonValue]
    portfolio: Mapping[str, JsonValue]
    config: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CaptureDisabled:
    status: str = "disabled"


@dataclass(frozen=True, slots=True)
class CaptureInconclusive:
    missing_provenance: tuple[str, ...]
    status: str = "inconclusive"


@dataclass(frozen=True, slots=True)
class CaptureSucceeded:
    snapshot_id: SnapshotId
    path: Path
    write_status: ArtifactWriteStatus
    status: str = "captured"


@dataclass(frozen=True, slots=True)
class CaptureFailed:
    failure_type: str
    detail: str
    status: str = "failed"


type NativeCaptureResult = (
    CaptureDisabled | CaptureInconclusive | CaptureSucceeded | CaptureFailed
)


def capture_native_snapshot(source: NativeCaptureInput) -> NativeCaptureResult:
    v4_config = record(source.config.get("v4"))
    capture_config = (
        record(v4_config.get("native_capture"))
        if v4_config is not None
        else None
    )
    if capture_config is None or capture_config.get("enabled") is not True:
        return CaptureDisabled()
    output_directory = text(capture_config, "output_dir")
    missing = list(missing_provenance(source))
    if output_directory is None:
        missing.append("config.v4.native_capture.output_dir")
    if missing:
        return CaptureInconclusive(tuple(missing))

    run = record(source.market_data["v4_provenance"]) or {}
    assert output_directory is not None
    try:
        snapshot = build_snapshot(
            SnapshotInput(
                created_at=text(run, "created_at") or "",
                decision_at=text(run, "decision_at") or "",
                recommendation_emitted_at=text(run, "emitted_at") or "",
                decision_data_cutoff_at=text(run, "data_cutoff_at") or "",
                request_scope=RequestScope(
                    text(run, "market_scope") or "", (), None
                ),
                contract_refs=ContractRefs(
                    "v4.phase22.1", "v4.market_context.phase25.1"
                ),
                retention_policy=RetentionPolicy(
                    "v4.retention.phase23.1", 180, "hash_only"
                ),
                recommendations=build_recommendations(source, run),
            )
        )
        status = write_snapshot(Path(output_directory), snapshot)
    except (ArtifactConflictError, CanonicalJsonError, OSError, ValueError) as error:
        return CaptureFailed(type(error).__name__, str(error))
    path = Path(output_directory) / f"{snapshot.snapshot_id}.json"
    return CaptureSucceeded(snapshot.snapshot_id, path, status)


def capture_result_json(result: NativeCaptureResult) -> dict[str, JsonValue]:
    match result:
        case CaptureDisabled():
            return {"status": result.status}
        case CaptureInconclusive():
            return {
                "status": result.status,
                "missing_provenance": list(result.missing_provenance),
            }
        case CaptureSucceeded():
            return {
                "status": result.status,
                "snapshot_id": result.snapshot_id,
                "path": str(result.path),
                "write_status": result.write_status,
            }
        case CaptureFailed():
            return {
                "status": result.status,
                "error": {
                    "type": result.failure_type,
                    "message": result.detail,
                },
            }
        case unreachable:
            assert_never(unreachable)
