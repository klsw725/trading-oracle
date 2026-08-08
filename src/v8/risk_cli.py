from __future__ import annotations

from pathlib import Path
from typing import Final

from src.v8.fixture import load_json
from src.v8.models import FailureCode, LedgerContractError
from src.v8.risk_acceptance import HAPPY_FIXTURE_PATH, run_risk_acceptance
from src.v8.risk_compiler import compile_risk_fixture
from src.v8.risk_json import JsonValue, canonical_json, model_json
from src.v8.risk_verifier import verify_risk_artifact

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
_PAPER_ROOT: Final = (_PROJECT_ROOT / "data/paper/v8").resolve()


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _option(arguments: tuple[str, ...], name: str) -> str | None:
    try:
        index = arguments.index(name)
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        raise LedgerContractError(FailureCode.MALFORMED_INPUT, f"missing value for {name}")
    return arguments[index + 1]


def _safe_output(raw_path: str) -> Path:
    output = Path(raw_path).resolve()
    try:
        _ = output.relative_to(_PAPER_ROOT)
    except ValueError as error:
        raise LedgerContractError(
            FailureCode.LIVE_STATE_CONTAMINATION, "output must be under data/paper/v8"
        ) from error
    return output


def risk_build(arguments: tuple[str, ...]) -> int:
    input_option = _option(arguments, "--input")
    input_path = Path(input_option) if input_option else HAPPY_FIXTURE_PATH
    compiled = compile_risk_fixture(load_json(input_path))
    artifact = compiled.artifact
    if artifact is None:
        _emit(
            {
                "risk_status": "kill_switch_active",
                "error_code": compiled.error_code.value if compiled.error_code else None,
                "fail_closed": True,
            }
        )
        return 1
    output_option = _option(arguments, "--output")
    if output_option is None:
        _emit(model_json(artifact))
        return 0
    output = _safe_output(output_option)
    if input_path.resolve() == output:
        raise LedgerContractError(FailureCode.MALFORMED_INPUT, "output must not replace input")
    payload = canonical_json(model_json(artifact)) + b"\n"
    if output.exists():
        if output.read_bytes() != payload:
            raise LedgerContractError(
                FailureCode.MALFORMED_INPUT, "immutable output already differs"
            )
        write_status = "unchanged"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        _ = output.write_bytes(payload)
        write_status = "created"
    _emit(
        {
            "risk_status": artifact.decision.risk_status,
            "output": str(output),
            "write_status": write_status,
        }
    )
    return 0


def risk_verify(arguments: tuple[str, ...]) -> int:
    artifact_option = _option(arguments, "--artifact")
    if artifact_option is not None:
        artifact_value = load_json(Path(artifact_option))
    else:
        fixture_option = _option(arguments, "--fixture")
        fixture_path = Path(fixture_option) if fixture_option else HAPPY_FIXTURE_PATH
        compiled = compile_risk_fixture(load_json(fixture_path))
        if compiled.artifact is None:
            _emit(
                {
                    "risk_status": "kill_switch_active",
                    "error_code": compiled.error_code.value if compiled.error_code else None,
                    "fail_closed": True,
                }
            )
            return 1
        artifact_value = model_json(compiled.artifact)
    result = verify_risk_artifact(artifact_value)
    _emit(model_json(result))
    return 0 if result.verification_status == "pass" else 1


def risk_acceptance() -> int:
    report = run_risk_acceptance()
    _emit(report)
    match report:  # noqa: MATCH_OK - report boundary requires an object
        case {"verification_status": "pass"}:
            return 0
        case _:
            return 1
