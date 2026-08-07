import json
from math import isfinite
import re
from typing import Final

from pydantic import ValidationError

from src.v4.models import JsonValue
from src.v6.models import JsonBoundary

from .spec_models import SpecContract, SpecVerificationError


_JSON_FENCE: Final = re.compile(r"^```json[ \t]*\n(?P<body>.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


class DuplicateSpecJsonKeyError(ValueError):
    pass


def _pairs(values: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in values:
        if key in result:
            raise DuplicateSpecJsonKeyError(key)
        result[key] = value
    return result


def _constant(value: str) -> JsonValue:
    raise SpecVerificationError("V7_SPEC_MALFORMED", f"forbidden numeric constant {value}")


def _finite(value: JsonValue) -> None:
    match value:  # noqa: MATCH_OK - recursive JsonValue variants are fully handled
        case dict() as record:
            for item in record.values():
                _finite(item)
        case list() as items:
            for item in items:
                _finite(item)
        case float() as number if not isfinite(number):
            raise SpecVerificationError("V7_SPEC_MALFORMED", "non-finite JSON number")
        case None | bool() | int() | float() | str():
            return


def parse_json_fences(markdown: str) -> tuple[JsonValue, ...]:
    blocks: list[JsonValue] = []
    for match in _JSON_FENCE.finditer(markdown):
        try:
            value = JsonBoundary.model_validate(
                json.loads(
                    match.group("body"),
                    object_pairs_hook=_pairs,
                    parse_constant=_constant,
                )
            ).root
            _finite(value)
            blocks.append(value)
        except (json.JSONDecodeError, DuplicateSpecJsonKeyError, ValidationError) as error:
            raise SpecVerificationError("V7_SPEC_MALFORMED", str(error)) from error
    return tuple(blocks)


def parse_spec_contract(markdown: str) -> SpecContract:
    blocks = parse_json_fences(markdown)
    if len(blocks) != 1:
        raise SpecVerificationError("V7_SPEC_MALFORMED", "SPEC must contain exactly one JSON fence")
    try:
        return SpecContract.model_validate(blocks[0])
    except ValidationError as error:
        raise SpecVerificationError("V7_SPEC_MALFORMED", str(error)) from error
