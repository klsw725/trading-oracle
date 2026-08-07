from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from src.v4.models import ArtifactWriteStatus, JsonValue, canonical_hash, write_immutable_json
from src.v6.models import BoundaryModel, JsonBoundary

from .models import HashText
from .sensitive_data import contains_sensitive
from .value_derivation import ValueMetrics
from .value_evaluator import ValueEvaluation, evaluate_value
from .value_input import ValueFixture
from .value_models import CohortManifest, SourceBinding, ValueCode, ValueContractError, ValueThresholds, canonical_thresholds
from .value_observations import OutcomeAdapterIdentity, PairedObservation
from .value_trust import ValueTrustContext, require_value_context

_REPEAT_COUNT = 3
_REQUIRED_FIELDS = (
    "source_binding", "cohort_manifest", "observations", "thresholds", "metrics",
    "terminal_code", "repeat_run_hashes", "production_isolation", "artifact_hash",
)


class RunHashInput(BoundaryModel):
    cohort_manifest_root: HashText
    observations_hash: HashText
    metrics_hash: HashText
    decision_hash: HashText
    policy_hash: HashText
    outcome_adapter_root: HashText
    provenance_manifest_root: HashText
    quality_registry_root: HashText


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    binding: SourceBinding
    manifest: CohortManifest
    observations: tuple[PairedObservation, ...]
    result: ValueEvaluation
    context: ValueTrustContext


