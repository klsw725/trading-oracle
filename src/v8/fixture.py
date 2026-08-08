from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import override

from pydantic import RootModel, ValidationError

from src.v4.models import JsonValue
from src.v8.models import FailureCode, LedgerContractError


class JsonBoundary(RootModel[JsonValue]):
    pass


class DuplicateJsonKeyError(ValueError):
    @override
    def __str__(self) -> str:
        return "duplicate JSON object key"


def _pairs(values: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in values:
        if key in result:
            raise DuplicateJsonKeyError
        result[key] = value
    return result


def _constant(value: str) -> JsonValue:
    raise LedgerContractError(
        FailureCode.MALFORMED_INPUT, f"forbidden numeric constant {value}"
    )


def _require_finite(value: JsonValue) -> None:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            for item in record.values():
                _require_finite(item)
        case list() as items:
            for item in items:
                _require_finite(item)
        case float() as number if not isfinite(number):
            raise LedgerContractError(
                FailureCode.MALFORMED_INPUT, "non-finite JSON number"
            )
        case None | bool() | int() | float() | str():
            return


def parse_json_bytes(payload: bytes) -> JsonValue:
    try:
        value = JsonBoundary.model_validate(
            json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant)
        ).root
    except (json.JSONDecodeError, DuplicateJsonKeyError, UnicodeDecodeError, ValidationError) as error:
        raise LedgerContractError(FailureCode.MALFORMED_INPUT, str(error)) from error
    _require_finite(value)
    return value


def load_json(path: Path) -> JsonValue:
    try:
        return parse_json_bytes(path.read_bytes())
    except OSError as error:
        raise LedgerContractError(FailureCode.MALFORMED_INPUT, str(error)) from error
