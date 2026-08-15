from __future__ import annotations

import argparse
import os
from enum import StrEnum, unique
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from src.v11.canonical import model_json
from src.v4.models import JsonValue, canonical_json
from src.v13.acceptance import run_acceptance
from src.v13.adapter import compile_source, load_descriptor
from src.v13.integration_probe import run_integration_probe
from src.v13.models import RecordedCandidateFixture
from src.v13.policy import build_policy
from src.v13.prd01_contract import run_acceptance as run_prd01
from src.v13.prd01_fixture import manifest_for
from src.v13.prd02_contract import run_acceptance as run_prd02
from src.v13.prd03_contract import run_acceptance as run_prd03
from src.v13.prd04_bundle import build_bundle
from src.v13.prd04_verifier import verify_bundle
from src.v13.public import replay_bundle, shadow_bundle
from src.v13.selection import run_router


_JSON: Final = TypeAdapter[JsonValue](JsonValue)


@unique
class Command(StrEnum):
    ACCEPTANCE = "acceptance"
    PRD01_BUILD = "prd01-build"
    PRD01_ACCEPTANCE = "prd01-acceptance"
    PRD02_ACCEPTANCE = "prd02-acceptance"
    PRD03_ACCEPTANCE = "prd03-acceptance"
    PRD04_BUILD = "prd04-build"
    PRD04_VERIFY = "prd04-verify"
    REPLAY = "replay"
    SHADOW = "shadow"
    ROUTER = "router"
    CODEX_INTEGRATION = "codex-integration-probe"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.v13.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    _ = commands.add_parser(Command.ACCEPTANCE.value)
    prd01_build = commands.add_parser(Command.PRD01_BUILD.value)
    _ = prd01_build.add_argument("--input", required=True)
    _ = commands.add_parser(Command.PRD01_ACCEPTANCE.value)
    _ = commands.add_parser(Command.PRD02_ACCEPTANCE.value)
    _ = commands.add_parser(Command.PRD03_ACCEPTANCE.value)
    prd04_build = commands.add_parser(Command.PRD04_BUILD.value)
    _ = prd04_build.add_argument("--input", required=True)
    for name in (Command.PRD04_VERIFY, Command.REPLAY, Command.SHADOW, Command.ROUTER):
        artifact = commands.add_parser(name.value)
        _ = artifact.add_argument("--artifact", required=True)
    _ = commands.add_parser(Command.CODEX_INTEGRATION.value)
    return parser


def _path(args: argparse.Namespace, field: str) -> Path:
    value = getattr(args, field, None)
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError(f"--{field} requires a path")
    return Path(value)


def _dispatch(command: Command, args: argparse.Namespace) -> JsonValue:
    match command:  # noqa: MATCH_OK - Command enum is exhaustively covered
        case Command.ACCEPTANCE:
            return run_acceptance()
        case Command.PRD01_BUILD:
            fixture = RecordedCandidateFixture.model_validate_json(
                _path(args, "input").read_bytes())
            return model_json(run_router(manifest_for(fixture, build_policy())))
        case Command.PRD01_ACCEPTANCE:
            return _JSON.validate_python(run_prd01())
        case Command.PRD02_ACCEPTANCE:
            return _JSON.validate_python(run_prd02())
        case Command.PRD03_ACCEPTANCE:
            return _JSON.validate_python(run_prd03())
        case Command.PRD04_BUILD:
            descriptor_path = _path(args, "input")
            source = compile_source(load_descriptor(descriptor_path), Path.cwd())
            return model_json(build_bundle(source))
        case Command.PRD04_VERIFY:
            return {"state": "pass", "bundle_hash": verify_bundle(
                _path(args, "artifact").read_bytes()).bundle_hash}
        case Command.REPLAY:
            bundle = verify_bundle(_path(args, "artifact").read_bytes())
            return model_json(replay_bundle(bundle))
        case Command.SHADOW | Command.ROUTER:
            bundle = verify_bundle(_path(args, "artifact").read_bytes())
            return model_json(shadow_bundle(bundle))
        case Command.CODEX_INTEGRATION:
            enabled = os.environ.get("TRADING_ORACLE_V13_CODEX_INTEGRATION") == "1"
            return _JSON.validate_python(run_integration_probe(enabled))


def _command(args: argparse.Namespace) -> Command:
    value = getattr(args, "command", None)
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError("command is required")
    return Command(value)


def main() -> int:
    args = _parser().parse_args()
    report = _dispatch(_command(args), args)
    print(canonical_json(report).decode())
    return 0 if not isinstance(report, dict) or report.get("state") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
