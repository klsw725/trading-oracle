from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, NewType, override

from pydantic import AwareDatetime, Field

from src.v4.models import JsonValue
from src.v6.models import BoundaryModel, JsonBoundary

HashText = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
TrustedManifestRoot = NewType("TrustedManifestRoot", str)
ErrorCode = Literal[
    "AS_OF_MISSING",
    "AUTH_BOUNDARY_MISSING",
    "SECRET_LEAKAGE_DETECTED",
    "COVERAGE_MISMATCH",
    "LICENSE_UNKNOWN_RESTRICTED",
    "RAW_HASH_MISSING",
    "NORMALIZATION_FAILED",
    "STALE_SOURCE",
    "MALFORMED_PAYLOAD",
    "UNTRUSTED_TEXT_PROMPT_INJECTION",
    "SOURCE_UNAVAILABLE",
    "REQUIRED_FIELD_MISSING",
    "HASH_MISMATCH",
    "MISLEADING_SUCCESS",
    "REDACTION_ORDER_INVALID",
    "FALLBACK_PROVENANCE_MISSING",
    "OUTPUT_PATH_UNSAFE",
    "TRUSTED_PAYLOAD_REQUIRED",
    "TRUSTED_MANIFEST_INVALID",
    "CONTEXT_ARTIFACT_MISMATCH",
]


@dataclass(frozen=True, slots=True)
class ProvenanceContractError(ValueError):
    code: ErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class SourceIdentity(BoundaryModel):
    source_id: Annotated[str, Field(min_length=1)]
    source_kind: Literal[
        "broker_api",
        "exchange_dataset",
        "finance_library",
        "web_page",
        "search_result",
        "manual_fixture",
        "local_cache",
    ]
    endpoint_label: Annotated[str, Field(min_length=1)]
    vendor_default: Literal[False]
    fallback_from_source_id: str | None = None
    fallback_provenance_hash: HashText | None = None


class AuthBoundary(BoundaryModel):
    mode: Literal["none", "api_key", "oauth", "session_cookie", "local_cache", "manual_fixture"]
    scope_label: Annotated[str, Field(min_length=1)]
    secret_material_present: bool
    credential_ref_hash: HashText | None
    loaded_from: Literal["env", "oauth_store", "config", "none"]
    redaction_policy: Literal["adapter-redaction.1"]


class MarketCoverage(BoundaryModel):
    declared_markets: tuple[Annotated[str, Field(min_length=1)], ...]
    declared_exchanges: tuple[Annotated[str, Field(min_length=1)], ...]
    actual_market: Annotated[str, Field(min_length=1)]
    actual_exchange: Annotated[str, Field(min_length=1)]
    symbol_namespace: Annotated[str, Field(min_length=1)]
    currency: Annotated[str, Field(min_length=1)]
    timezone: Annotated[str, Field(min_length=1)]


class AsOf(BoundaryModel):
    kind: Literal["session", "published_at", "release_at", "unknown"]
    value: Annotated[str, Field(min_length=1)]
    timezone: str | None = None


class SourceLicense(BoundaryModel):
    name: Annotated[str, Field(min_length=1)]
    redistribution: Literal["allowed", "internal_only", "hash_only", "forbidden", "unknown"]
    attribution_required: bool | Literal["unknown"]


class Retention(BoundaryModel):
    raw_mode: Literal["store_redacted", "hash_only", "discard_after_hash", "fixture_inline"]
    ttl_hours: Annotated[int, Field(strict=True, ge=0)] | None
    ttl_reason: str | None = None
    user_visible_allowed: bool


class RedactionReport(BoundaryModel):
    policy: Literal["adapter-redaction.1"]
    patterns_checked: tuple[Literal["secret", "token", "cookie", "signed_url", "user_data"], ...]
    replacement_count: Annotated[int, Field(strict=True, ge=0)]


class ErrorEnvelope(BoundaryModel):
    error_code: ErrorCode
    severity: Literal["fail", "degraded", "blocked"]
    message: Annotated[str, Field(min_length=1)]
    retryable: bool
    safe_fallback_allowed: bool
    blocked_fields: tuple[str, ...]
    evidence_ref: HashText


class ProvenanceEnvelope(BoundaryModel):
    schema_version: Literal["v7.source_adapter_provenance.artifact.1"]
    adapter_id: Annotated[str, Field(min_length=1)]
    adapter_version: Annotated[
        str,
        Field(pattern=r"^source-adapter-provenance\.1\+sha256:[0-9a-f]{64}$"),
    ]
    source_identity: SourceIdentity
    auth_boundary: AuthBoundary
    market_coverage: MarketCoverage
    fetch_started_at: AwareDatetime
    fetched_at: AwareDatetime
    as_of: AsOf
    freshness_status: Literal["fresh", "stale", "missing", "degraded", "not_applicable"]
    license: SourceLicense
    retention: Retention
    normalized_record: JsonBoundary
    raw_payload_hash: HashText
    normalized_record_hash: HashText
    provenance_hash: HashText
    capabilities: tuple[Annotated[str, Field(min_length=1)], ...]
    redaction_report: RedactionReport
    error_envelope: ErrorEnvelope | None
    result_status: Literal["pass", "fail", "degraded"]


class ProvenanceFixture(BoundaryModel):
    schema_version: Literal["v7.source_adapter_provenance.prd01.1"]
    contract_id: Literal["source_adapter_provenance_prd01"]
    evaluated_at: AwareDatetime
    freshness_sla_hours: dict[str, float]
    raw_payload: JsonBoundary
    happy_trace_fixture: JsonBoundary


class TrustedPayloadManifest(BoundaryModel):
    schema_version: Literal["v7.source_adapter_provenance.trusted-payload.1"]
    adapter_id: Annotated[str, Field(min_length=1)]
    source_identity: SourceIdentity
    raw_preimage_hash: HashText
    redacted_payload: JsonBoundary
    redacted_payload_hash: HashText
    redaction_report: RedactionReport
    normalized_source_input: JsonBoundary
    normalized_source_input_hash: HashText
    provenance_body: JsonBoundary
    provenance_body_hash: HashText
    evaluated_at: AwareDatetime
    freshness_sla_hours: dict[str, float]
    manifest_hash: HashText


class PersistedProvenanceBundle(BoundaryModel):
    schema_version: Literal["v7.source_adapter_provenance.verification-bundle.1"]
    artifact: ProvenanceEnvelope
    trusted_payload_manifest: TrustedPayloadManifest


@dataclass(frozen=True, slots=True)
class BuildContext:
    raw_payload: JsonValue
    evaluated_at: datetime
    freshness_sla_hours: dict[str, float]
