#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify: uv run scripts/run_perspective_paper_cohort.py verify-fixture
# 3. Build: uv run scripts/run_perspective_paper_cohort.py build --input docs/specs/v6/fixtures/prd03-paper-cohort.json
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
from src.v6.models import ContractInvariantError, VERSION_PATTERN
from src.v6.paper_acceptance import verify_paper_fixture
from src.v6.paper_artifact import build_paper_artifact, paper_artifact_json
from src.v6.paper_fixture import load_paper_fixture
from src.v6.paper_models import PaperStopCode


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v6/fixtures/prd03-paper-cohort.json")
    input: Path = fixture
    output: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify or build an isolated V6 paper cohort artifact")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-fixture")
    _ = verify.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    build = commands.add_parser("build")
    _ = build.add_argument("--input", type=Path, required=True)
    _ = build.add_argument("--output", type=Path)
    return parser


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _default_output(candidate_id: str, candidate_version: str) -> Path:
    if re.fullmatch(r"^pcand_v6_[a-z][a-z0-9_]*$", candidate_id) is None or re.fullmatch(VERSION_PATTERN, candidate_version) is None:
        raise ContractInvariantError("paper candidate identity is not a safe path token")
    root = (_PROJECT_ROOT / "data/v6/paper_cohorts").resolve()
    output = (root / candidate_id / f"{candidate_version}.json").resolve()
    try:
        _ = output.relative_to(root)
    except ValueError as error:
        raise ContractInvariantError("paper output escapes artifact root") from error
    return output


def _verify(args: CliArgs) -> int:
    result = verify_paper_fixture(load_paper_fixture(args.fixture))
    _emit(result)
    return 0 if isinstance(result, dict) and result.get("state") == "pass" else 1


def _build(args: CliArgs) -> int:
    fixture = load_paper_fixture(args.input)
    value = fixture.paper_input
    artifact = build_paper_artifact(value, fixture.ledger)
    output = args.output or _default_output(value.candidate_id, value.candidate_version)
    if args.input.resolve() == output.resolve():
        _emit({"state": "fail", "reason": "output_must_not_replace_input"})
        return 1
    write_status = write_immutable_json(output, paper_artifact_json(artifact))
    ready = artifact.decision.stop_code is PaperStopCode.READY
    _emit({"state": "pass" if ready else "fail", "terminal_code": artifact.decision.stop_code.value, "candidate_id": value.candidate_id, "candidate_version": value.candidate_version, "artifact_hash": artifact.artifact_hash, "ledger_head_hash": artifact.ledger_head_hash, "output": str(output), "write_status": write_status.value})
    return 0 if ready else 1


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        if args.command == "verify-fixture":
            return _verify(args)
        if args.command == "build":
            return _build(args)
        return 1
    except (ArtifactConflictError, ContractInvariantError, ValidationError, OSError) as error:
        _emit({"state": "fail", "error": type(error).__name__, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
