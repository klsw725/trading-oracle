from enum import StrEnum, unique
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from src.v4.models import JsonValue

from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, HypothesisId
from .offline_artifact import OfflineEvaluationArtifact
from .offline_models import ContentHash, Probability6
from .paper_assignment_types import AssignmentInput, AssignmentResult
from .paper_observations import HorizonObservation, ObservationBatch, OutcomeAdapter, PaperMetrics


@unique
class PaperStopCode(StrEnum):
    READY = "STOP_READY_FOR_LIFECYCLE_REVIEW"
    HARMFUL = "STOP_REJECT_HARMFUL_SHADOW"
    INSUFFICIENT = "STOP_INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    PENDING_ADAPTER = "STOP_INCONCLUSIVE_PENDING_ADAPTER"
    SCHEMA_DRIFT = "STOP_SCHEMA_DRIFT"
    COVERAGE_DRIFT = "STOP_COVERAGE_DRIFT"
    VERDICT_DRIFT = "STOP_VERDICT_DRIFT"
    LATENCY_DRIFT = "STOP_LATENCY_DRIFT"
    CONTAMINATION = "STOP_CONTAMINATION_DETECTED"
    CANCELLED = "STOP_CANCELLED_BY_OPERATOR"


@unique
class LedgerEventType(StrEnum):
    STARTED = "paper_run_started"
    ASSIGNED = "sample_assigned"
    SHADOW = "shadow_verdict_recorded"
    OUTCOME = "outcome_observed"
    DRIFT = "drift_signal_recorded"
    CANCELLED = "paper_run_cancelled"
    RESUMED = "paper_run_resumed"
    STOPPED = "paper_run_stopped"


class AssignmentPolicyBody(BoundaryModel):
    policy_id: str
    policy_salt: str
    sample_rate_bps: Annotated[int, Field(strict=True, ge=1, le=10_000)]
    eligible_markets: tuple[Literal["KR", "US", "ALL"], ...]
    eligible_actions: tuple[Literal["BUY", "SELL", "HOLD", "N/A"], ...]
    horizons: tuple[Annotated[int, Field(strict=True, ge=1)], ...]
    min_duration_market_sessions: Annotated[int, Field(strict=True, ge=1)]
    min_eligible_samples: Annotated[int, Field(strict=True, ge=1)]
    min_target_disagreement_samples: Annotated[int, Field(strict=True, ge=1)]
    min_mature_coverage: Probability6
    overall_na_ceiling: Probability6
    target_na_ceiling: Probability6
    schema_drift_ceiling: Probability6
    verdict_psi_ceiling: Probability6
    adapter_staleness_ceiling: Probability6
    max_harm_rate: Probability6

    @model_validator(mode="after")
    def required_horizons(self) -> Self:
        if self.horizons != (5, 20):
            raise ContractInvariantError("paper policy requires separate 5 and 20 session horizons")
        return self


class AssignmentPolicy(AssignmentPolicyBody):
    policy_hash: ContentHash


class ProductionSnapshot(BoundaryModel):
    perspectives: tuple[str, ...]
    vote_summary: JsonValue
    consensus_verdict: str
    portfolio_sizing: JsonValue
    user_output: JsonValue


class ShadowVerdict(BoundaryModel):
    sample_id: str
    perspective: str
    verdict: Literal["BUY", "SELL", "HOLD", "N/A"]
    confidence: Annotated[str, Field(pattern=r"^(?:0\.[0-9]{6}|1\.000000)$")]
    reason: str
    action: Literal["buy", "sell", "hold", "none"]
    vote_effect: Literal["none"]
    shadow_visible_to_user: Literal[False]
    cost_units: Annotated[int, Field(strict=True, ge=0)]
    latency_ms: Annotated[int, Field(strict=True, ge=0)]
    decision_cutoff: str

    @model_validator(mode="after")
    def na_contract(self) -> Self:
        if self.verdict == "N/A" and (self.confidence != "0.000000" or self.action != "none"):
            raise ContractInvariantError("N/A shadow requires zero confidence and none action")
        return self


class IsolationEvidence(BoundaryModel):
    production_before: ProductionSnapshot
    production_after: ProductionSnapshot
    scorer_read_shadow: bool
    deliberator_read_shadow: bool
    portfolio_read_shadow: bool
    tuning_read_shadow: bool


