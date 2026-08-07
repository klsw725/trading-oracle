#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14.2"
# dependencies = ["pydantic>=2,<3"]
# ///

# ─── How to run ───
# 1. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Verify: uv run scripts/run_source_quality.py verify-fixture
# 3. Build: uv run scripts/run_source_quality.py build --input docs/specs/v7/fixtures/prd02-quality-freshness-dedup.json --trust docs/specs/v7/fixtures/prd02-quality-freshness-dedup-trust.json --output /tmp/source-quality.json
# ──────────────────

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import final

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.v4.models import ArtifactConflictError, JsonValue, canonical_json
from src.v7.quality_acceptance import verify_quality_fixture
from src.v7.quality_artifact import build_quality_artifacts, ensure_quality_paths, verify_quality_artifact, write_quality_artifacts
from src.v7.quality_fixture import load_quality_fixture, load_quality_trust, parse_quality_json_bytes
from src.v7.quality_models import QualityContractError
from src.v7.quality_registry import trust_quality_fixture


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v7/fixtures/prd02-quality-freshness-dedup.json")
    trust: Path = Path("docs/specs/v7/fixtures/prd02-quality-freshness-dedup-trust.json")
    input: Path = fixture
    output: Path | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify or build offline V7 source quality artifacts")
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
    report = verify_quality_fixture(load_quality_fixture(args.fixture), load_quality_trust(args.trust))
    _emit(report)
    return 0 if isinstance(report, dict) and report.get("state") == "pass" else 1


def _build(args: CliArgs) -> int:
    if args.output is None:
        return 1
    ensure_quality_paths(args.input, args.output)
    ensure_quality_paths(args.trust, args.output)
    fixture = load_quality_fixture(args.input)
    trust = load_quality_trust(args.trust)
    artifacts = build_quality_artifacts(fixture, trust)
    status = write_quality_artifacts(args.output, artifacts, fixture, trust)
    _emit(
        {
            "state": "pass",
            "artifact_count": len(artifacts),
            "artifact_hashes": [item.artifact_hash for item in artifacts],
            "output": str(args.output),
            "runtime_adoption": "absent",
            "write_status": status.value,
        }
    )
    return 0


def _verify_persisted(args: CliArgs) -> int:
    value = parse_quality_json_bytes(args.input.read_bytes())
    if not isinstance(value, list) or len(value) != 2:
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "persisted artifact must contain primary and fallback")
    fixture = load_quality_fixture(args.fixture)
    trust = load_quality_trust(args.trust)
    contexts = (
        trust_quality_fixture(fixture.primary_evidence, trust.primary, fixture.primary_input.generated_at),
        trust_quality_fixture(fixture.fallback_evidence, trust.fallback, fixture.fallback_input.generated_at),
    )
    artifacts = tuple(verify_quality_artifact(item, context) for item, context in zip(value, contexts, strict=True))
    _emit({"state": "pass", "artifact_count": len(artifacts), "artifact_hashes": [item.artifact_hash for item in artifacts]})
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
    except (ArtifactConflictError, QualityContractError, OSError) as error:
        _emit(
            {
                "state": "fail",
                "error": type(error).__name__,
                "error_code": getattr(error, "code", "MALFORMED_QUALITY_PAYLOAD"),
                "detail": str(error),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
