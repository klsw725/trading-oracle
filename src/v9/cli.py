from __future__ import annotations

from pathlib import Path
import sys
from typing import Final

from src.v4.models import JsonValue, canonical_json
from .acceptance import run_acceptance, verify_fixture
from .contract import V9ContractError
from .fixture import FIXTURE_PATH, load_fixture


_USAGE: Final = (
    "usage: uv run python -m src.v9.cli "
    "{acceptance|verify [--fixture PATH]}"
)


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _verify(arguments: tuple[str, ...]) -> int:
    path = FIXTURE_PATH
    if arguments:
        if len(arguments) != 2 or arguments[0] != "--fixture":
            raise V9ContractError("malformed_query", "verify options")
        path = Path(arguments[1])
    _ = verify_fixture(load_fixture(path))
    _emit({"state": "pass", "fixture": str(path)})
    return 0


def main() -> int:
    arguments = tuple(sys.argv[1:])
    if not arguments or arguments[0] in {"--help", "-h"}:
        print(_USAGE)
        return 0
    try:
        match arguments[0]:  # noqa: MATCH_OK - unknown commands print usage
            case "acceptance":
                report = run_acceptance()
                _emit(report)
                match report:  # noqa: MATCH_OK - report boundary requires an object
                    case {"state": "pass"}:
                        return 0
                    case _:
                        return 1
            case "verify":
                return _verify(arguments[1:])
            case _:
                print(_USAGE)
                return 1
    except V9ContractError as error:
        _emit({"state": "fail", "error_code": error.code, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
