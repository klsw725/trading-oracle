from __future__ import annotations

from pathlib import Path
import sys
from typing import Final, Literal

from src.v4.models import JsonValue, canonical_json

from .acceptance import accept_prd, build_path, run_acceptance
from .models import V10ContractError
from .verifier import verify_bundle


_USAGE: Final = (
    "usage: uv run python -m src.v10.cli "
    "{acceptance|prd01-acceptance|prd02-acceptance|prd03-acceptance|prd04-acceptance|"
    "prd01-build|prd01-verify|prd02-build|prd02-verify|prd03-build|prd03-verify|"
    "prd04-build|prd04-verify}"
)


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _path(arguments: tuple[str, ...], option: str) -> Path:
    if len(arguments) != 2 or arguments[0] != option:
        raise V10ContractError("V10_CLI_ARGUMENT_ERROR", option)
    return Path(arguments[1])


def _prd(command: str) -> Literal[1, 2, 3, 4]:
    value = int(command[3:5])
    if value not in (1, 2, 3, 4):
        raise V10ContractError("V10_CLI_ARGUMENT_ERROR", command)
    return value


def _artifact(command: str, arguments: tuple[str, ...]) -> int:
    if command.endswith("-build"):
        _emit(build_path(_path(arguments, "--input")))
        return 0
    path = _path(arguments, "--artifact")
    try:
        bundle = verify_bundle(path.read_bytes())
    except OSError as error:
        raise V10ContractError("V10_FIXTURE_ERROR", str(error)) from error
    if bundle.prd != _prd(command):
        raise V10ContractError("V10_BUNDLE_MALFORMED", "PRD mismatch")
    _emit({"state": "pass", "prd": bundle.prd, "bundle_hash": bundle.bundle_hash})
    return 0


def main() -> int:
    arguments = tuple(sys.argv[1:])
    if not arguments or arguments[0] in {"--help", "-h"}:
        print(_USAGE)
        return 0
    try:
        command = arguments[0]
        if command == "acceptance":
            _emit(run_acceptance())
            return 0
        if command.startswith("prd") and command.endswith("-acceptance"):
            _emit(accept_prd(_prd(command)))
            return 0
        if command.startswith("prd") and (command.endswith("-build") or command.endswith("-verify")):
            return _artifact(command, arguments[1:])
        print(_USAGE)
        return 1
    except (V10ContractError, ValueError) as error:
        code = error.code if isinstance(error, V10ContractError) else "V10_CLI_ARGUMENT_ERROR"
        _emit({"state": "fail", "error_code": code, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
