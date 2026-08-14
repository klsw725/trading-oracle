from __future__ import annotations

from pathlib import Path
import sys

from pydantic import ValidationError

from src.v4.models import canonical_json

from .models import V10ContractError
from .strategy_input import build_strategy_input_path, verify_strategy_input


def main() -> int:
    arguments = tuple(sys.argv[1:])
    try:
        if arguments == () or arguments == ("--help",):
            print("usage: python -m src.v10.strategy_input_cli {build --input PATH|verify --artifact PATH}")
            return 0
        if len(arguments) != 3:
            raise V10ContractError("V10_CLI_ARGUMENT_ERROR", "strategy_input")
        command, option, path = arguments
        if command == "build" and option == "--input":
            print(canonical_json(build_strategy_input_path(Path(path))).decode())
        elif command == "verify" and option == "--artifact":
            bundle = verify_strategy_input(Path(path).read_bytes())
            print(canonical_json({"state": "pass", "bundle_hash": bundle.bundle_hash,
                "fixture_hash": bundle.fixture_hash, "bar_count": len(bundle.bars),
                "series_count": len(bundle.series)}).decode())
        else:
            raise V10ContractError("V10_CLI_ARGUMENT_ERROR", "strategy_input")
        return 0
    except (V10ContractError, ValidationError, OSError) as error:
        code = error.code if isinstance(error, V10ContractError) else "V10_CLI_ERROR"
        print(canonical_json({"state": "fail", "error_code": code,
                              "detail": str(error)}).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