class ValueArtifactBody(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.artifact.2"]
    report_id: str
    source_bundle_id: str
    generated_at: str
    source_binding: SourceBinding
    cohort_manifest: CohortManifest
    outcome_adapter: OutcomeAdapterIdentity
    outcome_adapter_root: HashText
    thresholds: ValueThresholds
    observations: tuple[PairedObservation, ...]
    metrics: ValueMetrics
    terminal_code: ValueCode
    reasons: tuple[str, ...]
    policy_no_op: bool
    promotion_eligible: bool
    repeat_run_hashes: tuple[HashText, ...]
    production_isolation: Literal["offline_read_only_no_production_mutation"]


class ValueArtifact(ValueArtifactBody):
    artifact_hash: HashText


def _json(value: BoundaryModel) -> JsonValue:
    return JsonBoundary.model_validate(value.model_dump(mode="json")).root


def _decision_hash(result: ValueEvaluation) -> str:
    return str(canonical_hash({"code": result.code, "reasons": list(result.reasons), "policy_no_op": result.policy_no_op, "promotion_eligible": result.promotion_eligible}))


def _run_hash(run: EvaluationRun) -> str:
    observations_value = JsonBoundary.model_validate([item.model_dump(mode="json") for item in run.observations]).root
    policy = canonical_thresholds()
    seed = RunHashInput(
        cohort_manifest_root=run.manifest.manifest_root,
        observations_hash=str(canonical_hash(observations_value)),
        metrics_hash=str(canonical_hash(_json(run.result.metrics))),
        decision_hash=_decision_hash(run.result), policy_hash=str(canonical_hash(_json(policy))),
        outcome_adapter_root=str(run.context.outcome_root),
        provenance_manifest_root=run.binding.provenance_bundle.trusted_payload_manifest.manifest_hash,
        quality_registry_root=str(run.context.quality_context.registry_root),
    )
    return str(canonical_hash(_json(seed)))


def _body_json(body: ValueArtifactBody) -> JsonValue:
    return _json(body)


def compile_value_artifact(fixture: ValueFixture, context: ValueTrustContext | None = None) -> ValueArtifact:
    trusted = require_value_context(context)
    if trusted.outcome_registry is None or trusted.outcome_root is None:
        raise ValueContractError("OUTCOME_ADAPTER_INVALID", "build requires a trusted outcome adapter root")
    result = evaluate_value(fixture.source_binding, fixture.observations, trusted)
    run_hash = _run_hash(EvaluationRun(fixture.source_binding, fixture.cohort_manifest, fixture.observations, result, trusted))
    body = ValueArtifactBody(
        schema_version="v7.incremental_value_evaluation.artifact.2", report_id=fixture.report_id,
        source_bundle_id=fixture.source_bundle_id, generated_at=fixture.generated_at.isoformat(),
        source_binding=fixture.source_binding, cohort_manifest=fixture.cohort_manifest,
        outcome_adapter=trusted.outcome_registry.adapter, outcome_adapter_root=str(trusted.outcome_root),
        thresholds=canonical_thresholds(), observations=fixture.observations, metrics=result.metrics,
        terminal_code=result.code, reasons=result.reasons, policy_no_op=result.policy_no_op,
        promotion_eligible=result.promotion_eligible, repeat_run_hashes=(run_hash,) * _REPEAT_COUNT,
        production_isolation="offline_read_only_no_production_mutation",
    )
    return ValueArtifact.model_validate({**body.model_dump(mode="json"), "artifact_hash": str(canonical_hash(_body_json(body)))})


def verify_value_artifact(value: JsonValue, context: ValueTrustContext | None = None) -> ValueArtifact:
    if contains_sensitive(value):
        raise ValueContractError("SECRET_LEAKAGE_DETECTED", "artifact contains forbidden material")
    trusted = require_value_context(context)
    match value:  # noqa: MATCH_OK - JSON boundary rejects non-object variants
        case dict() as record:
            missing = tuple(field for field in _REQUIRED_FIELDS if field not in record)
            if missing:
                raise ValueContractError("REQUIRED_FIELD_MISSING", ",".join(missing))
        case _:
            raise ValueContractError("MALFORMED_EVALUATION_INPUT", "artifact must be an object")
    try:
        artifact = ValueArtifact.model_validate(value)
    except ValidationError as error:
        code = "REQUIRED_FIELD_MISSING" if any(item["type"] == "missing" for item in error.errors()) else "MALFORMED_EVALUATION_INPUT"
        raise ValueContractError(code, str(error)) from error
    if artifact.cohort_manifest != trusted.cohort_manifest or artifact.cohort_manifest.manifest_root != str(trusted.cohort_root):
        raise ValueContractError("COHORT_MANIFEST_INVALID", "artifact manifest differs from trusted manifest")
    if trusted.outcome_registry is None or artifact.outcome_adapter != trusted.outcome_registry.adapter or artifact.outcome_adapter_root != str(trusted.outcome_root):
        raise ValueContractError("OUTCOME_ADAPTER_INVALID", "artifact outcome root differs")
    if artifact.thresholds != canonical_thresholds():
        raise ValueContractError("POLICY_MISMATCH", "artifact thresholds differ from canonical policy")
    expected = evaluate_value(artifact.source_binding, artifact.observations, trusted)
    declared = (artifact.metrics, artifact.terminal_code, artifact.reasons, artifact.policy_no_op, artifact.promotion_eligible)
    derived = (expected.metrics, expected.code, expected.reasons, expected.policy_no_op, expected.promotion_eligible)
    if declared != derived:
        raise ValueContractError("AGGREGATE_METRIC_MISMATCH", "declared result differs from trusted observations")
    expected_run = _run_hash(EvaluationRun(artifact.source_binding, artifact.cohort_manifest, artifact.observations, expected, trusted))
    if artifact.repeat_run_hashes != (expected_run,) * _REPEAT_COUNT:
        raise ValueContractError("REPEAT_HASH_MISMATCH", "repeat hashes differ from current evaluation")
    body = ValueArtifactBody.model_validate(artifact.model_dump(mode="json", exclude={"artifact_hash"}))
    if artifact.artifact_hash != str(canonical_hash(_body_json(body))):
        raise ValueContractError("ARTIFACT_HASH_MISMATCH", "artifact_hash")
    return artifact


def ensure_value_paths(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueContractError("OUTPUT_PATH_UNSAFE", "output must not replace input")


def write_value_artifact(path: Path, artifact: ValueArtifact, context: ValueTrustContext | None = None) -> ArtifactWriteStatus:
    verified = verify_value_artifact(artifact.model_dump(mode="json"), context)
    return write_immutable_json(path, JsonBoundary.model_validate(verified.model_dump(mode="json")).root)
