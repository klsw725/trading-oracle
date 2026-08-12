from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, ValidationError

from src.v4.models import JsonValue

from .canonical import canonical_hash, parse_json
from .fixture_models import ExecutionSnapshot
from .models import StrictModel, V11ContractError


APPROVAL_PATH: Final = Path(__file__).resolve().parents[2] / "docs/specs/v11/approved_execution_snapshots.json"
APPROVAL_ARTIFACT_HASH: Final = "sha256:bd5537935ff0655e8a8420095d6a10e3aa5ca86cb6b983f01b380fc6588585a4"


class SnapshotApprovalArtifact(StrictModel):
    schema_version: Literal["v11.snapshot_approval.1"]
    approved_snapshot_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    reviewer: str
    effective_session: str
    approved: bool
    artifact_hash: str


def snapshot_hash(snapshot: ExecutionSnapshot) -> str:
    body: JsonValue = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    return canonical_hash(body)


def approval_hash(approval: SnapshotApprovalArtifact) -> str:
    body: JsonValue = approval.model_dump(mode="json", exclude={"artifact_hash"})
    return canonical_hash(body)


def load_snapshot_approval() -> SnapshotApprovalArtifact:
    try:
        approval = SnapshotApprovalArtifact.model_validate(parse_json(APPROVAL_PATH.read_bytes()))
    except (OSError, ValidationError) as error:
        raise V11ContractError("V11_SNAPSHOT_APPROVAL_ARTIFACT", str(error)) from error
    if (not approval.approved or not approval.reviewer
            or approval.artifact_hash != approval_hash(approval)
            or approval.artifact_hash != APPROVAL_ARTIFACT_HASH):
        raise V11ContractError("V11_SNAPSHOT_APPROVAL_ARTIFACT", str(APPROVAL_PATH))
    return approval


def verify_snapshot(snapshot: ExecutionSnapshot, verified_refs: set[str],
                    approval: SnapshotApprovalArtifact) -> None:
    if not approval.approved or not approval.reviewer:
        raise V11ContractError("V11_SNAPSHOT_MANIFEST_APPROVAL", snapshot.symbol)
    if approval.effective_session != snapshot.interval_start.date().isoformat():
        raise V11ContractError("V11_SNAPSHOT_MANIFEST_SESSION", snapshot.symbol)
    if snapshot.snapshot_hash != snapshot_hash(snapshot):
        raise V11ContractError("V11_EXECUTION_SNAPSHOT_HASH", snapshot.symbol)
    if snapshot.snapshot_hash not in approval.approved_snapshot_hashes:
        raise V11ContractError("V11_SNAPSHOT_NOT_APPROVED", snapshot.symbol)
    refs = {snapshot.source_ref, snapshot.calendar_ref, snapshot.watermark_ref}
    if not refs <= verified_refs:
        raise V11ContractError("V11_EXECUTION_SNAPSHOT_PROVENANCE", snapshot.symbol)
