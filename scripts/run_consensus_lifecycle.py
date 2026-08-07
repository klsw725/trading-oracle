#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify: uv run scripts/run_consensus_lifecycle.py verify-fixture
# 3. Build: uv run scripts/run_consensus_lifecycle.py build --input docs/specs/v6/fixtures/prd04-consensus-lifecycle.json
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
from src.v6.lifecycle_acceptance import verify_lifecycle_fixture
from src.v6.lifecycle_artifact import ConsensusLifecycleArtifact, build_lifecycle_artifact
from src.v6.lifecycle_fixture import load_lifecycle_fixture
from src.v6.models import ContractInvariantError, JsonBoundary, VERSION_PATTERN


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v6/fixtures/prd04-consensus-lifecycle.json")
    input: Path = fixture
    output: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify or build an offline V6 consensus lifecycle artifact")
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
        raise ContractInvariantError("lifecycle candidate identity is not a safe path token")
    root = (_PROJECT_ROOT / "data/v6/consensus_lifecycle").resolve()
    output = (root / candidate_id / f"{candidate_version}.json").resolve()
    try:
        _ = output.relative_to(root)
    except ValueError as error:
        raise ContractInvariantError("lifecycle output escapes artifact root") from error
    return output


def _verify(args: CliArgs) -> int:
    result = verify_lifecycle_fixture(load_lifecycle_fixture(args.fixture))
    _emit(result)
    return 0 if isinstance(result, dict) and result.get("state") == "pass" else 1


def _build(args: CliArgs) -> int:
    fixture = load_lifecycle_fixture(args.input)
    context = fixture.artifacts[0].compiler_context
    built: list[ConsensusLifecycleArtifact] = []
    for operation in fixture.operations:
        artifact = build_lifecycle_artifact(operation, context)
        built.append(artifact)
        context = context.model_copy(update={"policy_registry": artifact.history.policy_registry})
    artifacts = tuple(built)
    artifact = artifacts[0]
    identity = fixture.operations[0].lifecycle_input
    output = args.output or _default_output(identity.candidate_id, identity.candidate_version)
    if args.input.resolve() == output.resolve():
        _emit({"state": "fail", "reason": "output_must_not_replace_input"})
        return 1
    bundle = JsonBoundary.model_validate([item.model_dump(mode="json") for item in artifacts]).root
    write_status = write_immutable_json(output, bundle)
    _emit({"state": "pass", "operation_count": len(artifacts), "result_codes": [item.decision.result_code.value for item in artifacts], "candidate_id": identity.candidate_id, "candidate_version": identity.candidate_version, "artifact_hash": artifact.artifact_hash, "runtime_adoption": artifact.runtime_adoption, "output": str(output), "write_status": write_status.value})
    return 0


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
