from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from src.v4.models import JsonValue, canonical_hash
from src.v6.models import JsonBoundary

from .artifact import CompiledProvenance, persisted_bundle
from .models import AsOf, BuildContext, PersistedProvenanceBundle
from .payload_manifest import build_payload_context
from .provenance import PRD02_FRESHNESS_SLA_HOURS, compile_provenance
from .quality_models import QualityBuildInput, QualityFixture, SourceBundleEvidence, Subject
from .quality_registry import registry_root
from .quality_registry_models import (
    CoverageBinding,
    ProvenanceSourceKind,
    QualityTrustFixture,
    QualityTrustDocument,
    QualityTrustExpectation,
    ReliabilityClass,
    SourceKind,
    SourceMetadata,
    SourceMetadataRegistry,
    SourceMetadataRegistryBody,
    TrustedBundleFixture,
)
from .redaction import redact

_ADAPTER_VERSION = "source-adapter-provenance.1+sha256:" + "a" * 64


@dataclass(frozen=True, slots=True)
class SourceSeed:
    source_id: str
    provenance_kind: ProvenanceSourceKind
    quality_kind: SourceKind
    reliability: ReliabilityClass
    family: str
    host: str
    normalized_record: JsonValue
    as_of: AsOf
    upstream_source_id: str | None = None
    freshness_status: Literal["fresh", "stale", "degraded"] = "fresh"


@dataclass(frozen=True, slots=True)
class BuiltSource:
    metadata: SourceMetadata
    bundle: PersistedProvenanceBundle
    raw_payload: JsonValue


def _artifact_value(seed: SourceSeed, raw: JsonValue) -> JsonValue:
    redacted = redact(raw)
    normalized_hash = str(canonical_hash(seed.normalized_record))
    body: dict[str, JsonValue] = {
        "schema_version": "v7.source_adapter_provenance.artifact.1",
        "adapter_id": "news_search",
        "adapter_version": _ADAPTER_VERSION,
        "source_identity": {
            "source_id": seed.source_id,
            "source_kind": seed.provenance_kind,
            "endpoint_label": seed.host,
            "vendor_default": False,
            "fallback_from_source_id": None,
            "fallback_provenance_hash": None,
        },
        "auth_boundary": {
            "mode": "local_cache" if seed.provenance_kind == "local_cache" else "none",
            "scope_label": "read_local_cache" if seed.provenance_kind == "local_cache" else "read_public_source",
            "secret_material_present": False,
            "credential_ref_hash": None,
            "loaded_from": "none",
            "redaction_policy": "adapter-redaction.1",
        },
        "market_coverage": {
            "declared_markets": ["KR"],
            "declared_exchanges": ["KOSPI"],
            "actual_market": "KR",
            "actual_exchange": "KOSPI",
            "symbol_namespace": "KRX_CODE",
            "currency": "KRW",
            "timezone": "Asia/Seoul",
        },
        "fetch_started_at": "2026-08-06T09:00:01+09:00",
        "fetched_at": "2026-08-06T09:00:02+09:00",
        "as_of": seed.as_of.model_dump(mode="json"),
        "freshness_status": seed.freshness_status,
        "license": {"name": "fixture", "redistribution": "hash_only", "attribution_required": False},
        "retention": {"raw_mode": "fixture_inline", "ttl_hours": 720, "ttl_reason": "PRD02 fixture", "user_visible_allowed": False},
        "normalized_record": seed.normalized_record,
        "raw_payload_hash": str(canonical_hash(redacted.value)),
        "normalized_record_hash": normalized_hash,
        "provenance_hash": "sha256:" + "0" * 64,
        "capabilities": ["news_claim"],
        "redaction_report": {
            "policy": "adapter-redaction.1",
            "patterns_checked": ["secret", "token", "cookie", "signed_url", "user_data"],
            "replacement_count": redacted.replacement_count,
        },
        "error_envelope": None,
        "result_status": "pass" if seed.freshness_status == "fresh" else "degraded",
    }
    provenance_body = {key: value for key, value in body.items() if key not in {"raw_payload_hash", "normalized_record_hash", "provenance_hash"}}
    body["provenance_hash"] = str(canonical_hash(provenance_body))
    return body


def build_source(seed: SourceSeed, generated_at: datetime) -> BuiltSource:
    raw: JsonValue = {"source_id": seed.source_id, "record": seed.normalized_record}
    context = BuildContext(raw, generated_at, PRD02_FRESHNESS_SLA_HOURS)
    artifact = compile_provenance(_artifact_value(seed, raw), context)
    compiled = CompiledProvenance(artifact, build_payload_context(artifact, context))
    metadata = SourceMetadata(
        source_id=seed.source_id,
        adapter_id=artifact.adapter_id,
        provenance_source_kind=seed.provenance_kind,
        quality_source_kind=seed.quality_kind,
        reliability_class=seed.reliability,
        source_family=seed.family,
        canonical_host=seed.host,
        capabilities=artifact.capabilities,
        coverage=CoverageBinding(market="KR", exchange="KOSPI", symbol_namespace="KRX_CODE"),
        upstream_source_id=seed.upstream_source_id,
    )
    return BuiltSource(metadata, persisted_bundle(compiled), raw)


