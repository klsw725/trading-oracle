from __future__ import annotations

import argparse
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, NoReturn, override

from pydantic import TypeAdapter, ValidationError
from src.v11.canonical import model_json
from src.v4.models import JsonValue, canonical_json

from .acceptance import run_acceptance
from .contract import V14ContractError
from .failure import V14Failure, V14FailureCode
from .fixture import Prd01Fixture
from .integrity import verify_bundle
from .pipeline import build_prd01
from .prd01_contract import run_acceptance as run_prd01
from .prd02_contract import run_acceptance as run_prd02
from .prd02_fixture import load_prd02_fixture
from .prd02_pipeline import build_prd02_validation_from
from .prd03_contract import run_acceptance as run_prd03
from .prd03_pipeline import build_prd03_segment_from
from .prd04_bundle import build_prd04
from .prd04_contract import run_acceptance as run_prd04
from .prd04_models import HoldoutHistory
from .prd04_source_models import Prd04Source
from .series_models import CostFixture
from .verdict_models import Prd03Fixture
from .series_models import ResearchSegment


_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def _failure_json(error: V14Failure) -> JsonValue:
    return {"state": "fail", "error": {
        "code": error.code.value, "detail": error.detail}}


class JsonArgumentParser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:
        failure = V14Failure(V14FailureCode.CLI_ARGUMENT, message)
        print(canonical_json(_failure_json(failure)).decode())
        raise SystemExit(1)


@unique
class Command(StrEnum):
    ACCEPTANCE = "acceptance"
    PRD01_BUILD = "prd01-build"
    PRD01_ACCEPTANCE = "prd01-acceptance"
    PRD02_BUILD = "prd02-build"
    PRD02_ACCEPTANCE = "prd02-acceptance"
    PRD03_BUILD = "prd03-build"
    PRD03_ACCEPTANCE = "prd03-acceptance"
    PRD04_BUILD = "prd04-build"
    PRD04_VERIFY = "prd04-verify"
    PRD04_ACCEPTANCE = "prd04-acceptance"


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="python -m src.v14.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    _ = commands.add_parser(Command.ACCEPTANCE.value)
    for command in (Command.PRD01_BUILD, Command.PRD02_BUILD,
            Command.PRD03_BUILD):
        build = commands.add_parser(command.value)
        _ = build.add_argument("--input", required=True)
    prd04 = commands.add_parser(Command.PRD04_BUILD.value)
    _ = prd04.add_argument("--input", required=True)
    _ = prd04.add_argument("--history", required=True)
    for command in (Command.PRD01_ACCEPTANCE, Command.PRD02_ACCEPTANCE,
            Command.PRD03_ACCEPTANCE, Command.PRD04_ACCEPTANCE):
        _ = commands.add_parser(command.value)
    verify = commands.add_parser(Command.PRD04_VERIFY.value)
    _ = verify.add_argument("--artifact", required=True)
    return parser


def _path(args: argparse.Namespace, name: str) -> Path:
    value = getattr(args, name, None)
    if not isinstance(value, str):
        raise V14Failure(V14FailureCode.ARTIFACT_MALFORMED, f"--{name}")
    return Path(value)


def _dispatch(command: Command, args: argparse.Namespace) -> JsonValue:
    match command:  # noqa: MATCH_OK - Command enum is exhaustively covered
        case Command.ACCEPTANCE:
            return run_acceptance()
        case Command.PRD01_BUILD:
            fixture = Prd01Fixture.model_validate_json(_path(args, "input").read_bytes())
            return model_json(build_prd01(fixture))
        case Command.PRD01_ACCEPTANCE:
            return _JSON.validate_python(run_prd01())
        case Command.PRD02_BUILD:
            fixture = CostFixture.model_validate_json(_path(args, "input").read_bytes())
            prd01 = build_prd01(Prd01Fixture.model_validate_json(
                Path("docs/specs/v14/fixtures/prd01-input.json").read_bytes()))
            return model_json(build_prd02_validation_from(
                prd01.plan, prd01.selection, fixture))
        case Command.PRD02_ACCEPTANCE:
            return _JSON.validate_python(run_prd02())
        case Command.PRD03_BUILD:
            fixture = Prd03Fixture.model_validate_json(_path(args, "input").read_bytes())
            prd01 = build_prd01(Prd01Fixture.model_validate_json(
                Path("docs/specs/v14/fixtures/prd01-input.json").read_bytes()))
            prd02 = build_prd02_validation_from(
                prd01.plan, prd01.selection, load_prd02_fixture())
            return model_json(build_prd03_segment_from(
                prd01.plan, prd02, fixture, ResearchSegment.VALIDATION))
        case Command.PRD03_ACCEPTANCE:
            return _JSON.validate_python(run_prd03())
        case Command.PRD04_BUILD:
            source = Prd04Source.model_validate_json(_path(args, "input").read_bytes())
            history = HoldoutHistory.model_validate_json(
                _path(args, "history").read_bytes())
            return model_json(build_prd04(source, history))
        case Command.PRD04_VERIFY:
            bundle = verify_bundle(_path(args, "artifact").read_bytes())
            return {"state": "pass", "bundle_hash": bundle.bundle_hash}
        case Command.PRD04_ACCEPTANCE:
            return _JSON.validate_python(run_prd04())


def _command(args: argparse.Namespace) -> Command:
    value = getattr(args, "command", None)
    if not isinstance(value, str):
        raise V14Failure(V14FailureCode.ARTIFACT_MALFORMED, "command")
    return Command(value)


def main() -> int:
    try:
        args = _parser().parse_args()
        report = _dispatch(_command(args), args)
        print(canonical_json(report).decode())
        return 0
    except V14Failure as error:
        print(canonical_json(_failure_json(error)).decode())
        return 1
    except (OSError, ValidationError, ValueError, V14ContractError) as error:
        failure = V14Failure(V14FailureCode.ARTIFACT_MALFORMED, str(error))
        print(canonical_json(_failure_json(failure)).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
