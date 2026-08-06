from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from .models import JsonValue
from .native_capture import (
    CaptureDisabled,
    CaptureFailed,
    CaptureInconclusive,
    CaptureSucceeded,
    NativeCaptureInput,
    NativeCaptureResult,
    capture_native_snapshot,
)


class NativeCapturePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    multi_results: dict[str, JsonValue]
    signals_data: list[dict[str, JsonValue]]
    market_data: dict[str, JsonValue]
    portfolio: dict[str, JsonValue]
    config: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CapturePayloadError(Exception):
    path: Path
    detail: str

    def __str__(self) -> str:
        return f"invalid native capture payload {self.path}: {self.detail}"


def load_capture_payload(path: Path) -> NativeCapturePayload:
    try:
        return TypeAdapter(NativeCapturePayload).validate_json(path.read_bytes())
    except ValidationError as error:
        raise CapturePayloadError(path, str(error)) from error


def _capture_config(
    config: dict[str, JsonValue], output_directory: Path
) -> dict[str, JsonValue]:
    configured = dict(config)
    match configured.get("v4"):
        case dict() as value:
            v4_config = dict(value)
        case None | str() | bool() | int() | float() | list():
            v4_config = {}
        case unreachable:
            assert_never(unreachable)
    v4_config["native_capture"] = {
        "enabled": True,
        "output_dir": str(output_directory),
    }
    configured["v4"] = v4_config
    return configured


def _result_json(result: NativeCaptureResult) -> JsonValue:
    match result:
        case CaptureSucceeded():
            return {
                "state": "success",
                "status": result.status,
                "snapshot_id": result.snapshot_id,
                "path": str(result.path),
                "write_status": result.write_status,
            }
        case CaptureInconclusive():
            return {
                "state": "inconclusive",
                "status": result.status,
                "missing_provenance": list(result.missing_provenance),
            }
        case CaptureFailed():
            return {
                "state": "fail",
                "status": result.status,
                "error": {
                    "type": result.failure_type,
                    "message": result.detail,
                },
            }
        case CaptureDisabled():
            return {
                "state": "fail",
                "status": result.status,
                "error": {
                    "type": "CaptureDisabled",
                    "message": "capture command must enable native capture",
                },
            }
        case unreachable:
            assert_never(unreachable)


def capture_report(input_path: Path, output_directory: Path) -> JsonValue:
    payload = load_capture_payload(input_path)
    return _result_json(
        capture_native_snapshot(
            NativeCaptureInput(
                multi_results=payload.multi_results,
                signals_data=payload.signals_data,
                market_data=payload.market_data,
                portfolio=payload.portfolio,
                config=_capture_config(payload.config, output_directory),
            )
        )
    )
