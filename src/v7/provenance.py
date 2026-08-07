from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash
from src.v6.models import JsonBoundary

from .models import BuildContext, ErrorCode, ProvenanceContractError, ProvenanceEnvelope
from .payload_manifest import TrustedPayloadContext, artifact_context
from .redaction import contains_secret, contains_trusted_injection, redact

PRD02_FRESHNESS_SLA_HOURS: Final[dict[str, float]] = {
    "market_price": 0.5,
    "fundamental_equity": 168.0,
    "news_search": 168.0,
    "web_context": 168.0,
    "macro_timeseries_daily": 24.0,
    "macro_timeseries_monthly": 720.0,
}
HASH_FIELDS: Final = {"raw_payload_hash", "normalized_record_hash", "provenance_hash"}
REQUIRED_FIELDS: Final = (
    "adapter_id",
    "adapter_version",
    "source_identity",
    "auth_boundary",
    "market_coverage",
    "fetch_started_at",
    "fetched_at",
    "as_of",
    "freshness_status",
    "license",
    "retention",
    "normalized_record",
    "raw_payload_hash",
    "normalized_record_hash",
    "provenance_hash",
    "capabilities",
    "redaction_report",
    "error_envelope",
)


def _fail(code: ErrorCode, detail: str) -> ProvenanceContractError:
    return ProvenanceContractError(code, detail)


def _required(record: dict[str, JsonValue]) -> None:
    for field in REQUIRED_FIELDS:
        if field in record:
            continue
        if field == "as_of":
            raise _fail("AS_OF_MISSING", "as_of is required independently of fetched_at")
        if field == "auth_boundary":
            raise _fail("AUTH_BOUNDARY_MISSING", "auth boundary is required")
        if field == "raw_payload_hash":
            raise _fail("RAW_HASH_MISSING", "raw payload hash is required")
        raise _fail("REQUIRED_FIELD_MISSING", field)


def _as_of_datetime(artifact: ProvenanceEnvelope) -> datetime:
    value = artifact.as_of
    try:
        if value.kind == "session":
            if value.timezone is None:
                raise _fail("MALFORMED_PAYLOAD", "session as_of requires timezone")
            return datetime.fromisoformat(value.value).replace(tzinfo=ZoneInfo(value.timezone))
        parsed = datetime.fromisoformat(value.value)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise _fail("MALFORMED_PAYLOAD", "invalid as_of timestamp") from error
    if parsed.tzinfo is None:
        raise _fail("MALFORMED_PAYLOAD", "as_of timestamp requires timezone")
    return parsed


def _validate_semantics(artifact: ProvenanceEnvelope, context: BuildContext) -> None:
    if artifact.fetch_started_at > artifact.fetched_at:
        raise _fail("MALFORMED_PAYLOAD", "fetched_at precedes fetch_started_at")
    if artifact.source_identity.source_kind == "broker_api" and artifact.auth_boundary.mode == "none":
        raise _fail("AUTH_BOUNDARY_MISSING", "authenticated source declared mode none")
    endpoint = artifact.source_identity.endpoint_label
    if "?" in endpoint or contains_secret(artifact.normalized_record.root):
        raise _fail("SECRET_LEAKAGE_DETECTED", "secret or user material survived redaction")
    coverage = artifact.market_coverage
    if coverage.actual_market not in coverage.declared_markets or coverage.actual_exchange not in coverage.declared_exchanges:
        raise _fail("COVERAGE_MISMATCH", "actual coverage is outside declared coverage")
    if artifact.license.name == "unknown" and (
        artifact.license.redistribution == "allowed" or artifact.retention.user_visible_allowed
    ):
        raise _fail("LICENSE_UNKNOWN_RESTRICTED", "unknown license cannot redistribute raw content")
    if contains_trusted_injection(artifact.normalized_record.root):
        raise _fail("UNTRUSTED_TEXT_PROMPT_INJECTION", "external instruction-like text was marked trusted")
    source = artifact.source_identity
    if source.fallback_from_source_id is not None and source.fallback_provenance_hash is None:
        raise _fail("FALLBACK_PROVENANCE_MISSING", "fallback requires its own provenance link")
    try:
        sla = context.freshness_sla_hours[artifact.adapter_id]
    except KeyError as error:
        raise _fail("MALFORMED_PAYLOAD", "adapter has no PRD02 freshness SLA") from error
    age_hours = (context.evaluated_at - _as_of_datetime(artifact)).total_seconds() / 3600
    if age_hours > sla and artifact.freshness_status == "fresh":
        raise _fail("STALE_SOURCE", "source exceeds PRD02 current-use SLA")
    if artifact.result_status == "pass" and artifact.error_envelope is not None:
        raise _fail("MISLEADING_SUCCESS", "pass result contains an error envelope")
    if artifact.result_status == "pass" and artifact.freshness_status != "fresh":
        raise _fail("MISLEADING_SUCCESS", "pass result is not fresh")


def _validate_hashes(artifact: ProvenanceEnvelope, context: BuildContext) -> None:
    normalized = JsonBoundary.model_validate(artifact.normalized_record).root
    if str(canonical_hash(normalized)) != artifact.normalized_record_hash:
        raise _fail("HASH_MISMATCH", "normalized_record_hash")
    redacted = redact(context.raw_payload)
    expected_raw = str(canonical_hash(redacted.value))
    if expected_raw != artifact.raw_payload_hash:
        code: ErrorCode = "REDACTION_ORDER_INVALID" if redacted.replacement_count else "HASH_MISMATCH"
        raise _fail(code, "raw_payload_hash")
    if redacted.replacement_count != artifact.redaction_report.replacement_count:
        raise _fail("REDACTION_ORDER_INVALID", "redaction report does not describe hashed payload")
    body = artifact.model_dump(mode="json", exclude=HASH_FIELDS)
    if str(canonical_hash(JsonBoundary.model_validate(body).root)) != artifact.provenance_hash:
        raise _fail("HASH_MISMATCH", "provenance_hash")


def compile_provenance(value: JsonValue, context: BuildContext) -> ProvenanceEnvelope:
    match value:  # noqa: MATCH_OK - boundary maps non-object JSON to a contract code
        case dict() as record:
            _required(record)
        case _:
            raise _fail("MALFORMED_PAYLOAD", "artifact must be an object")
    try:
        artifact = ProvenanceEnvelope.model_validate(value)
    except ValidationError as error:
        raise _fail("MALFORMED_PAYLOAD", str(error)) from error
    _validate_semantics(artifact, context)
    _validate_hashes(artifact, context)
    return artifact


def verify_artifact(
    value: JsonValue,
    trusted_context: TrustedPayloadContext | None = None,
) -> ProvenanceEnvelope:
    if trusted_context is None:
        raise _fail("TRUSTED_PAYLOAD_REQUIRED", "standalone verification requires a trusted payload context")
    try:
        artifact = ProvenanceEnvelope.model_validate(value)
    except ValidationError as error:
        raise _fail("MALFORMED_PAYLOAD", str(error)) from error
    return compile_provenance(value, artifact_context(artifact, trusted_context))
