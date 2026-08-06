#!/usr/bin/env python3
"""Offline JSON CLI for the Trading Oracle v4 contract engine."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Final, NoReturn

_PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pydantic import ValidationError

from src.v4.capture_cli import CapturePayloadError, capture_report
from src.v4.fixture_runner import (
    FixtureParseError,
    attribution_report,
    calibration_report,
    evidence_report,
    legacy_report,
    load_fixture,
    measurement_report,
    replay_report,
    verify_fixture,
)
from src.v4.market_context import MarketContextParseError
from src.v4.measurement import MeasurementParseError
from src.v4.models import ArtifactConflictError, JsonValue, write_immutable_json

_DEFAULT_FIXTURE: Final = Path("docs/specs/v4/fixtures/v4-offline.json")
_EXIT_CODES: Final = {"pass": 0, "success": 0, "fail": 1, "error": 1, "inconclusive": 2}


class UnsupportedCommandError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print(json.dumps({"state": "fail", "error": {"type": "ArgumentError", "message": message}}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        raise SystemExit(1)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description="Trading Oracle v4 offline contract CLI")
    parser.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE, help="offline fixture JSON")
    parser.add_argument("--output-dir", type=Path, help="write an immutable result artifact under this directory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-fixture", help="run deterministic Phase 22-29 checks")
    capture = subparsers.add_parser("capture", help="write a native v4 snapshot from captured run input")
    capture.add_argument("--input", type=Path, required=True, help="native capture input JSON")
    subparsers.add_parser("measure", help="evaluate fixture market contexts and measurements")
    legacy = subparsers.add_parser("legacy-audit", help="audit legacy snapshots without mutation")
    legacy.add_argument("--source-root", type=Path, default=Path("data/snapshots"))
    subparsers.add_parser("attribution", help="validate the five-action denominator")
    subparsers.add_parser("replay", help="run offline replay and checkpoint checks")
    subparsers.add_parser("calibration", help="calculate fixture Brier and ECE metrics")
    evidence = subparsers.add_parser("evidence-gate", help="evaluate complete or provenance-insufficient evidence")
    evidence.add_argument("--provenance", choices=("complete", "insufficient"), default="complete")
    return parser


def _run(args: argparse.Namespace) -> JsonValue:
    command = str(args.command)
    if command == "capture":
        if args.output_dir is None:
            raise CapturePayloadError(Path(args.input), "--output-dir is required")
        return capture_report(args.input, args.output_dir)
    if command == "legacy-audit":
        return legacy_report(args.source_root)
    fixture = load_fixture(args.fixture)
    if command == "verify-fixture":
        return verify_fixture(fixture, Path("data/snapshots"))
    if command == "measure":
        return measurement_report(fixture)
    if command == "attribution":
        return attribution_report(fixture)
    if command == "replay":
        return replay_report(fixture)
    if command == "calibration":
        return calibration_report(fixture)
    if command == "evidence-gate":
        return evidence_report(fixture, args.provenance)
    raise UnsupportedCommandError(command)


def main() -> int:  # noqa: BROAD_EXCEPT_OK
    parser = _parser()
    try:
        args = parser.parse_args()
        result = _run(args)
        if args.output_dir is not None and args.command != "capture":
            write_immutable_json(args.output_dir / f"{args.command}.json", result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        state = result.get("state") if isinstance(result, dict) else "error"
        return _EXIT_CODES.get(str(state), 1)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError, CapturePayloadError, FixtureParseError, MarketContextParseError, MeasurementParseError, ArtifactConflictError) as error:
        print(json.dumps({"state": "fail", "error": {"type": type(error).__name__, "message": str(error)}}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1
    except Exception as error:  # noqa: BROAD_EXCEPT_OK
        print(json.dumps({"state": "error", "error": {"type": type(error).__name__, "message": str(error)}}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
