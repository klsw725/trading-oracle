from __future__ import annotations

from hashlib import sha256
import json
from typing import Final

from pydantic import BaseModel, TypeAdapter

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def canonical_json(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: JsonValue) -> str:
    return f"sha256:{sha256(canonical_json(value)).hexdigest()}"


def deterministic_id(prefix: str, seed: JsonValue) -> str:
    return f"{prefix}{sha256(canonical_json(seed)).hexdigest()[:20]}"


def model_json(model: BaseModel, exclude: set[str] | None = None) -> JsonValue:
    return _JSON.validate_python(
        model.model_dump(mode="json", exclude=exclude, exclude_none=True)
    )
