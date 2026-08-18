from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import NoReturn, TextIO, override

from .canonical import JsonValue
from .errors import FailureCode, V16Failure
from .models import MarketScope
from .registries import FORBIDDEN_INPUT_TOKENS
from .reporting import line


@unique
class Command(StrEnum):
    CONFIG_CHECK = "config-check"
    DATA_HEALTH = "data-health"
    PRD01 = "prd01-acceptance"
    PRD02 = "prd02-acceptance"
    PRD03 = "prd03-acceptance"
    PRD04 = "prd04-acceptance"
    ACCEPTANCE = "acceptance"


@dataclass(frozen=True, slots=True)
class CliRequest:
    command: Command
    config: str | None = None
    manifest: str | None = None
    as_of: datetime | None = None
    scope: MarketScope | None = None


type Dispatcher = Callable[[CliRequest], JsonValue]


@dataclass(frozen=True, slots=True)
class CliEnvironment:
    stdout: TextIO
    stderr: TextIO
    dispatch: Dispatcher


class CanonicalArgumentParser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, "invalid command arguments")


def parser() -> CanonicalArgumentParser:
    root = CanonicalArgumentParser(prog="python -m src.v16.cli", add_help=True)
    commands = root.add_subparsers(dest="command", required=True)
    config = commands.add_parser(Command.CONFIG_CHECK.value, add_help=False)
    _ = config.add_argument("--config")
    health = commands.add_parser(Command.DATA_HEALTH.value, add_help=False)
    _ = health.add_argument("--manifest", required=True)
    _ = health.add_argument("--as-of", required=True)
    _ = health.add_argument("--market", choices=tuple(item.value for item in MarketScope), required=True)
    for command in (Command.PRD01, Command.PRD02, Command.PRD03,
                    Command.PRD04, Command.ACCEPTANCE):
        _ = commands.add_parser(command.value, add_help=False)
    return root


def _option(arguments: tuple[str, ...], name: str) -> str:
    if arguments.count(name) != 1:
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, f"{name} must occur exactly once")
    index = arguments.index(name)
    if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, f"{name} requires one value")
    return arguments[index + 1]


def parse_request(arguments: tuple[str, ...]) -> CliRequest:
    if not arguments:
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, "command required")
    if any(token in argument.casefold() for argument in arguments
           for token in FORBIDDEN_INPUT_TOKENS):
        raise V16Failure(FailureCode.INVALID, "forbidden boundary input")
    try:
        command = Command(arguments[0])
    except ValueError as error:
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, "unknown command") from error
    if command is Command.CONFIG_CHECK:
        if not arguments[1:]:
            _ = parser().parse_args(arguments)
            return CliRequest(command=command, config="config.yaml")
        config = _option(arguments, "--config")
        if arguments != (command.value, "--config", config):
            raise V16Failure(FailureCode.CLI_USAGE_ERROR, "invalid config options")
        _ = parser().parse_args(arguments)
        return CliRequest(command=command, config=config)
    if command is Command.DATA_HEALTH:
        manifest = _option(arguments, "--manifest")
        raw_as_of = _option(arguments, "--as-of")
        raw_market = _option(arguments, "--market")
        if len(arguments) != 7:
            raise V16Failure(FailureCode.CLI_USAGE_ERROR, "invalid health options")
        _ = parser().parse_args(arguments)
        try:
            as_of = datetime.fromisoformat(raw_as_of.replace("Z", "+00:00"))
            scope = MarketScope(raw_market)
        except ValueError as error:
            raise V16Failure(FailureCode.CLI_USAGE_ERROR, "invalid health arguments") from error
        return CliRequest(command=command, manifest=manifest, as_of=as_of, scope=scope)
    if len(arguments) != 1:
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, "acceptance takes no options")
    _ = parser().parse_args(arguments)
    return CliRequest(command=command)


def _failure(status: str, code: str) -> JsonValue:
    return {"code": code, "schema_version": "v16.failure.1", "status": status}


def run_cli(arguments: tuple[str, ...], environment: CliEnvironment) -> int:
    try:
        request = parse_request(arguments)
        report = environment.dispatch(request)
        _ = environment.stdout.write(line(report).decode("utf-8"))
        if isinstance(report, dict) and report.get("status") == "PASS":
            return 0
        return 1 if request.command.value.endswith("acceptance") else 2
    except V16Failure as error:
        _ = environment.stdout.write(line(_failure("FAIL", error.code.value)).decode("utf-8"))
        acceptance = bool(arguments) and arguments[0].endswith("acceptance")
        return 1 if acceptance and error.code is not FailureCode.CLI_USAGE_ERROR else 2


def run_cli_main(arguments: tuple[str, ...], environment: CliEnvironment) -> int:
    try:
        return run_cli(arguments, environment)
    except Exception:  # noqa: BROAD_EXCEPT_OK - final CLI boundary redacts defects
        _ = environment.stdout.write(line(_failure("ERROR", "INTERNAL_ERROR")).decode("utf-8"))
        _ = environment.stderr.write("INTERNAL_ERROR\n")
        return 1
