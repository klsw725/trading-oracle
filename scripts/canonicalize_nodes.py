#!/usr/bin/env python3
"""Causal node canonicalization migration CLI."""

import argparse
from pathlib import Path
import sys
from typing import final

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.causal.canonical_acceptance import (
    CanonicalFixtureError,
    load_fixture,
    verify_fixture,
)
from src.causal.canonical_models import LegacyGraphParseError, parse_legacy_graph
from src.causal.canonicalizer import canonicalize
from src.v4.models import ArtifactConflictError, JsonValue, canonical_json, write_immutable_json


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v5/fixtures/prd01-node-canonicalization.json")
    input: Path = Path("data/causal_graph.json")
    output: Path = Path("data/causal_graph_canonical.json")
    canonicalized_at: str | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canonicalize legacy causal graph nodes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-fixture")
    _ = verify.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    migrate = subparsers.add_parser("migrate")
    _ = migrate.add_argument("--input", type=Path, default=CliArgs.input)
    _ = migrate.add_argument("--output", type=Path, default=CliArgs.output)
    _ = migrate.add_argument("--canonicalized-at")
    return parser


def _load_json(path: Path) -> JsonValue:
    return load_fixture(path)


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _passed(value: JsonValue) -> bool:
    match value:  # noqa: MATCH_OK - CLI report accepts only object-shaped JSON
        case dict() as record:
            return record.get("state") == "pass"
        case _:
            return False


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        match args.command:  # noqa: MATCH_OK - argparse command is an open string boundary
            case "verify-fixture":
                result = verify_fixture(load_fixture(args.fixture))
                _emit(result)
                return 0 if _passed(result) else 1
            case "migrate":
                if args.input.resolve() == args.output.resolve():
                    _emit({"state": "fail", "reason": "output_must_not_replace_legacy"})
                    return 1
                result = canonicalize(
                    parse_legacy_graph(_load_json(args.input)),
                    canonicalized_at=args.canonicalized_at,
                )
                write_status = write_immutable_json(args.output, result.artifact)
                _emit(
                    {
                        "state": "pass",
                        "output": str(args.output),
                        "write_status": write_status.value,
                    }
                )
                return 0
            case None:
                return 1
            case unreachable:
                raise AssertionError(f"unsupported command: {unreachable}")
    except (CanonicalFixtureError, LegacyGraphParseError, ArtifactConflictError, OSError) as error:
        _emit({"state": "fail", "error": type(error).__name__, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
