from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self, override

from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError, model_validator

from src.v4.models import JsonValue, canonical_hash

from .candidate_artifact import CandidateArtifact
from .models import BoundaryModel, ContractInvariantError, ExistingPerspective, JsonBoundary, Verdict
from .offline_models import BaselineKind, ContentHash, Decimal6, ExpectedMutation, HandExpected, MutationName, OfflineCode, Probability6


NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class EvaluationConfigBody(BoundaryModel):
    success_threshold: Probability6
    holdout_lift_lower_minimum: Decimal6
    target_lift_lower_minimum: Decimal6
    harm_rate_maximum: Probability6
    non_target_harm_rate_maximum: Probability6
    recovery_rate_minimum: Probability6
    bootstrap_iterations: Annotated[int, Field(ge=100)]
    bootstrap_seed: str
    expected_repeat_runs: NonNegativeInt
    overlap_ceiling: Probability6


class HashedEvaluationConfig(BoundaryModel):
    body: EvaluationConfigBody
    config_hash: ContentHash


class BaselinePrediction(BoundaryModel):
    kind: BaselineKind
    confidence: Probability6
    verdict_direction: Literal[-1, 0, 1]


class PerspectivePrediction(BoundaryModel):
    perspective: ExistingPerspective
    verdict_direction: Literal[-1, 0, 1]


class CandidateOutputRecord(BoundaryModel):
    verdict: Verdict
    confidence: Probability6
    verdict_direction: Literal[-1, 0, 1]
    missing_required_input: bool
    timed_out: bool
    wall_ms: NonNegativeInt
    llm_calls: NonNegativeInt
    prompt_tokens: NonNegativeInt
    extra_fetches: NonNegativeInt


class BaselineEdge(BoundaryModel):
    kind: BaselineKind
    edge: Decimal6


class PerspectiveEdge(BoundaryModel):
    perspective: ExistingPerspective
    edge: Decimal6


class OutcomeRecord(BoundaryModel):
    adapter_available: bool
    baseline_edges: tuple[BaselineEdge, ...]
    perspective_edges: tuple[PerspectiveEdge, ...]
    candidate_edge: Decimal6 | None


class AblationRecord(BoundaryModel):
    remove_novel_observations_edge: Decimal6 | None
    existing_signal_only_edge: Decimal6 | None
    shuffled_candidate_edge: Decimal6 | None


class SampleBatchBody(BoundaryModel):
    batch_id: str
    sample_id_prefix: str
    sample_count: PositiveInt
    ticker_prefix: str
    market: Literal["KR", "US"]
    split: Literal["train_window", "validation_window", "holdout_window"]
    emitted_at: AwareDatetime
    decision_input_cutoff: AwareDatetime
    feature_generated_at: AwareDatetime
    outcome_cutoff: AwareDatetime
    source_hash_seed: ContentHash
    feature_fields: tuple[str, ...]
    target_error: bool
    baselines: tuple[BaselinePrediction, ...]
    perspectives: tuple[PerspectivePrediction, ...]
    candidate: CandidateOutputRecord
    outcome: OutcomeRecord
    ablation: AblationRecord


class SampleBatchRecord(BoundaryModel):
    body: SampleBatchBody
    record_hash: ContentHash


class FrozenManifestBody(BoundaryModel):
    dataset_manifest_id: str
    feature_cutoff: AwareDatetime
    outcome_horizon_sessions: PositiveInt
    threshold_version: str
    embargo_sessions: NonNegativeInt
    record_hashes: tuple[ContentHash, ...]


class FrozenManifest(BoundaryModel):
    body: FrozenManifestBody
    manifest_hash: ContentHash


class RepeatRun(BoundaryModel):
    run_index: PositiveInt
    input_hash: ContentHash
    config_hash: ContentHash
    terminal_code: OfflineCode


class FrozenEvaluationInput(BoundaryModel):
    schema_version: Literal["v6.offline-evaluation-input.2"]
    candidate_artifact_hash: ContentHash
    config: HashedEvaluationConfig
    manifest: FrozenManifest
    records: tuple[SampleBatchRecord, ...]
    input_hash: ContentHash
    reported_terminal_code: OfflineCode
    repeated_runs: tuple[RepeatRun, ...]


class OfflineFixture(BoundaryModel):
    schema_version: Literal["v6.offline-evaluation-fixture.2"]
    candidate_artifact: CandidateArtifact
    hand_input: FrozenEvaluationInput
    hand_expected: HandExpected
    threshold_input: FrozenEvaluationInput
    expected_mutations: tuple[ExpectedMutation, ...]

    @model_validator(mode="after")
    def exact_mutation_corpus(self) -> Self:
        names = tuple(item.name for item in self.expected_mutations)
        if len(names) != len(MutationName) or len(set(names)) != len(names) or set(names) != set(MutationName):
            raise ContractInvariantError("expected_mutations must exactly cover MutationName")
        return self


@dataclass(frozen=True, slots=True)
class OfflineFixtureError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return f"offline evaluation fixture: {self.detail}"


def load_offline_fixture(path: Path) -> OfflineFixture:
    try:
        return TypeAdapter(OfflineFixture).validate_json(path.read_bytes())
    except ValidationError as error:
        raise OfflineFixtureError(str(error)) from error


def boundary_json(value: BoundaryModel) -> JsonValue:
    return JsonBoundary.model_validate(value.model_dump(mode="json")).root


def expected_record_hash(record: SampleBatchRecord) -> str:
    return canonical_hash(boundary_json(record.body))


def expected_config_hash(config: HashedEvaluationConfig) -> str:
    return canonical_hash(boundary_json(config.body))


def expected_manifest_hash(manifest: FrozenManifest) -> str:
    return canonical_hash(boundary_json(manifest.body))


def expected_input_hash(value: FrozenEvaluationInput) -> str:
    identity: JsonValue = {
        "schema_version": value.schema_version,
        "candidate_artifact_hash": value.candidate_artifact_hash,
        "config_hash": value.config.config_hash,
        "manifest_hash": value.manifest.manifest_hash,
        "record_hashes": [record.record_hash for record in value.records],
    }
    return canonical_hash(identity)


def sample_ids(record: SampleBatchRecord) -> tuple[str, ...]:
    return tuple(f"{record.body.sample_id_prefix}_{index:03d}" for index in range(1, record.body.sample_count + 1))
