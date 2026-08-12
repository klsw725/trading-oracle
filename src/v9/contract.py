from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, NewType, override

from pydantic import BaseModel, ConfigDict, TypeAdapter

from src.v4.models import JsonValue


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


class Quality(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class RiskLevel(StrEnum):
    NORMAL = "normal"
    WATCH = "watch"
    BLOCKED = "blocked"


class Condition(StrEnum):
    READY = "ready"
    LOADING = "loading"
    EMPTY = "empty"
    PARTIAL = "partial"
    ERROR = "error"
    MISSING = "missing"


class SourceHealthLabel(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    EXPIRED = "expired"
    BLOCKED = "blocked"
    MISSING = "missing"


SubjectId = NewType("SubjectId", str)
RiskItemId = NewType("RiskItemId", str)
ViewId = NewType("ViewId", str)


@dataclass(frozen=True, slots=True)
class V9ContractError(Exception):
    code: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


_JSON = TypeAdapter[JsonValue](JsonValue)


def model_json(model: BaseModel) -> JsonValue:
    return _JSON.validate_python(model.model_dump(mode="json", exclude_none=False))
