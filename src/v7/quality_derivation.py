import re
from typing import Final
from urllib.parse import urlsplit

from pydantic import ValidationError

from .artifact import verify_persisted_bundle
from .models import PersistedProvenanceBundle, ProvenanceContractError, ProvenanceEnvelope
from .quality_derived_models import DerivedSourceEvidence, NormalizedQualityRecord
from .quality_models import QualityBuildInput, QualityContractError, SourceBundleEvidence
from .quality_registry import QualityTrustContext, bundle_trust, require_trusted_context, source_metadata
from .quality_registry_models import SourceKind, SourceMetadata
from .redaction import contains_secret

_INJECTION: Final = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions|system\s+prompt|developer\s+message)",
    re.IGNORECASE,
)


def _verified(bundle: PersistedProvenanceBundle, context: QualityTrustContext) -> ProvenanceEnvelope:
    trust = bundle_trust(bundle.trusted_payload_manifest.manifest_hash, context)
    try:
        return verify_persisted_bundle(bundle, trust.expected_root, trust.raw_payload)
    except ProvenanceContractError as error:
        raise QualityContractError("PRD01_LINEAGE_INVALID", str(error)) from error


def _normalized(artifact: ProvenanceEnvelope) -> NormalizedQualityRecord:
    try:
        return NormalizedQualityRecord.model_validate(artifact.normalized_record.root)
    except ValidationError as error:
        raise QualityContractError("NORMALIZED_CLAIM_INVALID", str(error)) from error


def _metadata(artifact: ProvenanceEnvelope, context: QualityTrustContext) -> SourceMetadata:
    metadata = source_metadata(artifact.source_identity.source_id, context)
    coverage = artifact.market_coverage
    declared = (
        metadata.adapter_id,
        metadata.provenance_source_kind,
        metadata.capabilities,
        metadata.coverage.market,
        metadata.coverage.exchange,
        metadata.coverage.symbol_namespace,
    )
    observed = (
        artifact.adapter_id,
        artifact.source_identity.source_kind,
        artifact.capabilities,
        coverage.actual_market,
        coverage.actual_exchange,
        coverage.symbol_namespace,
    )
    if declared != observed:
        raise QualityContractError("SOURCE_METADATA_MISMATCH", artifact.source_identity.source_id)
    return metadata


def _cache_kind(
    source: SourceBundleEvidence,
    record: NormalizedQualityRecord,
    metadata: SourceMetadata,
    context: QualityTrustContext,
) -> tuple[SourceKind, str | None]:
    if metadata.quality_source_kind != "local_cache":
        if source.upstream_bundle is not None or record.upstream_provenance_hash is not None:
            raise QualityContractError("CACHE_LINEAGE_INVALID", "non-cache source carries upstream lineage")
        return metadata.quality_source_kind, None
    if source.upstream_bundle is None or metadata.upstream_source_id is None:
        raise QualityContractError("CACHE_LINEAGE_INVALID", "cache requires trusted upstream bundle")
    upstream = _verified(source.upstream_bundle, context)
    upstream_metadata = _metadata(upstream, context)
    if upstream_metadata.quality_source_kind == "local_cache":
        raise QualityContractError("CACHE_LINEAGE_INVALID", "cache upstream cannot be another cache")
    if metadata.upstream_source_id != upstream.source_identity.source_id:
        raise QualityContractError("CACHE_LINEAGE_INVALID", "registry upstream source mismatch")
    if record.upstream_provenance_hash != upstream.provenance_hash:
        raise QualityContractError("CACHE_LINEAGE_INVALID", "normalized upstream provenance mismatch")
    return upstream_metadata.quality_source_kind, upstream.provenance_hash


def _derive(source: SourceBundleEvidence, value: QualityBuildInput, context: QualityTrustContext) -> DerivedSourceEvidence:
    artifact = _verified(source.bundle, context)
    metadata = _metadata(artifact, context)
    record = _normalized(artifact)
    if record.market != value.subject.market or record.ticker != value.subject.ticker:
        raise QualityContractError("DIRTY_SUBJECT_MISMATCH", source.record_id)
    host = (urlsplit(record.canonical_url).hostname or "").lower()
    if host != metadata.canonical_host.lower():
        raise QualityContractError("SOURCE_METADATA_MISMATCH", "canonical host differs from registry")
    if contains_secret(artifact.normalized_record.root) or any(contains_secret({"text": text}) for text in record.untrusted_text):
        raise QualityContractError("SECRET_LEAKAGE_DETECTED", source.record_id)
    if any(_INJECTION.search(text) for text in record.untrusted_text):
        raise QualityContractError("UNTRUSTED_TEXT_PROMPT_INJECTION", source.record_id)
    effective_kind, upstream_hash = _cache_kind(source, record, metadata, context)
    return DerivedSourceEvidence(
        record_id=source.record_id,
        source_id=artifact.source_identity.source_id,
        provenance=artifact,
        manifest_root=source.bundle.trusted_payload_manifest.manifest_hash,
        registry_root=str(context.registry_root),
        source_kind=effective_kind,
        upstream_provenance_hash=upstream_hash,
        subject_id=value.subject.subject_id,
        event_date=record.event_date,
        source_family=metadata.source_family,
        canonical_url=record.canonical_url,
        canonical_title=record.canonical_title,
        claim_text=record.claim.text,
        predicate=record.claim.predicate,
        object_value=record.claim.object_value,
        polarity=record.claim.polarity,
        numeric_consistency=record.claim.numeric_consistency,
        reliability_class=metadata.reliability_class,
        untrusted_text=record.untrusted_text,
    )


def derive_quality_sources(value: QualityBuildInput, context: QualityTrustContext) -> tuple[DerivedSourceEvidence, ...]:
    require_trusted_context(context)
    if value.generated_at != context.evaluated_at:
        raise QualityContractError("SOURCE_REGISTRY_INVALID", "compiler time differs from trusted context")
    ordered = tuple(sorted(value.sources, key=lambda item: item.record_id))
    if len({item.record_id for item in ordered}) != len(ordered):
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "record_id must be unique")
    provenance_hashes = tuple(item.bundle.artifact.provenance_hash for item in ordered)
    if len(set(provenance_hashes)) != len(provenance_hashes):
        raise QualityContractError("PROVENANCE_REUSED", "one provenance may appear only once")
    return tuple(_derive(source, value, context) for source in ordered)
