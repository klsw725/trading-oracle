#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys
from typing import final

from pydantic import ValidationError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.causal.statistical_acceptance import load_fixture, verify_fixture
from src.causal.statistical_models import VERIFICATION_INPUT_ADAPTER
from src.causal.statistical_pipeline import build_verification_artifact
from src.v4.models import ArtifactConflictError, JsonValue, canonical_json, write_immutable_json


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v5/fixtures/prd03-statistical-verification.json")
    input: Path = Path("data/causal_statistical_verification_input.json")
    output: Path = Path("data/causal_statistical_verification.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify approved canonical causal pairs statistically")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fixture = subparsers.add_parser("verify-fixture")
    _ = fixture.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    build = subparsers.add_parser("build")
    _ = build.add_argument("--input", type=Path, required=True)
    _ = build.add_argument("--output", type=Path, required=True)
    return parser


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        if args.command == "verify-fixture":
            result = verify_fixture(load_fixture(args.fixture))
            _emit(result)
            return 0 if isinstance(result, dict) and result.get("state") == "pass" else 1
        if args.command == "build":
            if args.input.resolve() == args.output.resolve():
                _emit({"state": "fail", "reason": "output_must_not_replace_input"})
                return 1
            build_input = VERIFICATION_INPUT_ADAPTER.validate_json(args.input.read_bytes())
            artifact = build_verification_artifact(build_input).artifact
            status = write_immutable_json(args.output, artifact)
            _emit({"state": "pass", "output": str(args.output), "write_status": status.value})
            return 0
        return 1
    except (ValidationError, ArtifactConflictError, OSError, ValueError, KeyError) as error:
        _emit({"state": "fail", "error": type(error).__name__, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
