from __future__ import annotations

from typing import Final

from pydantic import TypeAdapter

from src.v16.canonical import JsonValue, canonical_hash, canonical_json, content_hash

type ParsedJson = (
    str | int | float | bool | None | list[ParsedJson] | dict[str, ParsedJson]
)
_JSON: Final[TypeAdapter[ParsedJson]] = TypeAdapter(ParsedJson)


def parse_json(payload: str | bytes) -> JsonValue:
    return _JSON.validate_json(payload)


__all__ = ["JsonValue", "canonical_hash", "canonical_json", "content_hash", "parse_json"]
