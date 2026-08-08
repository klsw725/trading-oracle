from __future__ import annotations

from hashlib import sha256
from typing import Final

from pydantic import BaseModel, TypeAdapter

from src.v4.models import JsonValue, canonical_hash, canonical_json
from src.v8.event_models import LedgerEventBase

ID_HEX_LENGTH: Final = 20
_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def model_json(model: BaseModel, *, exclude: set[str] | None = None) -> JsonValue:
    return _JSON.validate_python(
        model.model_dump(mode="json", exclude=exclude, exclude_none=True)
    )


def deterministic_id(prefix: str, seed: JsonValue) -> str:
    return f"{prefix}{sha256(canonical_json(seed)).hexdigest()[:ID_HEX_LENGTH]}"


def event_hash(event: LedgerEventBase) -> str:
    return canonical_hash(model_json(event, exclude={"event_hash"}))
