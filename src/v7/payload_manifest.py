from dataclasses import dataclass, field

from src.v4.models import JsonValue, canonical_hash
from src.v6.models import JsonBoundary

from .models import (
    BuildContext,
    ProvenanceContractError,
    ProvenanceEnvelope,
    TrustedManifestRoot,
    TrustedPayloadManifest,
)
from .redaction import redact

_MANIFEST_HASH_FIELD = {"manifest_hash"}


class _TrustIssuer:
    pass


_ISSUER = _TrustIssuer()


@dataclass(frozen=True, slots=True)
class TrustedPayloadContext:
    manifest: TrustedPayloadManifest
    trusted_root: TrustedManifestRoot
    raw_payload: JsonValue
    _issuer: _TrustIssuer = field(repr=False)

    def issued_by(self, issuer: _TrustIssuer) -> bool:
        return self._issuer is issuer


def manifest_hash(manifest: TrustedPayloadManifest) -> str:
    body = manifest.model_dump(mode="json", exclude=_MANIFEST_HASH_FIELD)
    return str(canonical_hash(JsonBoundary.model_validate(body).root))


def _verify_manifest(
    manifest: TrustedPayloadManifest,
    expected_root: TrustedManifestRoot,
    raw_payload: JsonValue,
) -> None:
    if str(expected_root) != manifest.manifest_hash or manifest_hash(manifest) != manifest.manifest_hash:
        raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "manifest root mismatch")
    if str(canonical_hash(raw_payload)) != manifest.raw_preimage_hash:
        raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "raw preimage hash mismatch")
    redacted = redact(raw_payload)
    if redacted.value != manifest.redacted_payload.root:
        raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "redacted payload mismatch")
    if str(canonical_hash(redacted.value)) != manifest.redacted_payload_hash:
        raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "redacted payload hash mismatch")
    if redacted.replacement_count != manifest.redaction_report.replacement_count:
        raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "redaction count mismatch")
    normalized = manifest.normalized_source_input.root
    if str(canonical_hash(normalized)) != manifest.normalized_source_input_hash:
        raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "normalized input hash mismatch")
    provenance = manifest.provenance_body.root
    if str(canonical_hash(provenance)) != manifest.provenance_body_hash:
        raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "provenance body hash mismatch")


def trust_payload_manifest(
    manifest: TrustedPayloadManifest,
    expected_root: TrustedManifestRoot,
    raw_payload: JsonValue,
) -> TrustedPayloadContext:
    _verify_manifest(manifest, expected_root, raw_payload)
    return TrustedPayloadContext(manifest, expected_root, raw_payload, _ISSUER)


def build_payload_context(
    artifact: ProvenanceEnvelope,
    context: BuildContext,
) -> TrustedPayloadContext:
    redacted = redact(context.raw_payload)
    report = artifact.redaction_report.model_copy(
        update={"replacement_count": redacted.replacement_count}
    )
    provenance_body = JsonBoundary.model_validate(
        artifact.model_dump(
            mode="json",
            exclude={"raw_payload_hash", "normalized_record_hash", "provenance_hash"},
        )
    ).root
    body = JsonBoundary.model_validate(
        {
            "schema_version": "v7.source_adapter_provenance.trusted-payload.1",
            "adapter_id": artifact.adapter_id,
            "source_identity": artifact.source_identity.model_dump(mode="json"),
            "raw_preimage_hash": str(canonical_hash(context.raw_payload)),
            "redacted_payload": redacted.value,
            "redacted_payload_hash": str(canonical_hash(redacted.value)),
            "redaction_report": report.model_dump(mode="json"),
            "normalized_source_input": artifact.normalized_record.root,
            "normalized_source_input_hash": artifact.normalized_record_hash,
            "provenance_body": provenance_body,
            "provenance_body_hash": artifact.provenance_hash,
            "evaluated_at": context.evaluated_at.isoformat(),
            "freshness_sla_hours": context.freshness_sla_hours,
        }
    ).root
    root = str(canonical_hash(body))
    match body:  # noqa: MATCH_OK - constructed manifest body is an object
        case dict() as record:
            manifest = TrustedPayloadManifest.model_validate({**record, "manifest_hash": root})
        case _:
            raise ProvenanceContractError("TRUSTED_MANIFEST_INVALID", "manifest body is not an object")
    return trust_payload_manifest(manifest, TrustedManifestRoot(root), context.raw_payload)


def artifact_context(
    artifact: ProvenanceEnvelope,
    context: TrustedPayloadContext,
) -> BuildContext:
    if not context.issued_by(_ISSUER):
        raise ProvenanceContractError("TRUSTED_PAYLOAD_REQUIRED", "context was not issued by a trusted boundary")
    manifest = context.manifest
    _verify_manifest(manifest, context.trusted_root, context.raw_payload)
    if artifact.adapter_id != manifest.adapter_id or artifact.source_identity != manifest.source_identity:
        raise ProvenanceContractError("CONTEXT_ARTIFACT_MISMATCH", "adapter or source identity mismatch")
    if artifact.normalized_record.root != manifest.normalized_source_input.root:
        raise ProvenanceContractError("CONTEXT_ARTIFACT_MISMATCH", "normalized source input mismatch")
    if artifact.normalized_record_hash != manifest.normalized_source_input_hash:
        raise ProvenanceContractError("CONTEXT_ARTIFACT_MISMATCH", "normalized source hash mismatch")
    if artifact.raw_payload_hash != manifest.redacted_payload_hash:
        raise ProvenanceContractError("CONTEXT_ARTIFACT_MISMATCH", "redacted payload hash mismatch")
    if artifact.redaction_report != manifest.redaction_report:
        raise ProvenanceContractError("CONTEXT_ARTIFACT_MISMATCH", "redaction report mismatch")
    body = JsonBoundary.model_validate(
        artifact.model_dump(
            mode="json",
            exclude={"raw_payload_hash", "normalized_record_hash", "provenance_hash"},
        )
    ).root
    if body != manifest.provenance_body.root or artifact.provenance_hash != manifest.provenance_body_hash:
        raise ProvenanceContractError("CONTEXT_ARTIFACT_MISMATCH", "provenance body mismatch")
    return BuildContext(
        raw_payload=context.raw_payload,
        evaluated_at=manifest.evaluated_at,
        freshness_sla_hours=manifest.freshness_sla_hours,
    )
