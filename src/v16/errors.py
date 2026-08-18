from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import override


@unique
class FailureCode(StrEnum):
    PROJECT_ROOT_NOT_FOUND = "PROJECT_ROOT_NOT_FOUND"
    CONFIG_PATH_OUTSIDE_ROOT = "CONFIG_PATH_OUTSIDE_ROOT"
    CONFIG_NOT_READABLE = "CONFIG_NOT_READABLE"
    CONFIG_PARSE_ERROR = "CONFIG_PARSE_ERROR"
    UNKNOWN_CONFIG_KEY = "UNKNOWN_CONFIG_KEY"
    UNSUPPORTED_CONFIG_SCHEMA = "UNSUPPORTED_CONFIG_SCHEMA"
    UNKNOWN_POLICY_VERSION = "UNKNOWN_POLICY_VERSION"
    FIXTURE_INVENTORY_MISMATCH = "FIXTURE_INVENTORY_MISMATCH"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    CALENDAR_INVALID = "CALENDAR_INVALID"
    INVALID = "INVALID"
    HASH_MISMATCH = "HASH_MISMATCH"
    INCOMPLETE = "INCOMPLETE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    CLI_USAGE_ERROR = "CLI_USAGE_ERROR"


@dataclass(frozen=True, slots=True)
class V16Failure(Exception):
    code: FailureCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


@dataclass(frozen=True, slots=True)
class AcceptanceError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail
