from __future__ import annotations

from pathlib import Path
import sys
from typing import Final, Literal

from src.v4.models import JsonValue, canonical_json

from .acceptance import accept_prd, build_path, run_acceptance
from .canonical import canonical_hash, model_json
from .models import ExecutionLedger, V11ContractError
from .reconciliation import reconcile
from .replay import replay
from .verifier import verify_bundle


_USAGE: Final = "usage: uv run python -m src.v11.cli {acceptance|prd0N-build|prd0N-verify|prd03-replay|prd0N-acceptance}"


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _path(arguments: tuple[str, ...], option: str) -> Path:
    if len(arguments) != 2 or arguments[0] != option:
        raise V11ContractError("V11_CLI_ARGUMENT_ERROR", option)
    return Path(arguments[1])


def _prd(command: str) -> Literal[1, 2, 3, 4]:
    value = int(command[3:5])
    match value:  # noqa: MATCH_OK - CLI integer boundary rejects unsupported PRDs
        case 1: return 1
        case 2: return 2
        case 3: return 3
        case 4: return 4
        case _: raise V11ContractError("V11_CLI_ARGUMENT_ERROR", command)


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
            _emit({"state": "pass", "prd": bundle.prd, "bundle_hash": bundle.bundle_hash})
            return 0
        if command == "prd03-replay":
            bundle = verify_bundle(_path(arguments[1:], "--artifact").read_bytes())
            if bundle.prd != 3:
                raise V11ContractError("V11_BUNDLE_MALFORMED", "PRD mismatch")
            ledger = ExecutionLedger.model_validate(bundle.artifacts[0])
            replayed = replay(ledger.events, ledger.initial_cash, ledger.checkpoint)
            result = reconcile(replayed, ledger.source_snapshot)
            state_json = model_json(replayed)
            status = "fail" if result.execution_halt else "pass"
            _emit({"state": status, "prd": 3, "replay_state": state_json,
                "replay_hash": canonical_hash(state_json), "reconciliation": model_json(result)})
            return 1 if result.execution_halt else 0
        print(_USAGE)
        return 1
    except (V11ContractError, OSError, ValueError) as error:
        code = error.code if isinstance(error, V11ContractError) else "V11_CLI_ERROR"
        _emit({"state": "fail", "error_code": code, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
