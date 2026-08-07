from typing import Annotated, Literal

from pydantic import Field

from src.v4.models import canonical_hash
from src.v6.models import BoundaryModel, JsonBoundary

from .models import HashText, ProvenanceEnvelope
from .quality_artifact import verify_quality_artifact
from .quality_models import QualityArtifact, QualityContractError
from .source_models import ContractMetadata, SourcePolicyError
from .value_artifact import ValueArtifact, verify_value_artifact
from .value_models import ValueContractError
from .value_trust import ValueTrustContext, require_value_context


class SourceBundleBody(BoundaryModel):
    schema_version: Literal["v7.source-policy.bundle.1"]
    source_bundle_id: Annotated[str, Field(min_length=1)]
    provenance: tuple[ProvenanceEnvelope, ...]
    quality: tuple[QualityArtifact, ...]
    value: ValueArtifact
    capabilities: tuple[Annotated[str, Field(min_length=1)], ...]
    market: Annotated[str, Field(min_length=1)]
    exchange: Annotated[str, Field(min_length=1)]
    symbol_namespace: Annotated[str, Field(min_length=1)]
    contract: ContractMetadata


class SourceBundleManifest(SourceBundleBody):
    source_bundle_hash: HashText


def bundle_hash(body: SourceBundleBody) -> str:
    value = JsonBoundary.model_validate(body.model_dump(mode="json")).root
    return str(canonical_hash(value))


def verify_source_bundle(manifest: SourceBundleManifest, context: ValueTrustContext) -> None:
    trusted = require_value_context(context)
    body = SourceBundleBody.model_validate(manifest.model_dump(mode="json", exclude={"source_bundle_hash"}))
    if manifest.source_bundle_hash != bundle_hash(body):
        raise SourcePolicyError("SOURCE_BUNDLE_HASH_MISMATCH", manifest.source_bundle_id)
    try:
        verified_quality = tuple(verify_quality_artifact(item.model_dump(mode="json"), trusted.quality_context) for item in manifest.quality)
    except QualityContractError as error:
        raise SourcePolicyError("PRD02_LINEAGE_INVALID", str(error)) from error
    try:
        verified_value = verify_value_artifact(manifest.value.model_dump(mode="json"), trusted)
    except ValueContractError as error:
        raise SourcePolicyError("PRD03_LINEAGE_INVALID", str(error)) from error
    quality_provenance = tuple(source.bundle.artifact for item in verified_quality for source in item.build_input.sources)
    quality_hashes = tuple(dict.fromkeys(item.provenance_hash for item in quality_provenance))
    expected_provenance = tuple(next(item for item in quality_provenance if item.provenance_hash == digest) for digest in quality_hashes)
    if tuple(manifest.provenance) != expected_provenance:
        raise SourcePolicyError("PRD01_LINEAGE_INVALID", "quality provenance body is absent")
    binding = verified_value.source_binding
    if binding.provenance_bundle.artifact not in manifest.provenance or binding.quality_artifact not in verified_quality:
        raise SourcePolicyError("PRD03_LINEAGE_INVALID", "value source binding differs from manifest bodies")
    if verified_value.source_bundle_id != manifest.source_bundle_id:
        raise SourcePolicyError("PRD03_LINEAGE_INVALID", "source bundle identity differs")
    source_id = binding.provenance_bundle.artifact.source_identity.source_id
    metadata = tuple(item for item in trusted.quality_context.registry.entries if item.source_id == source_id)
    if len(metadata) != 1:
        raise SourcePolicyError("SOURCE_CONTEXT_MISMATCH", "source metadata identity")
    trusted_metadata = metadata[0]
    coverage = trusted_metadata.coverage
    if (manifest.capabilities, manifest.market, manifest.exchange, manifest.symbol_namespace) != (trusted_metadata.capabilities, coverage.market, coverage.exchange, coverage.symbol_namespace):
        raise SourcePolicyError("SOURCE_CONTEXT_MISMATCH", "capability or coverage differs from trusted registry")
