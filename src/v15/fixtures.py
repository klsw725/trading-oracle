from __future__ import annotations

import os
import stat
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from pydantic import TypeAdapter, ValidationError
from src.v11.canonical import canonical_hash, model_json, parse_json
from src.v11.models import V11ContractError
from src.v14.integrity import verify_bundle as verify_v14_bundle
from src.v14.prd04_models import V14ResultBundle, V14ResultBundleBody

from .contract import StrictModel, V15Failure, V15FailureCode
from .upstream import UpstreamEvidence, extract_upstream


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "docs/specs/v15/fixtures"
_V14_NAME: Final = "v14-result-bundle.json"
_V14_BUNDLE: Final = TypeAdapter(V14ResultBundle)
_ROOT_STAT: Final = ROOT.stat()
_ROOT_ID: Final = (_ROOT_STAT.st_dev, _ROOT_STAT.st_ino)


class Prd03Fixture(StrictModel):
    schema_version: Literal["v15.prd03_fixture.1"]
    prior_close_nav: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    commission: Decimal
    tax: Decimal
    spread: Decimal
    slippage: Decimal
    participation: Decimal
    borrow: Decimal
    locate: Decimal
    other_execution_cost: Decimal


def load_prd03() -> Prd03Fixture:
    return Prd03Fixture.model_validate_json(
        (FIXTURE_ROOT / "prd03.json").read_bytes())


def verify_v14_path(path: str) -> UpstreamEvidence:
    expected_parts = ("docs", "specs", "v15", "fixtures", _V14_NAME)
    if Path(path).parts != expected_parts:
        raise V15Failure(V15FailureCode.PAPER_BOUNDARY, "v14_artifact_path")
    try:
        payload = _read_v14_artifact()
        _ = parse_json(payload)
        bundle = _V14_BUNDLE.validate_json(payload)
    except (OSError, ValidationError, V11ContractError) as error:
        raise V15Failure(V15FailureCode.ARTIFACT_MALFORMED,
            str(error)) from error
    body = V14ResultBundleBody.model_validate(bundle.model_dump(
        exclude={"bundle_hash"}))
    result = bundle.result_manifest
    if canonical_hash(model_json(body)) != bundle.bundle_hash \
            or bundle.approval.approved_manifest_hash != bundle.plan.manifest_hash \
            or result.plan_manifest_hash != bundle.plan.manifest_hash \
            or result.approval_hash != bundle.approval.approval_hash \
            or result.validation_run_hash != bundle.validation_run.validation_run_hash \
            or result.holdout_run_hash != bundle.holdout_run.holdout_run_hash:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, "v14_lineage")
    verified = verify_v14_bundle(payload, ROOT)
    if verified != bundle:
        raise V15Failure(V15FailureCode.UPSTREAM_EVIDENCE, "v14_full_verify")
    return extract_upstream(verified)


def _read_v14_artifact() -> bytes:
    return read_pinned_fixture(
        f"docs/specs/v15/fixtures/{_V14_NAME}",
        ("docs", "specs", "v15", "fixtures", _V14_NAME))


def read_pinned_fixture(
    path: str, expected_parts: tuple[str, ...],
) -> bytes:
    if Path(path).parts != expected_parts:
        raise V15Failure(V15FailureCode.PAPER_BOUNDARY, "fixture_path")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory = os.open(ROOT, flags | os.O_DIRECTORY)
    artifact: int | None = None
    try:
        root_stat = os.fstat(directory)
        if (root_stat.st_dev, root_stat.st_ino) != _ROOT_ID:
            raise OSError("project root identity changed")
        for part in expected_parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        artifact = os.open(expected_parts[-1], flags, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(artifact).st_mode):
            raise OSError("v14 artifact is not a regular file")
        with os.fdopen(artifact, "rb") as stream:
            artifact = None
            return stream.read()
    except OSError as error:
        raise V15Failure(V15FailureCode.PAPER_BOUNDARY,
            "v14_artifact_path") from error
    finally:
        if artifact is not None:
            os.close(artifact)
        os.close(directory)
