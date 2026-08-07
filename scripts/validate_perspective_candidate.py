#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify: uv run scripts/validate_perspective_candidate.py verify-fixture
# 3. Build: uv run scripts/validate_perspective_candidate.py build --input candidate.json
# ──────────────────

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import final

from pydantic import ValidationError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.v4.models import ArtifactConflictError, JsonValue, canonical_json, write_immutable_json
from src.v6.candidate_contract import (
    CandidateContractError,
    artifact_json,
    build_candidate_artifact,
    parse_candidate,
)
from src.v6.candidate_fixture import CandidateFixtureError, load_fixture, verify_fixture
from src.v6.models import JsonBoundary, RejectionCode, VERSION_PATTERN


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path(
        "docs/specs/v6/fixtures/prd01-perspective-candidate-contract.json"
    )
    input: Path = fixture
    output: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an offline V6 perspective candidate contract"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-fixture")
    _ = verify.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    build = subparsers.add_parser("build")
    _ = build.add_argument("--input", type=Path, required=True)
    _ = build.add_argument("--output", type=Path)
    return parser


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _load_json(path: Path) -> JsonValue:
    try:
        return JsonBoundary.model_validate_json(path.read_bytes()).root
    except ValidationError as error:
        raise CandidateContractError(
            code=RejectionCode.UNTYPED,
            detail=str(error),
        ) from error


def _candidate_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return value.get("base_candidate", value)
    return value


def _default_output(candidate_id: str, candidate_version: str) -> Path:
    if (
        re.fullmatch(r"^pcand_v6_[a-z][a-z0-9_]*$", candidate_id) is None
        or re.fullmatch(VERSION_PATTERN, candidate_version) is None
    ):
        raise CandidateContractError(
            code=RejectionCode.IDENTITY,
            detail="candidate identity is not a safe artifact path token",
        )
    root = (_PROJECT_ROOT / "data/v6/perspective_candidates").resolve()
    output = (root / candidate_id / f"{candidate_version}.json").resolve()
    try:
        _ = output.relative_to(root)
    except ValueError as error:
        raise CandidateContractError(
            code=RejectionCode.IDENTITY,
            detail="default output escapes perspective candidate artifact root",
        ) from error
    return output


def _verify(args: CliArgs) -> int:
    result = verify_fixture(load_fixture(args.fixture))
    _emit(result)
    return 0 if isinstance(result, dict) and result.get("state") == "pass" else 1


def _build(args: CliArgs) -> int:
    candidate = parse_candidate(_candidate_value(_load_json(args.input)))
    identity = candidate.candidate_identity
    output = args.output or _default_output(
        identity.candidate_id, identity.candidate_version
    )
    if args.input.resolve() == output.resolve():
        _emit({"state": "fail", "reason": "output_must_not_replace_input"})
        return 1
    artifact = build_candidate_artifact(candidate)
    write_status = write_immutable_json(output, artifact_json(artifact))
    accepted = artifact.decision.accepted_for_evaluation
    _emit(
        {
            "state": "pass" if accepted else "fail",
            "accepted_for_evaluation": accepted,
            "rejection_code": (
                artifact.decision.rejection_code.value
                if artifact.decision.rejection_code is not None
                else None
            ),
            "output": str(output),
            "write_status": write_status.value,
            "artifact_hash": artifact.artifact_hash,
        }
    )
    return 0 if accepted else 1


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        if args.command == "verify-fixture":
            return _verify(args)
        if args.command == "build":
            return _build(args)
        return 1
    except CandidateContractError as error:
        _emit(
            {
                "state": "fail",
                "error": type(error).__name__,
                "rejection_code": error.code.value,
                "detail": error.detail,
            }
        )
        return 1
    except (CandidateFixtureError, ArtifactConflictError, OSError) as error:
        _emit({"state": "fail", "error": type(error).__name__, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