def claim_record(host: str, title: str, text: str, upstream_hash: str | None = None) -> JsonValue:
    return {
        "record_type": "quality_claim",
        "market": "KR",
        "ticker": "005930",
        "event_date": "2026-08-04",
        "canonical_url": f"https://{host}/article",
        "canonical_title": title,
        "claim": {
            "predicate": "hbm_outlook",
            "object_value": "conditional upside",
            "polarity": "supports",
            "numeric_consistency": "not_applicable",
            "text": text,
        },
        "untrusted_text": [title, text],
        "upstream_provenance_hash": upstream_hash,
    }


def trust_fixture_for_sources(sources: tuple[BuiltSource, ...], generated_at: datetime) -> QualityTrustFixture:
    registry_body = SourceMetadataRegistryBody(
        schema_version="v7.quality_source_metadata_registry.1",
        generated_at=generated_at,
        expires_at=datetime.fromisoformat("2026-08-07T09:30:00+09:00"),
        entries=tuple(source.metadata for source in sources),
    )
    placeholder = "sha256:" + "0" * 64
    registry = SourceMetadataRegistry.model_validate({**registry_body.model_dump(mode="json"), "registry_root": placeholder})
    root = registry_root(registry)
    registry = registry.model_copy(update={"registry_root": root})
    contexts = tuple(
        TrustedBundleFixture(
            trusted_raw_payload=JsonBoundary.model_validate(source.raw_payload),
        )
        for source in sources
    )
    return QualityTrustFixture(registry=registry, bundle_contexts=contexts)


def canonical_quality_fixture() -> QualityFixture:
    generated_at = datetime.fromisoformat("2026-08-06T09:30:00+09:00")
    as_of = AsOf(kind="published_at", value="2026-08-04T08:27:34+00:00", timezone=None)
    title = "Samsung Electronics SK Hynix HBM price target condition"
    text = "HBM execution may support a conditional upside case"
    first = build_source(SourceSeed("news_fixture_a", "search_result", "news_search", "syndicated_media", "msn_representation", "msn.com", claim_record("msn.com", title, text), as_of), generated_at)
    second = build_source(SourceSeed("news_fixture_b", "search_result", "news_search", "syndicated_media", "msn_representation", "msn.com", claim_record("msn.com", title, text), as_of), generated_at)
    fallback_title = "Samsung Electronics filing confirms HBM production milestone"
    fallback_text = "A primary filing confirms the HBM production milestone"
    fallback = build_source(SourceSeed("fallback_disclosure", "search_result", "news_search", "primary_disclosure", "primary_disclosure", "dart.fss.or.kr", claim_record("dart.fss.or.kr", fallback_title, fallback_text), as_of), generated_at)
    subject = Subject(market="KR", ticker="005930", name_hash=str(canonical_hash("Samsung Electronics")))
    primary_input = QualityBuildInput(schema_version="v7.quality_freshness_dedup.build.2", generated_at=generated_at, subject=subject, sources=(SourceBundleEvidence(record_id="news-a", bundle=first.bundle), SourceBundleEvidence(record_id="news-b", bundle=second.bundle)))
    fallback_input = QualityBuildInput(schema_version="v7.quality_freshness_dedup.build.2", generated_at=generated_at, subject=subject, sources=(SourceBundleEvidence(record_id="fallback-a", bundle=fallback.bundle),))
    return QualityFixture(
        schema_version="v7.quality_freshness_dedup.prd02.2",
        contract_id="quality_freshness_dedup_prd02",
        primary_input=primary_input,
        primary_evidence=trust_fixture_for_sources((first, second), generated_at),
        fallback_input=fallback_input,
        fallback_evidence=trust_fixture_for_sources((fallback,), generated_at),
        fallback_reason="syndicated cluster requires independent primary confirmation",
    )


def canonical_quality_trust_document(fixture: QualityFixture) -> QualityTrustDocument:
    return QualityTrustDocument(
        schema_version="v7.quality_freshness_dedup.trust.1",
        contract_id="quality_freshness_dedup_prd02",
        primary=QualityTrustExpectation(
            expected_registry_root=fixture.primary_evidence.registry.registry_root,
            expected_bundle_roots=tuple(item.bundle.trusted_payload_manifest.manifest_hash for item in fixture.primary_input.sources),
        ),
        fallback=QualityTrustExpectation(
            expected_registry_root=fixture.fallback_evidence.registry.registry_root,
            expected_bundle_roots=tuple(item.bundle.trusted_payload_manifest.manifest_hash for item in fixture.fallback_input.sources),
        ),
    )
