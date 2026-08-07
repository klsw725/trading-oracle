from dataclasses import dataclass
from pathlib import Path

from src.v4.models import ArtifactWriteStatus, JsonValue, write_immutable_json
from src.v6.models import JsonBoundary

from .models import BuildContext, PersistedProvenanceBundle, ProvenanceContractError, ProvenanceEnvelope, ProvenanceFixture, TrustedManifestRoot
from .payload_manifest import TrustedPayloadContext, build_payload_context, trust_payload_manifest
from .provenance import PRD02_FRESHNESS_SLA_HOURS, compile_provenance, verify_artifact


def ensure_distinct_paths(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ProvenanceContractError("OUTPUT_PATH_UNSAFE", "output must not replace input")


@dataclass(frozen=True, slots=True)
class CompiledProvenance:
    artifact: ProvenanceEnvelope
    trusted_context: TrustedPayloadContext


def build_from_fixture(fixture: ProvenanceFixture) -> CompiledProvenance:
    if fixture.freshness_sla_hours != PRD02_FRESHNESS_SLA_HOURS:
        raise ProvenanceContractError("MALFORMED_PAYLOAD", "freshness SLA differs from PRD02")
    context = BuildContext(
        raw_payload=fixture.raw_payload.root,
        evaluated_at=fixture.evaluated_at,
        freshness_sla_hours=fixture.freshness_sla_hours,
    )
    artifact = compile_provenance(
        fixture.happy_trace_fixture.root,
        context,
    )
    return CompiledProvenance(artifact, build_payload_context(artifact, context))


def persisted_bundle(compiled: CompiledProvenance) -> PersistedProvenanceBundle:
    verified = verify_artifact(
        compiled.artifact.model_dump(mode="json"),
        compiled.trusted_context,
    )
    return PersistedProvenanceBundle(
        schema_version="v7.source_adapter_provenance.verification-bundle.1",
        artifact=verified,
        trusted_payload_manifest=compiled.trusted_context.manifest,
    )


def verify_persisted_bundle(
    bundle: PersistedProvenanceBundle,
    expected_root: TrustedManifestRoot,
    trusted_raw_payload: JsonValue,
) -> ProvenanceEnvelope:
    context = trust_payload_manifest(
        bundle.trusted_payload_manifest,
        expected_root,
        trusted_raw_payload,
    )
    return verify_artifact(bundle.artifact.model_dump(mode="json"), context)


def write_artifact(path: Path, compiled: CompiledProvenance) -> ArtifactWriteStatus:
    bundle = persisted_bundle(compiled)
    value = JsonBoundary.model_validate(bundle.model_dump(mode="json")).root
    return write_immutable_json(path, value)
