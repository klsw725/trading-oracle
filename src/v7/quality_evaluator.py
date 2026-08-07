from dataclasses import dataclass
from typing import Final

from src.v4.models import JsonValue, canonical_hash

from .dedup import claim_fingerprint, cluster_id, dedup_key
from .freshness import assess_freshness
from .quality_derived_models import DerivedSourceEvidence
from .quality_models import (
    ClaimAssessment,
    DuplicateCluster,
    FreshnessLabel,
    QualityBuildInput,
    QualityLabel,
    QualitySummary,
    ScoreBreakdown,
    SourceAssessment,
)
from .quality_registry_models import ReliabilityClass

_RELIABILITY_POINTS: Final[dict[ReliabilityClass, int]] = {
    "primary_disclosure": 20,
    "exchange_or_regulator": 18,
    "wire_or_major_media": 16,
    "broker_research": 14,
    "syndicated_media": 10,
    "social_or_video": 4,
    "unknown": 0,
}
_FRESHNESS_POINTS: Final[dict[FreshnessLabel, int]] = {
    "fresh": 20,
    "stale": 8,
    "expired": 0,
    "degraded": 5,
    "missing": 0,
}
_FRESHNESS_ORDER: Final[dict[FreshnessLabel, int]] = {
    "fresh": 0,
    "stale": 1,
    "degraded": 2,
    "expired": 3,
    "missing": 4,
}


@dataclass(frozen=True, slots=True)
class LabelEvidence:
    score: int
    freshness: FreshnessLabel
    contradiction: bool
    near_duplicate_reliance: bool
    best_reliability_points: int


@dataclass(frozen=True, slots=True)
class QualityEvaluation:
    source_results: tuple[SourceAssessment, ...]
    clusters: tuple[DuplicateCluster, ...]
    claims: tuple[ClaimAssessment, ...]
    freshness_label: FreshnessLabel
    quality_label: QualityLabel
    quality_score: int
    score_breakdown: ScoreBreakdown
    summary: QualitySummary
    result_label: str


def _groups(sources: tuple[DerivedSourceEvidence, ...]) -> dict[str, tuple[DerivedSourceEvidence, ...]]:
    keys = sorted({dedup_key(source) for source in sources})
    return {
        key: tuple(
            sorted(
                (source for source in sources if dedup_key(source) == key),
                key=lambda item: (item.provenance.provenance_hash, item.record_id),
            )
        )
        for key in keys
    }


def _cluster_data(groups: dict[str, tuple[DerivedSourceEvidence, ...]]) -> tuple[DuplicateCluster, ...]:
    fingerprints = {key: claim_fingerprint(items[0]) for key, items in groups.items()}
    clusters: list[DuplicateCluster] = []
    for key, items in groups.items():
        near = tuple(
            sorted(cluster_id(other) for other, fingerprint in fingerprints.items() if other != key and fingerprint == fingerprints[key])
        )
        clusters.append(
            DuplicateCluster(
                cluster_id=cluster_id(key),
                dedup_key=key,
                representative_ref=items[0].provenance.provenance_hash,
                duplicate_refs=tuple(item.provenance.provenance_hash for item in items[1:]),
                near_duplicate_cluster_ids=near,
                independent_evidence_count=1,
                duplicate_count=len(items) - 1,
            )
        )
    return tuple(sorted(clusters, key=lambda item: item.cluster_id))


def _source_data(value: QualityBuildInput, groups: dict[str, tuple[DerivedSourceEvidence, ...]]) -> tuple[SourceAssessment, ...]:
    results: list[SourceAssessment] = []
    for key, items in groups.items():
        fingerprint = claim_fingerprint(items[0])
        has_near = any(claim_fingerprint(other[0]) == fingerprint for other_key, other in groups.items() if other_key != key)
        for index, source in enumerate(items):
            if index > 0:
                label = "duplicate"
            elif len(items) > 1:
                label = "representative"
            elif has_near:
                label = "near_duplicate"
            else:
                label = "unique"
            results.append(
                SourceAssessment(
                    record_id=source.record_id,
                    source_id=source.source_id,
                    provenance_hash=source.provenance.provenance_hash,
                    manifest_root=source.manifest_root,
                    registry_root=source.registry_root,
                    upstream_provenance_hash=source.upstream_provenance_hash,
                    freshness=assess_freshness(source, value.generated_at),
                    claim_fingerprint=fingerprint,
                    dedup_key=key,
                    cluster_id=cluster_id(key),
                    duplicate_label=label,
                )
            )
    return tuple(sorted(results, key=lambda item: item.record_id))


