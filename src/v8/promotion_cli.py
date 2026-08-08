from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import ValidationError

from src.v4.models import write_immutable_json
from src.v8.fixture import load_json
from src.v8.models import FailureCode, LedgerContractError
from .promotion_acceptance import (
    HAPPY_FIXTURE_PATH,
    run_promotion_acceptance,
)
from src.v8.promotion_compiler import compile_incident_fixture, compile_promotion_fixture
from src.v8.promotion_models import CompilePromotionResult, IncidentRecord, PromotionArtifact
from .promotion_verifier import verify_incident_record, verify_promotion_artifact
from src.v8.risk_json import JsonValue, canonical_json, model_json

_PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
_PROMOTION_ROOT: Final = (_PROJECT_ROOT / "data/paper/v8/promotion").resolve()


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
        _ = output.relative_to(_PROMOTION_ROOT)
    except ValueError as error:
        raise LedgerContractError(
            FailureCode.LIVE_STATE_CONTAMINATION,
            "output must be under data/paper/v8/promotion",
        ) from error
    return output


def _compile(value: JsonValue) -> CompilePromotionResult:
    match value:  # noqa: MATCH_OK - fixture name selects the closed PRD05 fixture variants
        case {"fixture_name": "incident_auto_rollback_after_stale_quote_false_allow"}:
            return compile_incident_fixture(value)
        case _:
            return compile_promotion_fixture(value)


def promotion_build(arguments: tuple[str, ...]) -> int:
    input_option = _option(arguments, "--input")
    input_path = Path(input_option) if input_option else HAPPY_FIXTURE_PATH
    compiled = _compile(load_json(input_path))
    if compiled.artifact is None:
        _emit(
            {
                "promotion_status": "rolled_back",
                "error_code": compiled.error_code.value if compiled.error_code else None,
                "dry_run_request_allowed": False,
            }
        )
        return 1
    output_option = _option(arguments, "--output")
    if output_option is None:
        _emit(model_json(compiled.artifact))
        return 0
    output = _safe_output(output_option)
    if input_path.resolve() == output:
        raise LedgerContractError(FailureCode.MALFORMED_INPUT, "output must not replace input")
    status = write_immutable_json(output, model_json(compiled.artifact))
    _emit(
        {
            "promotion_status": compiled.artifact.promotion_status,
            "output": str(output),
            "write_status": status.value,
        }
    )
    return 0


def promotion_verify(arguments: tuple[str, ...]) -> int:
    artifact_option = _option(arguments, "--artifact")
    if artifact_option is not None:
        artifact_value = load_json(Path(artifact_option))
        try:
            incident = IncidentRecord.model_validate(artifact_value)
        except ValidationError:
            result = verify_promotion_artifact(artifact_value)
        else:
            result = verify_incident_record(model_json(incident))
    else:
        fixture_option = _option(arguments, "--fixture")
        fixture_path = Path(fixture_option) if fixture_option else HAPPY_FIXTURE_PATH
        compiled = _compile(load_json(fixture_path))
        if compiled.artifact is None:
            _emit(
                {
                    "promotion_status": "rolled_back",
                    "error_code": compiled.error_code.value if compiled.error_code else None,
                    "dry_run_request_allowed": False,
                }
            )
            return 1
        match compiled.artifact:  # noqa: MATCH_OK - compiled artifact variants are fully handled
            case PromotionArtifact() as promotion:
                result = verify_promotion_artifact(model_json(promotion))
            case IncidentRecord() as incident:
                result = verify_incident_record(model_json(incident))
    _emit(model_json(result))
    return 0 if result.verification_status == "pass" else 1


def promotion_acceptance() -> int:
    report = run_promotion_acceptance()
    _emit(report)
    match report:  # noqa: MATCH_OK - report boundary requires an object
        case {"verification_status": "pass"}:
            return 0
        case _:
            return 1
