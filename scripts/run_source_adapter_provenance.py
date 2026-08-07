#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify: uv run scripts/run_source_adapter_provenance.py verify-fixture
# 3. Build: uv run scripts/run_source_adapter_provenance.py build --input docs/specs/v7/fixtures/prd01-source-adapter-provenance.json --output /tmp/source-provenance.json
# ──────────────────

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import final

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.v7 import acceptance
from src.v7.artifact import build_from_fixture, ensure_distinct_paths, write_artifact
from src.v7.fixture import load_fixture
from src.v7.models import ProvenanceContractError
from src.v4.models import ArtifactConflictError, JsonValue, canonical_json


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v7/fixtures/prd01-source-adapter-provenance.json")
    input: Path = fixture
    output: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or build an offline V7 source provenance artifact"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-fixture")
    _ = verify.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    build = commands.add_parser("build")
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
            report = acceptance.verify_fixture(load_fixture(args.fixture))
            _emit(report)
            return 0 if isinstance(report, dict) and report.get("state") == "pass" else 1
        if args.command == "build":
            if args.output is None:
                return 1
            fixture = load_fixture(args.input)
            ensure_distinct_paths(args.input, args.output)
            compiled = build_from_fixture(fixture)
            status = write_artifact(args.output, compiled)
            _emit(
                {
                    "state": "pass",
                    "output": str(args.output),
                    "provenance_hash": compiled.artifact.provenance_hash,
                    "trusted_manifest_root": compiled.trusted_context.trusted_root,
                    "runtime_adoption": "absent",
                    "write_status": status.value,
                }
            )
            return 0
        return 1
    except (ArtifactConflictError, ProvenanceContractError, OSError) as error:
        _emit(
            {
                "state": "fail",
                "error": type(error).__name__,
                "error_code": getattr(error, "code", "MALFORMED_PAYLOAD"),
                "detail": str(error),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