def _claims(groups: dict[str, tuple[DerivedSourceEvidence, ...]]) -> tuple[ClaimAssessment, ...]:
    representatives = tuple(items[0] for items in groups.values())
    claims: list[ClaimAssessment] = []
    for source in representatives:
        fingerprint = claim_fingerprint(source)
        peers = tuple(item for item in representatives if (item.subject_id, item.event_date, item.predicate) == (source.subject_id, source.event_date, source.predicate))
        supporting = tuple(sorted(cluster_id(dedup_key(item)) for item in peers if item.polarity == source.polarity))
        opposing = tuple(sorted(cluster_id(dedup_key(item)) for item in peers if item.polarity != source.polarity or item.numeric_consistency == "mismatch"))
        identity: JsonValue = {
            "subject": source.subject_id,
            "predicate": source.predicate,
            "object": source.object_value,
            "event_date": source.event_date,
            "source_ref": source.provenance.provenance_hash,
        }
        claims.append(
            ClaimAssessment(
                claim_id=f"qclaim_{str(canonical_hash(identity)).removeprefix('sha256:')[:20]}",
                claim_text_hash=fingerprint,
                supporting_cluster_ids=supporting,
                opposing_cluster_ids=opposing,
                numeric_consistency=source.numeric_consistency,
                source_reliability_class=source.reliability_class,
            )
        )
    return tuple(sorted(claims, key=lambda item: item.claim_id))


def _score(
    sources: tuple[DerivedSourceEvidence, ...],
    results: tuple[SourceAssessment, ...],
    clusters: tuple[DuplicateCluster, ...],
    claims: tuple[ClaimAssessment, ...],
) -> ScoreBreakdown:
    representatives = tuple(source for source in sources if source.provenance.provenance_hash in {cluster.representative_ref for cluster in clusters})
    reliability = round(sum(_RELIABILITY_POINTS[item.reliability_class] for item in representatives) / len(representatives))
    fingerprints = {item.claim_text_hash for item in claims}
    contradiction = any(item.opposing_cluster_ids for item in claims)
    has_near = any(item.near_duplicate_cluster_ids for item in clusters)
    return ScoreBreakdown(
        freshness_fit=min(_FRESHNESS_POINTS[item.freshness.label] for item in results),
        source_reliability=reliability,
        factuality_support=0 if contradiction else 25 if len(fingerprints) >= 2 else 17,
        contradiction_risk=0 if contradiction else 20,
        dedup_integrity=7 if has_near else 10,
        prompt_safety=5,
    )


def label_quality(evidence: LabelEvidence) -> QualityLabel:
    if evidence.contradiction or evidence.freshness == "expired" or evidence.score < 30:
        return "blocked"
    if evidence.freshness != "fresh" or evidence.score < 60 or evidence.near_duplicate_reliance:
        return "degraded"
    if evidence.score < 80 or evidence.best_reliability_points <= 10:
        return "usable"
    return "high"


def evaluate_quality(value: QualityBuildInput, sources: tuple[DerivedSourceEvidence, ...]) -> QualityEvaluation:
    groups = _groups(sources)
    clusters = _cluster_data(groups)
    results = _source_data(value, groups)
    claims = _claims(groups)
    breakdown = _score(sources, results, clusters, claims)
    score = sum(breakdown.model_dump().values())
    freshness: FreshnessLabel = results[0].freshness.label
    for item in results[1:]:
        if _FRESHNESS_ORDER[item.freshness.label] > _FRESHNESS_ORDER[freshness]:
            freshness = item.freshness.label
    contradiction = any(item.opposing_cluster_ids for item in claims)
    has_near = any(item.near_duplicate_cluster_ids for item in clusters)
    label = label_quality(
        LabelEvidence(
            score=score,
            freshness=freshness,
            contradiction=contradiction,
            near_duplicate_reliance=has_near,
            best_reliability_points=max(_RELIABILITY_POINTS[item.reliability_class] for item in sources),
        )
    )
    fingerprints = {item.claim_fingerprint for item in results}
    fresh_fingerprints = {item.claim_fingerprint for item in results if item.freshness.label == "fresh" and item.duplicate_label != "duplicate"}
    summary = QualitySummary(
        raw_result_count=len(sources),
        cluster_count=len(clusters),
        independent_evidence_count=len(fingerprints),
        fresh_count=len(fresh_fingerprints),
        quality_count=len(fingerprints) if label in ("high", "usable") else 0,
    )
    result_label = "blocked" if label == "blocked" else "degraded" if label == "degraded" else "pass"
    return QualityEvaluation(results, clusters, claims, freshness, label, score, breakdown, summary, result_label)
