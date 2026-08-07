from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from src.v6.models import BoundaryModel, JsonBoundary

from .models import HashText

type SourceKind = Literal[
    "market_price",
    "fundamental_equity",
    "news_search",
    "web_context",
    "macro_timeseries_daily",
    "macro_timeseries_monthly",
    "local_cache",
]
type ReliabilityClass = Literal[
    "primary_disclosure",
    "exchange_or_regulator",
    "wire_or_major_media",
    "broker_research",
    "syndicated_media",
    "social_or_video",
    "unknown",
]
type ProvenanceSourceKind = Literal[
    "broker_api",
    "exchange_dataset",
    "finance_library",
    "web_page",
    "search_result",
    "manual_fixture",
    "local_cache",
]


class CoverageBinding(BoundaryModel):
    market: Annotated[str, Field(min_length=1)]
    exchange: Annotated[str, Field(min_length=1)]
    symbol_namespace: Annotated[str, Field(min_length=1)]


class SourceMetadata(BoundaryModel):
    source_id: Annotated[str, Field(min_length=1)]
    adapter_id: Annotated[str, Field(min_length=1)]
    provenance_source_kind: ProvenanceSourceKind
    quality_source_kind: SourceKind
    reliability_class: ReliabilityClass
    source_family: Annotated[str, Field(min_length=1)]
    canonical_host: Annotated[str, Field(min_length=1)]
    capabilities: tuple[Annotated[str, Field(min_length=1)], ...]
    coverage: CoverageBinding
    upstream_source_id: str | None = None


class SourceMetadataRegistryBody(BoundaryModel):
    schema_version: Literal["v7.quality_source_metadata_registry.1"]
    generated_at: AwareDatetime
    expires_at: AwareDatetime
    entries: Annotated[tuple[SourceMetadata, ...], Field(min_length=1)]


class SourceMetadataRegistry(SourceMetadataRegistryBody):
    registry_root: HashText


class TrustedBundleFixture(BoundaryModel):
    trusted_raw_payload: JsonBoundary


class QualityTrustFixture(BoundaryModel):
    registry: SourceMetadataRegistry
    bundle_contexts: Annotated[tuple[TrustedBundleFixture, ...], Field(min_length=1)]


class QualityTrustExpectation(BoundaryModel):
    expected_registry_root: HashText
    expected_bundle_roots: Annotated[tuple[HashText, ...], Field(min_length=1)]


class QualityTrustDocument(BoundaryModel):
    schema_version: Literal["v7.quality_freshness_dedup.trust.1"]
    contract_id: Literal["quality_freshness_dedup_prd02"]
    primary: QualityTrustExpectation
    fallback: QualityTrustExpectation
