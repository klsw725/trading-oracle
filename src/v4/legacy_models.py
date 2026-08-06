from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import NewType

from src.v4.models import ContentHash, JsonValue


LegacySnapshotId = NewType("LegacySnapshotId", str)
LegacyRecommendationId = NewType("LegacyRecommendationId", str)


@unique
class LegacyParseState(StrEnum):
    PARSED = "parsed"
    MALFORMED = "malformed"
    MISSING_REQUIRED_FIELD = "missing_required_field"


@unique
class LegacyMigrationTier(StrEnum):
    T0_SOURCE_INVENTORY = "T0"
    T1_STRUCTURAL_AUDIT = "T1"


@unique
class LegacyProvenance(StrEnum):
    DIRECT = "direct"
    DERIVED = "derived"
    EXTERNAL_BACKFILL = "external_backfill"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class LegacyField:
    value: JsonValue
    provenance: LegacyProvenance


@dataclass(frozen=True, slots=True)
class LegacyRecommendationAudit:
    legacy_recommendation_id: LegacyRecommendationId
    source_record_index: int
    ticker: LegacyField
    name: LegacyField
    recommendation_price: LegacyField
    consensus_verdict: LegacyField
    perspectives: LegacyField
    unknown_native_fields: tuple[str, ...]
    failure_states: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LegacySourceInventory:
    source_path: Path
    source_hash: ContentHash
    byte_length: int
    parse_state: LegacyParseState
    migration_tier: LegacyMigrationTier
    recommendation_count: int
    failure_detail: str | None
    source_snapshot_date: LegacyField
    source_market: LegacyField
    recommendation_records: tuple[LegacyRecommendationAudit, ...]


@dataclass(frozen=True, slots=True)
class LegacyAuditEligibility:
    audit_only: bool = True
    canonical_metric_eligible: bool = False
    calibration_eligible: bool = False
    adaptive_weight_eligible: bool = False
    verbatim_replay_eligible: bool = False
    outcome_replay_eligible: bool = False
    recompute_replay_eligible: bool = False
    outcome_audit_overlay_eligible: bool = True


@dataclass(frozen=True, slots=True)
class LegacyDerivedAudit:
    policy_version: str
    legacy_snapshot_id: LegacySnapshotId
    source_path: Path
    source_hash: ContentHash
    parse_state: LegacyParseState
    migration_tier: LegacyMigrationTier
    recommendation_count: int
    source_snapshot_date: LegacyField
    source_market: LegacyField
    recommendation_records: tuple[LegacyRecommendationAudit, ...]
    eligibility: LegacyAuditEligibility
    derived_artifact_hash: ContentHash
    source_link_hash: ContentHash


@dataclass(frozen=True, slots=True)
class LegacyInventoryReport:
    expected_source_count: int
    records: tuple[LegacySourceInventory, ...]
    parsed_source_count: int
    malformed_source_count: int
    invalid_recommendation_count: int
    source_count_matches_expected: bool
    coverage_complete: bool
    audit_overlay_eligible: bool
    failure_states: tuple[str, ...]
    canonical_metric_eligible_count: int = 0
    calibration_eligible_count: int = 0
