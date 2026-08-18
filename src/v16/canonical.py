from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite
from dataclasses import dataclass
from typing import TypeAlias, override
from unicodedata import normalize


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class CanonicalError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def normalized(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            normalized_key = normalize("NFC", key)
            if normalized_key in result:
                raise CanonicalError("duplicate key after NFC normalization")
            result[normalized_key] = normalized(item)
        return result
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, str):
        return normalize("NFC", value)
    if isinstance(value, float) and not isfinite(value):
        raise CanonicalError("non-finite number")
    return value


def canonical_json(value: JsonValue) -> bytes:
    return json.dumps(normalized(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(payload: bytes) -> str:
    return f"sha256:{sha256(payload).hexdigest()}"


def canonical_hash(value: JsonValue) -> str:
    return content_hash(canonical_json(value))
