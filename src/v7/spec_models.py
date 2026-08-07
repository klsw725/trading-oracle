from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, override

from pydantic import BaseModel, ConfigDict


type SpecErrorCode = Literal[
    "V7_SPEC_MALFORMED",
    "V7_SPEC_PATH_UNSAFE",
    "V7_PRD_ROW_MISSING",
    "V7_PRD_LINK_MISSING",
    "V7_PRD_LINK_DUPLICATE",
    "V7_PRD_LINK_BROKEN",
    "V7_PRD_BIDIRECTIONAL_GAP",
    "ILLEGAL_PROMOTION_JUMP",
    "COUNT_USED_AS_QUALITY",
    "REJECT_NO_INCREMENTAL_VALUE",
    "REJECT_LATENCY_ONLY",
    "FALLBACK_USES_INELIGIBLE_SOURCE",
    "STALE_CACHE_POLICY_MISMATCH",
    "POLICY_HASH_MISMATCH",
]


@dataclass(frozen=True, slots=True)
class SpecVerificationError(ValueError):
    code: SpecErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class SpecHappyPromotion(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    source_bundle_id: str
    provenance_gate: str
    quality_gate: str
    value_gate: str
    traffic_path: tuple[str, ...]
    final_state: str
    expected_code: str


class SpecHarmfulRetirement(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    source_bundle_id: str
    incident_code: str
    previous_state: str
    previous_traffic_share: str
    disable_state: str
    disable_traffic_share: str
    retirement_reason: str
    final_state: str
    fallback_removed: bool
    current_cache_allowed: bool
    expected_code: str


class SpecThresholds(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    quality_min_label: str
    coverage_rate_min: str
    target_coverage_rate_min: str
    p95_added_wall_ms_max: int
    mean_added_wall_ms_max: int
    added_prompt_tokens_per_ticker_max: int
    timeout_rate_max: str
    harm_rate_max: str
    severe_harm_rate_max: str


class SpecContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    contract_id: str
    flow: tuple[str, ...]
    required_prds: tuple[str, ...]
    local_prd_links: tuple[str, ...]
    states: tuple[str, ...]
    happy_promotion_fixture: SpecHappyPromotion
    harmful_retirement_fixture: SpecHarmfulRetirement
    success_thresholds: SpecThresholds
    required_mutations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrdDocument:
    prd_id: str
    path: Path
    text: str


@dataclass(frozen=True, slots=True)
class SpecBundle:
    spec_path: Path
    spec_text: str
    prds: tuple[PrdDocument, ...]


@dataclass(frozen=True, slots=True)
class SpecVerificationReport:
    schema_version: str
    json_block_count: int
    linked_prd_count: int
