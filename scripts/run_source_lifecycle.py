#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify: uv run scripts/run_source_lifecycle.py verify-fixture
# 3. Build: uv run scripts/run_source_lifecycle.py build --input docs/specs/v7/fixtures/prd04-promotion-retirement.json --trust docs/specs/v7/fixtures/prd04-promotion-retirement-trust.json --value-fixture docs/specs/v7/fixtures/prd03-incremental-value-evaluation.json --value-trust docs/specs/v7/fixtures/prd03-incremental-value-evaluation-trust.json --output /tmp/source-policy.json
# 4. Verify artifact: use the same trust arguments with verify --artifact /tmp/source-policy.json --fixture docs/specs/v7/fixtures/prd04-promotion-retirement.json
# ──────────────────

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import final

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.v4.models import ArtifactConflictError, JsonValue, canonical_json
from src.v7.source_acceptance import verify_source_fixture
from src.v7.source_context import SourceTrustInputs
from src.v7.fixture import parse_json_bytes
from src.v7.models import ProvenanceContractError
from src.v7.source_artifact import compile_source_artifact, ensure_source_paths, verify_source_artifact, write_source_artifact
from src.v7.source_fixture import load_source_fixture, load_source_trust
from src.v7.source_models import SourcePolicyError
from src.v7.source_trust import issue_source_context
from src.v7.value_fixture import load_value_fixture, load_value_trust


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v7/fixtures/prd04-promotion-retirement.json")
    trust: Path = Path("docs/specs/v7/fixtures/prd04-promotion-retirement-trust.json")
    value_fixture: Path = Path("docs/specs/v7/fixtures/prd03-incremental-value-evaluation.json")
    value_trust: Path = Path("docs/specs/v7/fixtures/prd03-incremental-value-evaluation-trust.json")
    input: Path = fixture
    output: Path | None = None
    artifact: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify or build offline V7 source lifecycle policies")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-fixture")
    _ = verify.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    _ = verify.add_argument("--trust", type=Path, default=CliArgs.trust)
    _ = verify.add_argument("--value-fixture", type=Path, default=CliArgs.value_fixture)
    _ = verify.add_argument("--value-trust", type=Path, default=CliArgs.value_trust)
    build = commands.add_parser("build")
    _ = build.add_argument("--input", type=Path, required=True)
    _ = build.add_argument("--trust", type=Path, required=True)
    _ = build.add_argument("--value-fixture", type=Path, required=True)
    _ = build.add_argument("--value-trust", type=Path, required=True)
    _ = build.add_argument("--output", type=Path, required=True)
    verify_artifact = commands.add_parser("verify")
    _ = verify_artifact.add_argument("--artifact", type=Path, required=True)
    _ = verify_artifact.add_argument("--fixture", type=Path, required=True)
    _ = verify_artifact.add_argument("--trust", type=Path, required=True)
    _ = verify_artifact.add_argument("--value-fixture", type=Path, required=True)
    _ = verify_artifact.add_argument("--value-trust", type=Path, required=True)
    return parser


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _trust_inputs(args: CliArgs) -> SourceTrustInputs:
    return SourceTrustInputs(load_source_trust(args.trust), load_value_fixture(args.value_fixture), load_value_trust(args.value_trust))


def _verify(args: CliArgs) -> int:
    report = verify_source_fixture(load_source_fixture(args.fixture), _trust_inputs(args))
    _emit(report)
    return 0 if isinstance(report, dict) and report.get("state") == "pass" else 1


def _build(args: CliArgs) -> int:
    if args.output is None:
        return 1
    ensure_source_paths(args.input, args.output)
    ensure_source_paths(args.trust, args.output)
    ensure_source_paths(args.value_fixture, args.output)
    ensure_source_paths(args.value_trust, args.output)
    fixture = load_source_fixture(args.input)
    context = issue_source_context(fixture, _trust_inputs(args))
    artifact = compile_source_artifact(fixture, context)
    status = write_source_artifact(args.output, artifact, context)
    _emit({"state": "pass", "artifact_hash": artifact.artifact_hash, "terminal_code": artifact.terminal_code, "production_isolation": artifact.production_isolation, "output": str(args.output), "write_status": status.value})
    return 0


def _verify_artifact(args: CliArgs) -> int:
    if args.artifact is None:
        return 1
    fixture = load_source_fixture(args.fixture)
    context = issue_source_context(fixture, _trust_inputs(args))
    try:
        value = parse_json_bytes(args.artifact.read_bytes())
    except ProvenanceContractError as error:
        raise SourcePolicyError("MALFORMED_SOURCE_POLICY", error.detail) from error
    artifact = verify_source_artifact(value, context)
    _emit({"state": "pass", "artifact_hash": artifact.artifact_hash, "terminal_code": artifact.terminal_code, "production_isolation": artifact.production_isolation})
    return 0


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        if args.command == "verify-fixture":
            return _verify(args)
        if args.command == "build":
            return _build(args)
        if args.command == "verify":
            return _verify_artifact(args)
        return 1
    except (ArtifactConflictError, SourcePolicyError, OSError) as error:
        _emit({"state": "fail", "error": type(error).__name__, "error_code": getattr(error, "code", "MALFORMED_SOURCE_POLICY"), "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
