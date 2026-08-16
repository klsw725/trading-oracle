from __future__ import annotations

import argparse
from enum import StrEnum, unique
from pathlib import Path
from typing import NoReturn, override

from pydantic import ValidationError
from src.v14.failure import V14Failure
from src.v11.canonical import model_json
from src.v4.models import JsonValue, canonical_json

from .acceptance import run_acceptance
from .contract import V15Failure, V15FailureCode
from .operation_build import build_operation_bundle
from .operation_fixture import load_operation_source
from .operation_verify import verify_operation_bundle
from .prd01_acceptance import run_acceptance as run_prd01
from .prd02_acceptance import run_acceptance as run_prd02
from .prd03_acceptance import run_acceptance as run_prd03
from .prd04_acceptance import run_acceptance as run_prd04


@unique
class Command(StrEnum):
    ACCEPTANCE = "acceptance"
    BUILD = "build"
    VERIFY = "verify"
    PRD01_ACCEPTANCE = "prd01-acceptance"
    PRD02_ACCEPTANCE = "prd02-acceptance"
    PRD03_ACCEPTANCE = "prd03-acceptance"
    PRD04_ACCEPTANCE = "prd04-acceptance"


def _failure_json(error: V15Failure) -> JsonValue:
    return {"state": "fail", "error": {
        "code": error.code.value, "detail": error.detail}}


class JsonArgumentParser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:
        error = V15Failure(V15FailureCode.CLI_ARGUMENT, message)
        print(canonical_json(_failure_json(error)).decode())
        raise SystemExit(1)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="python -m src.v15.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in Command:
        command_parser = commands.add_parser(command.value)
        if command is Command.BUILD:
            _ = command_parser.add_argument("--input", required=True)
        if command is Command.VERIFY:
            _ = command_parser.add_argument("--artifact", required=True)
    return parser


def _command(args: argparse.Namespace) -> Command:
    value = getattr(args, "command", None)
    if not isinstance(value, str):
        raise V15Failure(V15FailureCode.CLI_ARGUMENT, "command")
    return Command(value)


def _path(args: argparse.Namespace, name: str) -> Path:
    value = getattr(args, name, None)
    if not isinstance(value, str):
        raise V15Failure(V15FailureCode.CLI_ARGUMENT, f"--{name}")
    return Path(value)


def _dispatch(command: Command, args: argparse.Namespace) -> JsonValue:
    match command:  # noqa: MATCH_OK - Command enum is exhaustively covered
        case Command.ACCEPTANCE:
            return run_acceptance()
        case Command.BUILD:
            return model_json(build_operation_bundle(
                load_operation_source(_path(args, "input"))))
        case Command.VERIFY:
            bundle = verify_operation_bundle(_path(args, "artifact").read_bytes())
            return {"state": "pass", "bundle_hash": bundle.bundle_hash,
                "replay_hash": bundle.replay.replay_hash}
        case Command.PRD01_ACCEPTANCE:
            return run_prd01()
        case Command.PRD02_ACCEPTANCE:
            return run_prd02()
        case Command.PRD03_ACCEPTANCE:
            return run_prd03()
        case Command.PRD04_ACCEPTANCE:
            return run_prd04()


def main() -> int:
    try:
        args = _parser().parse_args()
        report = _dispatch(_command(args), args)
        print(canonical_json(report).decode())
        return 1 if isinstance(report, dict) and report.get("state") == "fail" else 0
    except V15Failure as error:
        print(canonical_json(_failure_json(error)).decode())
        return 1
    except V14Failure as error:
        failure = V15Failure(V15FailureCode.ARTIFACT_MALFORMED, str(error))
        print(canonical_json(_failure_json(failure)).decode())
        return 1
    except (OSError, ValidationError, ValueError) as error:
        failure = V15Failure(V15FailureCode.ARTIFACT_MALFORMED, str(error))
        print(canonical_json(_failure_json(failure)).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
