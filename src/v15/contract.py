from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import ClassVar, override

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="forbid", strict=True
    )


@unique
class V15FailureCode(StrEnum):
    APPROVAL_REQUIRED = "V15_APPROVAL_REQUIRED"
    APPROVAL_MISMATCH = "V15_APPROVAL_MISMATCH"
    PROMOTION_BLOCKED = "V15_PROMOTION_BLOCKED"
    INVALID_TRANSITION = "V15_INVALID_TRANSITION"
    CHAIN_MISMATCH = "V15_CHAIN_MISMATCH"
    UPSTREAM_EVIDENCE = "V15_UPSTREAM_EVIDENCE"
    MIRROR_NOT_ISOLATED = "V15_MIRROR_NOT_ISOLATED"
    LEDGER_EVIDENCE = "V15_LEDGER_EVIDENCE"
    SAMPLE_INSUFFICIENT = "V15_SAMPLE_INSUFFICIENT"
    COMPARISON_INVALID = "V15_COMPARISON_INVALID"
    RECOVERY_BLOCKED = "V15_RECOVERY_BLOCKED"
    TERMINATION_INCOMPLETE = "V15_TERMINATION_INCOMPLETE"
    VERSION_RETIRED = "V15_VERSION_RETIRED"
    PAPER_BOUNDARY = "V15_PAPER_BOUNDARY"
    ARTIFACT_MALFORMED = "V15_ARTIFACT_MALFORMED"
    BUNDLE_MISMATCH = "V15_BUNDLE_MISMATCH"
    SIDE_EFFECT = "V15_SIDE_EFFECT"
    CLI_ARGUMENT = "V15_CLI_ARGUMENT"


@dataclass(frozen=True, slots=True)
class V15Failure(Exception):
    code: V15FailureCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"
