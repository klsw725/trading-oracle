#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Verify: uv run scripts/verify_v7_spec.py verify
# 2. Mutations: uv run scripts/verify_v7_spec.py verify-fixture
# ──────────────────

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Final, NoReturn, final, override

_PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.v4.models import JsonValue, canonical_json
from src.v7.spec_acceptance import verify_spec_fixture
from src.v7.spec_models import SpecVerificationError
from src.v7.spec_parser import read_spec_bundle, verify_spec_bundle


@final
class CliArgs:
    command: str | None = None
    spec: Path = Path("docs/specs/v7/SPEC.md")


class JsonArgumentParser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:
        _emit({"state": "fail", "error": "ArgumentError", "detail": message})
        raise SystemExit(1)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description="Verify the canonical V7 Markdown SPEC")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    _ = verify.add_argument("--spec", type=Path, default=CliArgs.spec)
    fixture = commands.add_parser("verify-fixture")
    _ = fixture.add_argument("--spec", type=Path, default=CliArgs.spec)
    return parser


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _verify(spec_path: Path) -> JsonValue:
    bundle = read_spec_bundle(spec_path)
    report = verify_spec_bundle(bundle)
    return {
        "state": "pass",
        "schema_version": report.schema_version,
        "json_block_count": report.json_block_count,
        "linked_prd_count": report.linked_prd_count,
        "spec": str(bundle.spec_path.relative_to(_PROJECT_ROOT)),
    }


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        result = verify_spec_fixture(args.spec) if args.command == "verify-fixture" else _verify(args.spec)
        _emit(result)
        return 0 if isinstance(result, dict) and result.get("state") == "pass" else 1
    except SpecVerificationError as error:
        _emit(
            {
                "state": "fail",
                "error": type(error).__name__,
                "error_code": error.code,
                "detail": error.detail,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