class PaperCohortInput(BoundaryModel):
    schema_version: Literal["v6.paper-cohort-input.1"]
    generated_at: str
    run_id: str
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    offline_artifact_hash: ContentHash
    offline_artifact: OfflineEvaluationArtifact
    policy: AssignmentPolicy
    assignment_input: AssignmentInput
    assignment: AssignmentResult
    isolation: IsolationEvidence
    shadow: ShadowVerdict
    observation_batches: tuple[ObservationBatch, ...]
    horizon_observations: tuple[HorizonObservation, ...]
    outcome_adapter: OutcomeAdapter | None
    reported_stop_code: PaperStopCode

    @model_validator(mode="after")
    def evidence_inventory(self) -> Self:
        batch_ids = tuple(batch.batch_id for batch in self.observation_batches)
        batch_hashes = tuple(batch.batch_hash for batch in self.observation_batches)
        sample_ids = tuple(record.sample_id for batch in self.observation_batches for record in batch.records)
        horizons = tuple(item.horizon_market_sessions for item in self.horizon_observations)
        observation_hashes = tuple(item.observation_hash for item in self.horizon_observations)
        if not batch_ids or len(set(batch_ids)) != len(batch_ids) or len(set(batch_hashes)) != len(batch_hashes):
            raise ContractInvariantError("observation batch inventory mismatch")
        if horizons != (5, 20) or len(set(observation_hashes)) != len(observation_hashes):
            raise ContractInvariantError("paper evidence requires unique 5 and 20 session observations")
        if len(set(sample_ids)) != len(sample_ids):
            raise ContractInvariantError("paper sample IDs must be globally unique")
        if any({record.sample_id for record in item.records} != set(sample_ids) for item in self.horizon_observations):
            raise ContractInvariantError("horizon outcome IDs must exactly match paper sample IDs")
        representative = tuple(record for batch in self.observation_batches for record in batch.records if record.sample_id == self.shadow.sample_id)
        matching_shadow = len(representative) == 1 and representative[0].assignment_input == self.assignment_input and representative[0].assignment == self.assignment and (representative[0].perspective, representative[0].shadow_verdict, representative[0].shadow_confidence, representative[0].shadow_reason, representative[0].shadow_action, representative[0].vote_effect, representative[0].shadow_visible_to_user, representative[0].cost_units, representative[0].latency_ms) == (self.shadow.perspective, self.shadow.verdict, self.shadow.confidence, self.shadow.reason, self.shadow.action, self.shadow.vote_effect, self.shadow.shadow_visible_to_user, self.shadow.cost_units, self.shadow.latency_ms)
        if not matching_shadow:
            raise ContractInvariantError("representative shadow does not match its sample observation")
        return self


class LedgerEventBody(BoundaryModel):
    schema_version: Literal["v6.paper-cohort-ledger.1"]
    run_id: str
    event_index: Annotated[int, Field(strict=True, ge=0)]
    event_type: LedgerEventType
    occurred_at: str
    entity_ref_id: str
    prev_event_hash: ContentHash
    payload_hash: ContentHash
    payload: JsonValue


class LedgerEvent(LedgerEventBody):
    event_id: str
    event_hash: ContentHash


class ResumeCheckpoint(BoundaryModel):
    run_id: str
    policy_id: str
    candidate_version: CandidateVersion
    policy_hash: ContentHash
    last_event_index: Annotated[int, Field(strict=True, ge=0)]
    last_event_hash: ContentHash
    recorded_sample_ids: tuple[str, ...]


class ResumeRequest(BoundaryModel):
    run_id: str
    policy_id: str
    candidate_version: CandidateVersion
    prev_event_hash: ContentHash
    next_event_index: Annotated[int, Field(strict=True, ge=1)]
    write_sample_id: str


class ResumeDecision(BoundaryModel):
    resume_allowed: bool
    stop_code: PaperStopCode | None
    reason: Literal["resume_valid", "resume_identity_mismatch", "duplicate_shadow_resume", "invalid_cancelled_history"]


class PaperFixture(BoundaryModel):
    schema_version: Literal["v6.paper-cohort-fixture.1"]
    paper_input: PaperCohortInput
    ledger: tuple[LedgerEvent, ...]
    assignment_vectors: tuple[AssignmentInput, ...]
    assignment_golden_buckets: tuple[int, ...]
    cancelled_ledger: tuple[LedgerEvent, ...]
    checkpoint: ResumeCheckpoint
    resume_request: ResumeRequest


class PaperDecision(BoundaryModel):
    stop_code: PaperStopCode
    lifecycle_review_eligible: bool
    reasons: tuple[str, ...]
    metrics: PaperMetrics
