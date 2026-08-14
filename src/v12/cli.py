from __future__ import annotations

from pathlib import Path
import sys
from typing import Final, Literal

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_json
from src.v11.canonical import model_json
from src.v11.models import V11ContractError

from .acceptance import accept_prd, build_path, run_acceptance
from .models import V12ContractError
from .replay import replay
from .verifier import verify_bundle


_USAGE: Final = "usage: uv run python -m src.v12.cli {acceptance|prd0N-build|prd0N-verify|prd0N-acceptance|prd02-replay|shadow}"


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _path(arguments: tuple[str, ...], option: str) -> Path:
    if len(arguments) != 2 or arguments[0] != option:
        raise V12ContractError("V12_CLI_ARGUMENT_ERROR", option)
    return Path(arguments[1])


def _selection(arguments: tuple[str, ...]) -> tuple[Path, str, str]:
    if (len(arguments) != 6 or arguments[0] != "--artifact"
            or arguments[2] != "--strategy" or arguments[4] != "--parameter-set"):
        raise V12ContractError("V12_CLI_ARGUMENT_ERROR", "artifact/strategy/parameter-set")
    return Path(arguments[1]), arguments[3], arguments[5]


def _prd(command: str) -> Literal[1, 2, 3, 4]:
    match int(command[3:5]):
        case 1: return 1
        case 2: return 2
        case 3: return 3
        case 4: return 4
        case _:
            raise V12ContractError("V12_CLI_ARGUMENT_ERROR", command)


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
        if command.endswith("-acceptance"):
            _emit(accept_prd(_prd(command)))
            return 0
        if command.endswith("-build"):
            _emit(build_path(_path(arguments[1:], "--input")))
            return 0
        if command.endswith("-verify"):
            bundle = verify_bundle(_path(arguments[1:], "--artifact").read_bytes())
            _emit({"state": "pass", "fixture_hash": bundle.fixture_hash,
                "bundle_hash": bundle.bundle_hash, "run_hash": bundle.run.manifest_hash})
            return 0
        if command in {"prd02-replay", "shadow"}:
            path, strategy_id, parameter_set_id = _selection(arguments[1:])
            trade = replay(path.read_bytes(), strategy_id, parameter_set_id)
            _emit({"state": "pass", "mode": command, "bundle_path": str(path),
                "trade": model_json(trade)})
            return 0
        print(_USAGE)
        return 1
    except (V12ContractError, V11ContractError, ValidationError, OSError, ValueError) as error:
        code = error.code if isinstance(error, (V12ContractError, V11ContractError)) else "V12_CLI_ERROR"
        _emit({"state": "fail", "error_code": code, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
