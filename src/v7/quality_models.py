from dataclasses import dataclass
from typing import Annotated, Literal, override

from pydantic import AwareDatetime, Field

from src.v6.models import BoundaryModel

from .models import HashText, PersistedProvenanceBundle
from .quality_registry_models import QualityTrustFixture, ReliabilityClass

QualityErrorCode = Literal[
    "MALFORMED_QUALITY_PAYLOAD",
    "REQUIRED_FIELD_MISSING",
    "PRD01_LINEAGE_INVALID",
    "TRUSTED_QUALITY_CONTEXT_REQUIRED",
    "SOURCE_REGISTRY_INVALID",
    "SOURCE_REGISTRY_STALE",
    "SOURCE_METADATA_MISSING",
    "SOURCE_METADATA_MISMATCH",
    "CACHE_LINEAGE_INVALID",
    "NORMALIZED_CLAIM_INVALID",
    "PROVENANCE_REUSED",
    "STALE_MISLABELED_FRESH",
    "DEDUP_KEY_HASH_MISMATCH",
    "COUNT_USED_AS_QUALITY",
    "SCORE_COMPONENT_MISMATCH",
    "QUALITY_LABEL_MISMATCH",
    "DIRTY_SUBJECT_MISMATCH",
    "MISLEADING_SUMMARY",
    "CONTRADICTION_UNRESOLVED",
    "UNTRUSTED_TEXT_PROMPT_INJECTION",
    "SECRET_LEAKAGE_DETECTED",
    "FALLBACK_CHAIN_REASON_REQUIRED",
    "FALLBACK_PROVENANCE_MISSING",
    "ARTIFACT_HASH_MISMATCH",
    "OUTPUT_PATH_UNSAFE",
]
FreshnessLabel = Literal["fresh", "stale", "expired", "degraded", "missing"]
QualityLabel = Literal["high", "usable", "degraded", "blocked"]


@dataclass(frozen=True, slots=True)
class QualityContractError(ValueError):
    code: QualityErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class Subject(BoundaryModel):
    market: Annotated[str, Field(min_length=1)]
    ticker: Annotated[str, Field(min_length=1)]
    name_hash: HashText

    @property
    def subject_id(self) -> str:
        return f"{self.market}:{self.ticker}"


class SourceBundleEvidence(BoundaryModel):
    record_id: Annotated[str, Field(min_length=1)]
    bundle: PersistedProvenanceBundle
    upstream_bundle: PersistedProvenanceBundle | None = None


class FallbackLink(BoundaryModel):
    parent_artifact_hash: HashText
    reason: str
    contradiction_link: HashText | None


class QualityBuildInput(BoundaryModel):
    schema_version: Literal["v7.quality_freshness_dedup.build.2"]
    generated_at: AwareDatetime
    subject: Subject
    sources: Annotated[tuple[SourceBundleEvidence, ...], Field(min_length=1)]
    fallback_for: FallbackLink | None = None


class FreshnessAssessment(BoundaryModel):
    label: FreshnessLabel
    age_hours: float | None
    current_sla_hours: float | None
    audit_ttl_hours: float | None
    expires_after_hours: float | None
    audit_status: Literal["active", "retained", "expired", "unavailable"]


class SourceAssessment(BoundaryModel):
    record_id: str
    source_id: str
    provenance_hash: HashText
    manifest_root: HashText
    registry_root: HashText
    upstream_provenance_hash: HashText | None
    freshness: FreshnessAssessment
    claim_fingerprint: HashText
    dedup_key: HashText
    cluster_id: Annotated[str, Field(pattern=r"^qcluster_[0-9a-f]{20}$")]
    duplicate_label: Literal["unique", "representative", "duplicate", "near_duplicate"]


class DuplicateCluster(BoundaryModel):
    cluster_id: Annotated[str, Field(pattern=r"^qcluster_[0-9a-f]{20}$")]
    dedup_key: HashText
    representative_ref: HashText
    duplicate_refs: tuple[HashText, ...]
    near_duplicate_cluster_ids: tuple[str, ...]
    independent_evidence_count: Literal[1]
    duplicate_count: Annotated[int, Field(strict=True, ge=0)]


class ClaimAssessment(BoundaryModel):
    claim_id: Annotated[str, Field(pattern=r"^qclaim_[0-9a-f]{20}$")]
    claim_text_hash: HashText
    supporting_cluster_ids: tuple[str, ...]
    opposing_cluster_ids: tuple[str, ...]
    numeric_consistency: Literal["match", "range_match", "mismatch", "not_applicable"]
    source_reliability_class: ReliabilityClass


class ScoreBreakdown(BoundaryModel):
    freshness_fit: Annotated[int, Field(strict=True, ge=0, le=20)]
    source_reliability: Annotated[int, Field(strict=True, ge=0, le=20)]
    factuality_support: Annotated[int, Field(strict=True, ge=0, le=25)]
    contradiction_risk: Annotated[int, Field(strict=True, ge=0, le=20)]
    dedup_integrity: Annotated[int, Field(strict=True, ge=0, le=10)]
    prompt_safety: Annotated[int, Field(strict=True, ge=0, le=5)]


class QualitySummary(BoundaryModel):
    raw_result_count: Annotated[int, Field(strict=True, ge=0)]
    cluster_count: Annotated[int, Field(strict=True, ge=0)]
    independent_evidence_count: Annotated[int, Field(strict=True, ge=0)]
    fresh_count: Annotated[int, Field(strict=True, ge=0)]
    quality_count: Annotated[int, Field(strict=True, ge=0)]


class QualityArtifact(BoundaryModel):
    schema_version: Literal["v7.quality_freshness_dedup.artifact.2"]
    contract_id: Literal["quality_freshness_dedup_prd02"]
    generated_at: AwareDatetime
    source_registry_root: HashText
    build_input: QualityBuildInput
    source_results: tuple[SourceAssessment, ...]
    clusters: tuple[DuplicateCluster, ...]
    claims: tuple[ClaimAssessment, ...]
    freshness_label: FreshnessLabel
    quality_label: QualityLabel
    quality_score: Annotated[int, Field(strict=True, ge=0, le=100)]
    score_breakdown: ScoreBreakdown
    summary: QualitySummary
    fallback: FallbackLink | None
    result_label: Literal["pass", "degraded", "blocked"]
    runtime_adoption: Literal["absent"]
    artifact_hash: HashText


class QualityFixture(BoundaryModel):
    schema_version: Literal["v7.quality_freshness_dedup.prd02.2"]
    contract_id: Literal["quality_freshness_dedup_prd02"]
    primary_input: QualityBuildInput
    primary_evidence: QualityTrustFixture
    fallback_input: QualityBuildInput
    fallback_evidence: QualityTrustFixture
    fallback_reason: str
