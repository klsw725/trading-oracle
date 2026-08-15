from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StrictInt

from src.v11.models import Account
from src.v4.models import JsonValue
from src.v13.fallback import RoutedBatch
from src.v13.models import BoundCandidateEvidence, RouterSelection, StrictModel
from src.v13.prd02_models import BatchRequest, BatchScoringArtifact, ContextSnapshot, RecordedResponse
from src.v13.prd03_models import SwitchFixture, SwitchResult
from src.v13.replay import ReplayRecord, ReplayResult


class Prd04InputDescriptor(StrictModel):
    schema_version: Literal["v13.prd04.input.1"]
    v10_context_path: str
    v11_account_path: str
    v11_execution_path: str
    v12_cohort_path: str
    switch_path: str


class Prd04SourceFixture(StrictModel):
    schema_version: Literal["v13.prd04.source.1"]
    v10_context_fixture: JsonValue
    v11_account_fixture: JsonValue
    v11_execution_fixture: JsonValue
    v12_cohort_fixture: JsonValue
    switch_fixture: SwitchFixture
    candidate_fixture: Annotated[tuple[BoundCandidateEvidence, ...], Field(strict=False)]
    canonical_symbols: Annotated[tuple[str, ...], Field(strict=False)]
    recorded_response: RecordedResponse


class UpstreamProof(StrictModel):
    v10_context_bundle_hash: str
    v11_account_bundle_hash: str
    v11_execution_bundle_hash: str
    v12_bundle_hash: str
    v12_run_hash: str
    verified_account_hash: str
    strategy_count: Annotated[StrictInt, Field(ge=0)]
    long_trade_count: Annotated[StrictInt, Field(ge=0)]
    short_trade_count: Annotated[StrictInt, Field(ge=0)]
    namespace_count: Annotated[StrictInt, Field(ge=0)]
    happy_count: Annotated[StrictInt, Field(ge=0)]
    no_signal_count: Annotated[StrictInt, Field(ge=0)]
    missing_count: Annotated[StrictInt, Field(ge=0)]


class CandidateInventory(StrictModel):
    candidate_ids: Annotated[tuple[str, ...], Field(strict=False)]
    candidate_inventory_hash: str
    canonical_symbols: Annotated[tuple[str, ...], Field(strict=False)]
    symbol_inventory_hash: str


class VersionPins(StrictModel):
    policy_version: Literal["v13.router_policy.1"]
    policy_hash: str
    model_id: Literal["gpt-5.1-codex"]
    prompt_version: Literal["v13.prompt.1"]
    schema_version: Literal["v13.codex_response.1"]
    detector_version: Literal["v13.detector.1"]


class NormativeProbe(StrictModel):
    probe_id: str
    state: Literal["killed"]


class CoverageEntry(StrictModel):
    requirement_id: str
    prd: Literal[1, 2, 3, 4]
    fixture: str
    probes: Annotated[tuple[str, ...], Field(strict=False)]


class CoverageArtifact(StrictModel):
    entries: Annotated[tuple[CoverageEntry, ...], Field(strict=False)]
    requirement_count: Annotated[StrictInt, Field(gt=0)]
    prd_count: Literal[4]
    fixture_count: Annotated[StrictInt, Field(gt=0)]
    probe_count: Literal[13]
    coverage_hash: str


class AdapterOutput(StrictModel):
    candidates: Annotated[tuple[BoundCandidateEvidence, ...], Field(strict=False)]
    router_candidates: Annotated[tuple[BoundCandidateEvidence, ...], Field(strict=False)]
    canonical_symbols: Annotated[tuple[str, ...], Field(strict=False)]
    account: Account
    context: ContextSnapshot
    upstream: UpstreamProof


class Prd04Bundle(StrictModel):
    schema_version: Literal["v13.router.bundle.1"]
    fixture_hash: str
    source_fixture: Prd04SourceFixture
    upstream: UpstreamProof
    versions: VersionPins
    inventory: CandidateInventory
    request: BatchRequest
    router_selection: RouterSelection
    recorded_scoring: BatchScoringArtifact
    switch: SwitchResult
    circuit: RoutedBatch
    replay_record: ReplayRecord
    replay_result: ReplayResult
    probes: Annotated[tuple[NormativeProbe, ...], Field(strict=False)]
    coverage: CoverageArtifact
    run_hash: str
    bundle_hash: str
