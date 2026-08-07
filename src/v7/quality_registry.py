from dataclasses import dataclass, field
from datetime import datetime
from typing import NewType

from src.v4.models import JsonValue, canonical_hash
from src.v6.models import JsonBoundary

from .models import TrustedManifestRoot
from .quality_models import QualityContractError
from .quality_registry_models import QualityTrustExpectation, QualityTrustFixture, SourceMetadata, SourceMetadataRegistry

TrustedRegistryRoot = NewType("TrustedRegistryRoot", str)


class _TrustIssuer:
    pass


_ISSUER = _TrustIssuer()


@dataclass(frozen=True, slots=True)
class BundleTrust:
    expected_root: TrustedManifestRoot
    raw_payload: JsonValue


@dataclass(frozen=True, slots=True)
class QualityTrustContext:
    registry: SourceMetadataRegistry
    registry_root: TrustedRegistryRoot
    evaluated_at: datetime
    bundles: tuple[BundleTrust, ...]
    _issuer: _TrustIssuer = field(repr=False)

    def issued_by(self, issuer: _TrustIssuer) -> bool:
        return self._issuer is issuer


def registry_root(registry: SourceMetadataRegistry) -> str:
    body = JsonBoundary.model_validate(registry.model_dump(mode="json", exclude={"registry_root"})).root
    return str(canonical_hash(body))


def trust_quality_fixture(fixture: QualityTrustFixture, expectation: QualityTrustExpectation, evaluated_at: datetime) -> QualityTrustContext:
    expected = expectation.expected_registry_root
    if expected != fixture.registry.registry_root or registry_root(fixture.registry) != expected:
        raise QualityContractError("SOURCE_REGISTRY_INVALID", "registry root mismatch")
    if fixture.registry.generated_at > evaluated_at or evaluated_at > fixture.registry.expires_at:
        raise QualityContractError("SOURCE_REGISTRY_STALE", "registry is outside its trusted validity window")
    source_ids = tuple(item.source_id for item in fixture.registry.entries)
    if len(set(source_ids)) != len(source_ids):
        raise QualityContractError("SOURCE_REGISTRY_INVALID", "source_id entries must be unique")
    if len(fixture.bundle_contexts) != len(expectation.expected_bundle_roots):
        raise QualityContractError("SOURCE_REGISTRY_INVALID", "bundle trust inventory differs")
    bundles = tuple(
        BundleTrust(TrustedManifestRoot(root), item.trusted_raw_payload.root)
        for item, root in zip(fixture.bundle_contexts, expectation.expected_bundle_roots, strict=True)
    )
    if len({str(item.expected_root) for item in bundles}) != len(bundles):
        raise QualityContractError("SOURCE_REGISTRY_INVALID", "bundle trust roots must be unique")
    return QualityTrustContext(fixture.registry, TrustedRegistryRoot(expected), evaluated_at, bundles, _ISSUER)


def require_trusted_context(context: QualityTrustContext) -> None:
    if not context.issued_by(_ISSUER):
        raise QualityContractError("TRUSTED_QUALITY_CONTEXT_REQUIRED", "context was not issued by registry trust boundary")
    if registry_root(context.registry) != str(context.registry_root):
        raise QualityContractError("SOURCE_REGISTRY_INVALID", "registry changed after trust issuance")


def source_metadata(source_id: str, context: QualityTrustContext) -> SourceMetadata:
    require_trusted_context(context)
    matches = tuple(item for item in context.registry.entries if item.source_id == source_id)
    if len(matches) != 1:
        raise QualityContractError("SOURCE_METADATA_MISSING", source_id)
    return matches[0]


def bundle_trust(root: str, context: QualityTrustContext) -> BundleTrust:
    require_trusted_context(context)
    matches = tuple(item for item in context.bundles if str(item.expected_root) == root)
    if len(matches) != 1:
        raise QualityContractError("PRD01_LINEAGE_INVALID", f"trusted bundle root missing: {root}")
    return matches[0]
