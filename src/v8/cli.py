from __future__ import annotations

from pathlib import Path
import sys
from typing import Final

from src.v4.models import (
    ArtifactConflictError,
    JsonValue,
    canonical_json,
    write_immutable_json,
)
from src.v8.approval_acceptance import (
    FIXTURE_PATH as APPROVAL_FIXTURE_PATH,
    run_approval_acceptance,
)
from src.v8.approval_compiler import compile_approval_fixture
from src.v8.approval_verifier import verify_approval_artifact
from src.v8.acceptance import FIXTURE_PATH, run_acceptance
from src.v8.compiler import compile_fixture
from src.v8.fixture import load_json
from src.v8.identity import model_json
from src.v8.models import FailureCode, LedgerContractError, VerificationContext
from src.v8.reconciliation_cli import (
    reconciliation_acceptance,
    reconciliation_build,
    reconciliation_verify,
)
from .promotion_cli import promotion_acceptance, promotion_build, promotion_verify
from .risk_cli import risk_acceptance, risk_build, risk_verify
from .spec_acceptance import run_spec_acceptance
from src.v8.verifier import verify_artifact

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
_PAPER_ROOT: Final = (_PROJECT_ROOT / "data/paper/v8").resolve()
_USAGE: Final = (
    "usage: uv run python -m src.v8.cli "
    "{verify [--fixture PATH]|compile --input PATH [--output PATH]|acceptance|"
    "prd02-verify [--fixture PATH|--artifact PATH]|"
    "prd02-build [--input PATH] [--output PATH]|prd02-acceptance|"
    "prd03-verify [--fixture PATH|--artifact PATH]|"
    "prd03-build [--input PATH] [--output PATH]|prd03-acceptance|"
    "prd04-verify [--fixture PATH|--artifact PATH]|"
    "prd04-build [--input PATH] [--output PATH]|prd04-acceptance|"
    "prd05-verify [--fixture PATH|--artifact PATH]|"
    "prd05-build [--input PATH] [--output PATH]|prd05-acceptance|spec-acceptance}"
)


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _option(arguments: tuple[str, ...], name: str) -> str | None:
    try:
        index = arguments.index(name)
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        raise LedgerContractError(
            code=FailureCode.MALFORMED_INPUT, detail=f"missing value for {name}"
        )
    return arguments[index + 1]


def _verify(arguments: tuple[str, ...]) -> int:
    fixture_option = _option(arguments, "--fixture")
    fixture_path = Path(fixture_option) if fixture_option else FIXTURE_PATH
    fixture = load_json(fixture_path)
    artifact = compile_fixture(fixture)
    source_hash = artifact.source_input_hash
    context = VerificationContext(
        replay_cutoff=artifact.events[-1].recorded_at,
        declared_input_hash=source_hash,
        observed_input_hash=source_hash,
        claimed_success=False,
    )
    result = verify_artifact(artifact, context)
    _emit(model_json(result))
    return 0 if result.state == "pass" else 1


def _safe_output(raw_path: str) -> Path:
    output = Path(raw_path).resolve()
    try:
        _ = output.relative_to(_PAPER_ROOT)
    except ValueError as error:
        raise LedgerContractError(
            FailureCode.LIVE_STATE_CONTAMINATION,
            "output must be under data/paper/v8",
        ) from error
    return output


def _compile(arguments: tuple[str, ...]) -> int:
    input_option = _option(arguments, "--input")
    if input_option is None:
        raise LedgerContractError(
            FailureCode.MALFORMED_INPUT, "compile requires --input"
        )
    input_path = Path(input_option)
    artifact = compile_fixture(load_json(input_path))
    output_option = _option(arguments, "--output")
    if output_option is None:
        _emit(model_json(artifact))
        return 0
    output = _safe_output(output_option)
    if input_path.resolve() == output:
        raise LedgerContractError(
            FailureCode.MALFORMED_INPUT, "output must not replace input"
        )
    status = write_immutable_json(output, model_json(artifact))
    _emit({"state": "pass", "output": str(output), "write_status": status.value})
    return 0


