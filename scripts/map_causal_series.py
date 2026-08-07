#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys
from typing import final

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.causal.series_mapping import (
    MappingInputError,
    build_mapping_artifact,
    parse_mapping_input,
)
from src.causal.series_mapping_acceptance import (
    MappingFixtureError,
    load_json,
    verify_fixture,
)
from src.v4.models import ArtifactConflictError, JsonValue, canonical_json, write_immutable_json


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v5/fixtures/prd02-series-mapping-provenance.json")
    input: Path = fixture
    output: Path = Path("data/causal_series_mapping.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build canonical-node series mappings")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-fixture")
    _ = verify.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    build = subparsers.add_parser("build")
    _ = build.add_argument("--input", type=Path, default=CliArgs.input)
    _ = build.add_argument("--output", type=Path, default=CliArgs.output)
    return parser


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _passed(value: JsonValue) -> bool:
    return isinstance(value, dict) and value.get("state") == "pass"


def _build_input(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return value.get("build_input", value)
    return value


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        if args.command == "verify-fixture":
            result = verify_fixture(load_json(args.fixture))
            _emit(result)
            return 0 if _passed(result) else 1
        if args.command == "build":
            if args.input.resolve() == args.output.resolve():
                _emit({"state": "fail", "reason": "output_must_not_replace_input"})
                return 1
            build_input = parse_mapping_input(_build_input(load_json(args.input)))
            result = build_mapping_artifact(build_input)
            status = write_immutable_json(args.output, result.artifact)
            _emit({"state": "pass", "output": str(args.output), "write_status": status.value})
            return 0
        return 1
    except (
        MappingFixtureError,
        MappingInputError,
        ArtifactConflictError,
        OSError,
    ) as error:
        _emit({"state": "fail", "error": type(error).__name__, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
