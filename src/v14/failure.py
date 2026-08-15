from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import override


@unique
class V14FailureCode(StrEnum):
    VALIDATION_TUNE = "V14_VALIDATION_TUNE"
    HOLDOUT_REUSE = "V14_HOLDOUT_REUSE"
    MANIFEST_MISMATCH = "V14_MANIFEST_MISMATCH"
    SAMPLE_INSUFFICIENT = "V14_SAMPLE_INSUFFICIENT"
    VALIDATION_GATE = "V14_VALIDATION_GATE"
    MULTIPLE_TESTING = "V14_MULTIPLE_TESTING"
    COHORT_CONTINUITY = "V14_COHORT_CONTINUITY"
    VERDICT = "V14_VERDICT"
    POINT_IN_TIME = "V14_POINT_IN_TIME"
    MANIFEST_INCOMPLETE = "V14_MANIFEST_INCOMPLETE"
    ARTIFACT_MALFORMED = "V14_ARTIFACT_MALFORMED"
    HASH_MISMATCH = "V14_HASH_MISMATCH"
    CLI_ARGUMENT = "V14_CLI_ARGUMENT"
    INPUT_READ = "V14_INPUT_READ"


@dataclass(frozen=True, slots=True)
class V14Failure(Exception):
    code: V14FailureCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"
