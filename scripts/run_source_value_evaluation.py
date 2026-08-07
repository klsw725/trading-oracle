#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify: uv run scripts/run_source_value_evaluation.py verify-fixture
# 3. Build: uv run scripts/run_source_value_evaluation.py build --input docs/specs/v7/fixtures/prd03-incremental-value-evaluation.json --trust docs/specs/v7/fixtures/prd03-incremental-value-evaluation-trust.json --output /tmp/source-value.json
# ──────────────────

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import final

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.v4.models import ArtifactConflictError, JsonValue, canonical_json
from src.v7.value_acceptance import verify_value_fixture
from src.v7.value_artifact import compile_value_artifact, ensure_value_paths, verify_value_artifact, write_value_artifact
from src.v7.value_fixture import load_value_fixture, load_value_trust, parse_value_json_bytes
from src.v7.value_models import ValueContractError
from src.v7.value_trust import trust_value_fixture


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v7/fixtures/prd03-incremental-value-evaluation.json")
    trust: Path = Path("docs/specs/v7/fixtures/prd03-incremental-value-evaluation-trust.json")
    input: Path = fixture
    output: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify or build offline V7 incremental value artifacts")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-fixture")
    _ = verify.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    _ = verify.add_argument("--trust", type=Path, default=CliArgs.trust)
    build = commands.add_parser("build")
    _ = build.add_argument("--input", type=Path, required=True)
    _ = build.add_argument("--trust", type=Path, required=True)
    _ = build.add_argument("--output", type=Path, required=True)
    persisted = commands.add_parser("verify")
    _ = persisted.add_argument("--input", type=Path, required=True)
    _ = persisted.add_argument("--fixture", type=Path, required=True)
    _ = persisted.add_argument("--trust", type=Path, required=True)
    return parser


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _verify(args: CliArgs) -> int:
    report = verify_value_fixture(load_value_fixture(args.fixture), load_value_trust(args.trust))
    _emit(report)
    return 0 if isinstance(report, dict) and report.get("state") == "pass" else 1


def _build(args: CliArgs) -> int:
    if args.output is None:
        return 1
    ensure_value_paths(args.input, args.output)
    ensure_value_paths(args.trust, args.output)
    fixture = load_value_fixture(args.input)
    trust = load_value_trust(args.trust)
    context = trust_value_fixture(fixture, trust)
    artifact = compile_value_artifact(fixture, context)
    status = write_value_artifact(args.output, artifact, context)
    _emit(
        {
            "state": "pass",
            "artifact_hash": artifact.artifact_hash,
            "terminal_code": artifact.terminal_code,
            "promotion_eligible": artifact.promotion_eligible,
            "production_isolation": artifact.production_isolation,
            "output": str(args.output),
            "write_status": status.value,
        }
    )
    return 0


def _verify_persisted(args: CliArgs) -> int:
    fixture = load_value_fixture(args.fixture)
    context = trust_value_fixture(fixture, load_value_trust(args.trust))
    artifact = verify_value_artifact(parse_value_json_bytes(args.input.read_bytes()), context)
    _emit({"state": "pass", "artifact_hash": artifact.artifact_hash, "terminal_code": artifact.terminal_code})
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
            return _verify_persisted(args)
        return 1
    except (ArtifactConflictError, ValueContractError, OSError) as error:
        _emit({"state": "fail", "error": type(error).__name__, "error_code": getattr(error, "code", "MALFORMED_EVALUATION_INPUT"), "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
