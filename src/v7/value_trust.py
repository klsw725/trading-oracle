from dataclasses import dataclass, field
from typing import NewType

from src.v4.models import canonical_hash
from src.v6.models import JsonBoundary

from .models import TrustedManifestRoot
from .payload_manifest import TrustedPayloadContext, trust_payload_manifest
from .quality_registry import QualityTrustContext, bundle_trust, trust_quality_fixture
from .quality_models import QualityContractError
from .models import ProvenanceContractError
from .value_input import ValueFixture, ValueTrustDocument
from .value_models import CohortManifest, CohortManifestBody, ValueContractError
from .value_observations import OutcomeRegistry, outcome_adapter_hash, outcome_hash, outcome_registry_root

TrustedCohortRoot = NewType("TrustedCohortRoot", str)
TrustedOutcomeRoot = NewType("TrustedOutcomeRoot", str)


class _TrustIssuer:
    pass


_ISSUER = _TrustIssuer()


@dataclass(frozen=True, slots=True)
class ValueTrustContext:
    cohort_manifest: CohortManifest
    cohort_root: TrustedCohortRoot
    provenance_context: TrustedPayloadContext
    quality_context: QualityTrustContext
    outcome_registry: OutcomeRegistry | None
    outcome_root: TrustedOutcomeRoot | None
    _issuer: _TrustIssuer = field(repr=False)

    def issued_by(self, issuer: _TrustIssuer) -> bool:
        return self._issuer is issuer


def cohort_manifest_root(manifest: CohortManifest) -> str:
    body = CohortManifestBody.model_validate(manifest.model_dump(mode="json", exclude={"manifest_root"}))
    value = JsonBoundary.model_validate(body.model_dump(mode="json")).root
    return str(canonical_hash(value))


def _verify_cohort(fixture: ValueFixture, trust: ValueTrustDocument) -> None:
    manifest = fixture.cohort_manifest
    if trust.expected_cohort_root != manifest.manifest_root or cohort_manifest_root(manifest) != manifest.manifest_root:
        raise ValueContractError("COHORT_MANIFEST_INVALID", "cohort root mismatch")
    sample_ids = tuple(item.sample_id for item in manifest.samples)
    if len(set(sample_ids)) != len(sample_ids) or tuple(sorted(sample_ids)) != sample_ids:
        raise ValueContractError("COHORT_MANIFEST_INVALID", "sample inventory must be unique and canonical")


def _verify_outcomes(fixture: ValueFixture, trust: ValueTrustDocument) -> None:
    registry = fixture.outcome_registry
    expected = trust.expected_outcome_root
    if registry is None and expected is None:
        return
    if registry is None or expected is None:
        raise ValueContractError("OUTCOME_ADAPTER_INVALID", "outcome registry and root must be paired")
    if outcome_adapter_hash(registry.adapter) != registry.adapter.body_hash:
        raise ValueContractError("OUTCOME_ADAPTER_INVALID", "adapter body hash mismatch")
    if outcome_registry_root(registry) != registry.registry_root or expected != registry.registry_root:
        raise ValueContractError("OUTCOME_ADAPTER_INVALID", "outcome registry root mismatch")
    sample_ids = tuple(item.sample_id for item in registry.outcomes)
    if len(set(sample_ids)) != len(sample_ids) or tuple(sorted(sample_ids)) != sample_ids:
        raise ValueContractError("OUTCOME_ADAPTER_INVALID", "outcome inventory must be unique and canonical")
    for outcome in registry.outcomes:
        if outcome.adapter_body_hash != registry.adapter.body_hash or outcome_hash(outcome) != outcome.outcome_hash:
            raise ValueContractError("OUTCOME_ADAPTER_INVALID", outcome.sample_id)


def trust_value_fixture(fixture: ValueFixture, trust: ValueTrustDocument) -> ValueTrustContext:
    _verify_cohort(fixture, trust)
    _verify_outcomes(fixture, trust)
    binding = fixture.source_binding
    bundle = binding.provenance_bundle
    if bundle.trusted_payload_manifest.manifest_hash != trust.expected_provenance_manifest_root:
        raise ValueContractError("PRD01_LINEAGE_INVALID", "provenance manifest differs from trusted root")
    if binding.quality_artifact.artifact_hash != trust.expected_quality_artifact_hash:
        raise ValueContractError("PRD02_LINEAGE_INVALID", "quality artifact differs from trusted hash")
    try:
        quality = trust_quality_fixture(fixture.quality_evidence, trust.quality, binding.quality_artifact.generated_at)
        root = bundle.trusted_payload_manifest.manifest_hash
        trusted_bundle = bundle_trust(root, quality)
    except QualityContractError as error:
        raise ValueContractError("PRD02_LINEAGE_INVALID", str(error)) from error
    try:
        provenance = trust_payload_manifest(bundle.trusted_payload_manifest, TrustedManifestRoot(root), trusted_bundle.raw_payload)
    except ProvenanceContractError as error:
        raise ValueContractError("PRD01_LINEAGE_INVALID", str(error)) from error
    outcome_root = None if fixture.outcome_registry is None else TrustedOutcomeRoot(fixture.outcome_registry.registry_root)
    return ValueTrustContext(
        fixture.cohort_manifest, TrustedCohortRoot(fixture.cohort_manifest.manifest_root),
        provenance, quality, fixture.outcome_registry, outcome_root, _ISSUER,
    )


def require_value_context(context: ValueTrustContext | None) -> ValueTrustContext:
    if context is None or not context.issued_by(_ISSUER):
        raise ValueContractError("TRUSTED_VALUE_CONTEXT_REQUIRED", "trusted cohort, lineage, and outcome roots are required")
    if cohort_manifest_root(context.cohort_manifest) != str(context.cohort_root):
        raise ValueContractError("COHORT_MANIFEST_INVALID", "cohort changed after trust issuance")
    return context
