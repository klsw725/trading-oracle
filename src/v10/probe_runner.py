from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from src.v4.models import JsonValue

from .models import V10ContractError


class Mutation(Protocol):
    def __call__(self) -> JsonValue | BaseModel | None: ...


def error_probe(name: str, expected: str, mutation: Mutation) -> JsonValue:
    observed: str | None = None
    try:
        _ = mutation()
    except V10ContractError as error:
        observed = error.code
    if observed != expected:
        raise V10ContractError("V10_PROBE_FAILED", f"{name}: {observed}")
    return {"name": name, "state": "pass", "expected_error_code": expected,
            "observed_error_code": observed}


def outcome_probe(name: str, expected: str, observed: str) -> JsonValue:
    if observed != expected:
        raise V10ContractError("V10_PROBE_FAILED", f"{name}: {observed}")
    return {"name": name, "state": "pass", "expected_outcome": expected,
            "observed_outcome": observed}
