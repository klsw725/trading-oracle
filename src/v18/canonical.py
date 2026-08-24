from typing import Final

from pydantic import BaseModel, TypeAdapter

from src.v17.canonical import (
    canonical_hash as _canonical_hash,
    canonical_json as _canonical_json,
    content_hash,
)

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def model_json(model: BaseModel, *, exclude: set[str] | None = None) -> JsonValue:
    return _JSON.validate_python(
        model.model_dump(mode="json", exclude=exclude, exclude_none=True)
    )


def canonical_json(value: JsonValue) -> bytes:
    return _canonical_json(value)


def canonical_hash(value: JsonValue) -> str:
    return _canonical_hash(value)


def parse_json(payload: str | bytes) -> JsonValue:
    return _JSON.validate_json(payload)


__all__ = (
    "JsonValue",
    "canonical_hash",
    "canonical_json",
    "content_hash",
    "model_json",
    "parse_json",
)
