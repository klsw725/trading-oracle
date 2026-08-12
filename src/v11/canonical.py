from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from math import isfinite
from typing import Final

import numpy as np
from pydantic import BaseModel, TypeAdapter, ValidationError

from src.v4.models import JsonValue, canonical_json

from .models import V11ContractError


_JSON: Final = TypeAdapter[JsonValue](JsonValue)
_FORBIDDEN: Final = frozenset({
    "access_token", "account_id", "account_number", "broker_destination",
    "client_secret", "credential", "oauth_token", "raw_account_id",
    "raw_account_identifier", "portfolio_path",
})


def decimal_value(value: str) -> Decimal:
    return Decimal(value)


def money(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"-0", ""} else normalized


def normalize_scalar(value: JsonValue | int | float | Decimal | np.integer | np.floating) -> JsonValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        if not isfinite(number):
            raise V11ContractError("V11_NON_FINITE", str(number))
        return money(Decimal(str(number)))
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, float):
        if not isfinite(value):
            raise V11ContractError("V11_NON_FINITE", str(value))
        return money(Decimal(str(value)))
    if isinstance(value, dict):
        return {key: normalize_scalar(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_scalar(item) for item in value]
    return value


def model_json(model: BaseModel) -> JsonValue:
    return _JSON.validate_python(normalize_scalar(model.model_dump(mode="json", exclude_none=False)))


def canonical_hash(value: JsonValue) -> str:
    return f"sha256:{sha256(canonical_json(normalize_scalar(value))).hexdigest()}"


def parse_json(payload: bytes) -> JsonValue:
    try:
        return _JSON.validate_json(payload)
    except ValidationError as error:
        raise V11ContractError("V11_JSON_PARSE_ERROR", str(error)) from error


def reject_forbidden(value: JsonValue) -> None:
    match value:  # noqa: MATCH_OK - recursive JsonValue variants are fully covered
        case dict() as record:
            forbidden = _FORBIDDEN.intersection(record)
            if forbidden:
                raise V11ContractError("V11_PAPER_BOUNDARY", min(forbidden))
            for item in record.values():
                reject_forbidden(item)
        case list() as items:
            for item in items:
                reject_forbidden(item)
        case None | bool() | int() | float() | str():
            return