def _approval_build(arguments: tuple[str, ...]) -> int:
    input_option = _option(arguments, "--input")
    input_path = Path(input_option) if input_option else APPROVAL_FIXTURE_PATH
    result = compile_approval_fixture(load_json(input_path))
    if result.artifact is None:
        _emit(
            {
                "approval_status": result.approval_status,
                "error_code": (
                    result.error_code.value if result.error_code is not None else None
                ),
            }
        )
        return 1
    output_option = _option(arguments, "--output")
    if output_option is None:
        _emit(model_json(result.artifact))
        return 0
    output = _safe_output(output_option)
    if input_path.resolve() == output:
        raise LedgerContractError(
            FailureCode.MALFORMED_INPUT, "output must not replace input"
        )
    status = write_immutable_json(output, model_json(result.artifact))
    _emit(
        {
            "approval_status": result.approval_status,
            "output": str(output),
            "write_status": status.value,
        }
    )
    return 0


def _approval_verify(arguments: tuple[str, ...]) -> int:
    artifact_option = _option(arguments, "--artifact")
    if artifact_option is not None:
        artifact_value = load_json(Path(artifact_option))
    else:
        fixture_option = _option(arguments, "--fixture")
        fixture_path = Path(fixture_option) if fixture_option else APPROVAL_FIXTURE_PATH
        compiled = compile_approval_fixture(load_json(fixture_path))
        if compiled.artifact is None:
            _emit(
                {
                    "approval_status": compiled.approval_status,
                    "error_code": (
                        compiled.error_code.value
                        if compiled.error_code is not None
                        else None
                    ),
                }
            )
            return 1
        artifact_value = model_json(compiled.artifact)
    result = verify_approval_artifact(artifact_value)
    _emit(model_json(result))
    return 0 if result.verification_status == "pass" else 1


def main() -> int:
    arguments = tuple(sys.argv[1:])
    if not arguments or arguments[0] in {"--help", "-h"}:
        print(_USAGE)
        return 0
    try:
        match arguments[0]:  # noqa: MATCH_OK - unknown CLI commands return exit 1
            case "verify":
                return _verify(arguments[1:])
            case "compile":
                return _compile(arguments[1:])
            case "acceptance":
                report = run_acceptance()
                _emit(report)
                match report:  # noqa: MATCH_OK - report boundary requires an object
                    case {"state": "pass"}:
                        return 0
                    case _:
                        return 1
            case "prd02-build":
                return _approval_build(arguments[1:])
            case "prd02-verify":
                return _approval_verify(arguments[1:])
            case "prd02-acceptance":
                report = run_approval_acceptance()
                _emit(report)
                match report:  # noqa: MATCH_OK - report boundary requires an object
                    case {"verification_status": "pass"}:
                        return 0
                    case _:
                        return 1
            case "prd03-build":
                return reconciliation_build(arguments[1:])
            case "prd03-verify":
                return reconciliation_verify(arguments[1:])
            case "prd03-acceptance":
                return reconciliation_acceptance()
            case "prd04-build":
                return risk_build(arguments[1:])
            case "prd04-verify":
                return risk_verify(arguments[1:])
            case "prd04-acceptance":
                return risk_acceptance()
            case "prd05-build":
                return promotion_build(arguments[1:])
            case "prd05-verify":
                return promotion_verify(arguments[1:])
            case "prd05-acceptance":
                return promotion_acceptance()
            case "spec-acceptance":
                report = run_spec_acceptance()
                _emit(report)
                match report:  # noqa: MATCH_OK - report boundary requires an object
                    case {"state": "pass"}:
                        return 0
                    case _:
                        return 1
            case _:
                print(_USAGE)
                return 1
    except LedgerContractError as error:
        _emit(
            {
                "state": "fail",
                "error_code": error.code.value,
                "detail": str(error),
            }
        )
        return 1
    except ArtifactConflictError as error:
        _emit(
            {
                "state": "fail",
                "error_code": "artifact_conflict",
                "detail": str(error),
            }
        )
        return 1
    except OSError as error:
        _emit({"state": "fail", "error_code": "io_error", "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
