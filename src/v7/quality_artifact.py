from pathlib import Path

from pydantic import ValidationError

from src.v4.models import ArtifactWriteStatus, JsonValue, canonical_hash, write_immutable_json
from src.v6.models import JsonBoundary

from .quality_derivation import derive_quality_sources
from .quality_evaluator import evaluate_quality
from .quality_models import (
    FallbackLink,
    QualityArtifact,
    QualityBuildInput,
    QualityContractError,
    QualityFixture,
)
from .quality_registry import QualityTrustContext, trust_quality_fixture
from .quality_registry_models import QualityTrustDocument
from .sensitive_data import contains_sensitive

_REQUIRED_ARTIFACT_FIELDS = (
    "build_input",
    "source_registry_root",
    "source_results",
    "clusters",
    "claims",
    "freshness_label",
    "quality_label",
    "quality_score",
    "score_breakdown",
    "summary",
    "fallback",
    "result_label",
    "artifact_hash",
)


def ensure_quality_paths(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        raise QualityContractError("OUTPUT_PATH_UNSAFE", "output must not replace input")


def compile_quality(value: QualityBuildInput, context: QualityTrustContext) -> QualityArtifact:
    canonical_input = value.model_copy(update={"sources": tuple(sorted(value.sources, key=lambda item: item.record_id))})
    if canonical_input.fallback_for is not None and not canonical_input.fallback_for.reason.strip():
        raise QualityContractError("FALLBACK_CHAIN_REASON_REQUIRED", "fallback reason is blank")
    sources = derive_quality_sources(canonical_input, context)
    evaluated = evaluate_quality(canonical_input, sources)
    body: JsonValue = {
        "schema_version": "v7.quality_freshness_dedup.artifact.2",
        "contract_id": "quality_freshness_dedup_prd02",
        "generated_at": canonical_input.generated_at.isoformat(),
        "source_registry_root": str(context.registry_root),
        "build_input": canonical_input.model_dump(mode="json"),
        "source_results": [item.model_dump(mode="json") for item in evaluated.source_results],
        "clusters": [item.model_dump(mode="json") for item in evaluated.clusters],
        "claims": [item.model_dump(mode="json") for item in evaluated.claims],
        "freshness_label": evaluated.freshness_label,
        "quality_label": evaluated.quality_label,
        "quality_score": evaluated.quality_score,
        "score_breakdown": evaluated.score_breakdown.model_dump(mode="json"),
        "summary": evaluated.summary.model_dump(mode="json"),
        "fallback": canonical_input.fallback_for.model_dump(mode="json") if canonical_input.fallback_for is not None else None,
        "result_label": evaluated.result_label,
        "runtime_adoption": "absent",
    }
    body["artifact_hash"] = str(canonical_hash(body))
    try:
        return QualityArtifact.model_validate(body)
    except ValidationError as error:
        raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", str(error)) from error


def _artifact_body(artifact: QualityArtifact) -> JsonValue:
    return JsonBoundary.model_validate(artifact.model_dump(mode="json", exclude={"artifact_hash"})).root


def _parse_artifact(value: JsonValue) -> QualityArtifact:
    match value:  # noqa: MATCH_OK - JSON boundary rejects non-object variants
        case dict() as record:
            missing = tuple(field for field in _REQUIRED_ARTIFACT_FIELDS if field not in record)
            if missing:
                raise QualityContractError("REQUIRED_FIELD_MISSING", ",".join(missing))
        case _:
            raise QualityContractError("MALFORMED_QUALITY_PAYLOAD", "artifact must be an object")
    try:
        return QualityArtifact.model_validate(value)
    except ValidationError as error:
        code = "REQUIRED_FIELD_MISSING" if any(item["type"] == "missing" for item in error.errors()) else "MALFORMED_QUALITY_PAYLOAD"
        raise QualityContractError(code, str(error)) from error


def verify_quality_artifact(value: JsonValue, context: QualityTrustContext | None = None) -> QualityArtifact:
    if contains_sensitive(value):
        raise QualityContractError("SECRET_LEAKAGE_DETECTED", "artifact contains forbidden material")
    if context is None:
        raise QualityContractError("TRUSTED_QUALITY_CONTEXT_REQUIRED", "quality verification requires trusted registry and bundle roots")
    artifact = _parse_artifact(value)
    if artifact.source_registry_root != str(context.registry_root):
        raise QualityContractError("SOURCE_REGISTRY_INVALID", "artifact registry root differs from trusted root")
    expected = compile_quality(artifact.build_input, context)
    if tuple(item.dedup_key for item in artifact.source_results) != tuple(item.dedup_key for item in expected.source_results) or tuple(item.dedup_key for item in artifact.clusters) != tuple(item.dedup_key for item in expected.clusters):
        raise QualityContractError("DEDUP_KEY_HASH_MISMATCH", "dedup key differs from embedded evidence")
    if tuple(item.freshness for item in artifact.source_results) != tuple(item.freshness for item in expected.source_results) or artifact.freshness_label != expected.freshness_label:
        raise QualityContractError("STALE_MISLABELED_FRESH", "freshness differs from PRD02 SLA result")
    if artifact.summary.raw_result_count != expected.summary.raw_result_count and artifact.quality_score != expected.quality_score:
        raise QualityContractError("COUNT_USED_AS_QUALITY", "raw count changed quality score")
    if artifact.summary != expected.summary:
        raise QualityContractError("MISLEADING_SUMMARY", "summary differs from embedded evidence")
    hidden_contradiction = any(item.opposing_cluster_ids for item in expected.claims) and (artifact.quality_label != "blocked" or artifact.result_label != "blocked")
    if hidden_contradiction:
        raise QualityContractError("CONTRADICTION_UNRESOLVED", "artifact hides opposing clusters")
    if artifact.score_breakdown != expected.score_breakdown or artifact.quality_score != expected.quality_score:
        raise QualityContractError("SCORE_COMPONENT_MISMATCH", "score differs from embedded evidence")
    if artifact.quality_label != expected.quality_label or artifact.result_label != expected.result_label:
        raise QualityContractError("QUALITY_LABEL_MISMATCH", "label differs from score and evidence gates")
    if (artifact.source_results, artifact.clusters, artifact.claims, artifact.fallback) != (expected.source_results, expected.clusters, expected.claims, expected.fallback):
        raise QualityContractError("ARTIFACT_HASH_MISMATCH", "derived quality body differs from recomputation")
    if str(canonical_hash(_artifact_body(artifact))) != artifact.artifact_hash:
        raise QualityContractError("ARTIFACT_HASH_MISMATCH", "artifact_hash")
    return artifact


def build_quality_artifacts(fixture: QualityFixture, trust: QualityTrustDocument) -> tuple[QualityArtifact, QualityArtifact]:
    primary_context = trust_quality_fixture(fixture.primary_evidence, trust.primary, fixture.primary_input.generated_at)
    primary = compile_quality(fixture.primary_input, primary_context)
    if fixture.fallback_input.fallback_for is not None:
        raise QualityContractError("FALLBACK_PROVENANCE_MISSING", "fixture fallback input must be linked by compiler")
    fallback_link = FallbackLink(
        parent_artifact_hash=primary.artifact_hash,
        reason=fixture.fallback_reason,
        contradiction_link=primary.artifact_hash if any(item.opposing_cluster_ids for item in primary.claims) else None,
    )
    fallback_context = trust_quality_fixture(fixture.fallback_evidence, trust.fallback, fixture.fallback_input.generated_at)
    fallback = compile_quality(fixture.fallback_input.model_copy(update={"fallback_for": fallback_link}), fallback_context)
    return primary, fallback


def write_quality_artifacts(path: Path, artifacts: tuple[QualityArtifact, QualityArtifact], fixture: QualityFixture, trust: QualityTrustDocument) -> ArtifactWriteStatus:
    contexts = (
        trust_quality_fixture(fixture.primary_evidence, trust.primary, fixture.primary_input.generated_at),
        trust_quality_fixture(fixture.fallback_evidence, trust.fallback, fixture.fallback_input.generated_at),
    )
    verified = tuple(verify_quality_artifact(item.model_dump(mode="json"), context) for item, context in zip(artifacts, contexts, strict=True))
    value = JsonBoundary.model_validate([item.model_dump(mode="json") for item in verified]).root
    return write_immutable_json(path, value)
