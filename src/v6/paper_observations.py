from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from src.v4.models import canonical_hash

from .models import BoundaryModel, ContractInvariantError, JsonBoundary
from .offline_models import ContentHash, Decimal6, Probability6
from .paper_assignment_types import AssignmentInput, AssignmentResult


Verdict = Literal["BUY", "SELL", "HOLD", "N/A"]


def _hash(value: BoundaryModel) -> str:
    return canonical_hash(JsonBoundary.model_validate(value.model_dump(mode="json")).root)


class SampleObservationBody(BoundaryModel):
    schema_version: Literal["v6.paper-sample-observation.1"]
    sample_id: str
    target_disagreement: bool
    input_schema_valid: bool
    assignment_input: AssignmentInput
    assignment: AssignmentResult
    production_verdict: Verdict
    perspective: str
    shadow_verdict: Verdict
    shadow_confidence: Annotated[str, Field(pattern=r"^(?:0\.[0-9]{6}|1\.000000)$")]
    shadow_reason: str
    shadow_action: Literal["buy", "sell", "hold", "none"]
    vote_effect: Literal["none"]
    shadow_visible_to_user: Literal[False]
    cost_units: Annotated[int, Field(strict=True, ge=0)]
    shadow_recorded: Literal[True]
    latency_ms: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def na_contract(self) -> Self:
        if self.production_verdict != self.assignment_input.production_action:
            raise ContractInvariantError("sample production verdict must match assignment action")
        if self.shadow_verdict == "N/A" and (self.shadow_confidence != "0.000000" or self.shadow_action != "none"):
            raise ContractInvariantError("N/A sample observation requires zero confidence and none action")
        return self


class SampleObservation(SampleObservationBody):
    record_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = SampleObservationBody.model_validate(self.model_dump(mode="json", exclude={"record_hash"}))
        if self.record_hash != _hash(body):
            raise ContractInvariantError("sample observation hash mismatch")
        return self


class MarketSession(BoundaryModel):
    market: Literal["KR", "US"]
    session_id: str


class ObservationBatchBody(BoundaryModel):
    schema_version: Literal["v6.paper-observation-batch.2"]
    batch_id: str
    run_id: str
    policy_hash: ContentHash
    production_snapshot_hash: ContentHash
    decision_cutoff: str
    market_sessions: tuple[MarketSession, ...]
    records: tuple[SampleObservation, ...]
    shadow_vote_distribution_psi: Decimal6

    @model_validator(mode="after")
    def explicit_inventory(self) -> Self:
        sample_ids = tuple(record.sample_id for record in self.records)
        if not sample_ids or len(set(sample_ids)) != len(sample_ids):
            raise ContractInvariantError("sample observation IDs must be non-empty and unique")
        session_keys = tuple((session.market, session.session_id) for session in self.market_sessions)
        if not session_keys or len(set(session_keys)) != len(session_keys):
            raise ContractInvariantError("market session IDs must be non-empty and unique")
        return self


class ObservationBatch(ObservationBatchBody):
    batch_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = ObservationBatchBody.model_validate(self.model_dump(mode="json", exclude={"batch_hash"}))
        if self.batch_hash != _hash(body):
            raise ContractInvariantError("observation batch hash mismatch")
        return self


class OutcomeAdapterBody(BoundaryModel):
    adapter_id: str
    adapter_version: str
    observed_at: str
    staleness_rate: Probability6


class OutcomeAdapter(OutcomeAdapterBody):
    adapter_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = OutcomeAdapterBody.model_validate(self.model_dump(mode="json", exclude={"adapter_hash"}))
        if self.adapter_hash != _hash(body):
            raise ContractInvariantError("outcome adapter hash mismatch")
        return self


class HorizonOutcomeBody(BoundaryModel):
    schema_version: Literal["v6.paper-horizon-outcome.1"]
    sample_id: str
    mature: bool
    harmed: bool

    @model_validator(mode="after")
    def maturity(self) -> Self:
        if self.harmed and not self.mature:
            raise ContractInvariantError("harm requires a mature outcome")
        return self


class HorizonOutcome(HorizonOutcomeBody):
    record_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = HorizonOutcomeBody.model_validate(self.model_dump(mode="json", exclude={"record_hash"}))
        if self.record_hash != _hash(body):
            raise ContractInvariantError("horizon outcome hash mismatch")
        return self


class HorizonObservationBody(BoundaryModel):
    schema_version: Literal["v6.paper-horizon-observation.2"]
    batch_id: str
    run_id: str
    adapter_hash: ContentHash
    horizon_market_sessions: Literal[5, 20]
    records: tuple[HorizonOutcome, ...]

    @model_validator(mode="after")
    def explicit_inventory(self) -> Self:
        sample_ids = tuple(record.sample_id for record in self.records)
        if not sample_ids or len(set(sample_ids)) != len(sample_ids):
            raise ContractInvariantError("horizon outcome IDs must be non-empty and unique")
        return self


class HorizonObservation(HorizonObservationBody):
    observation_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = HorizonObservationBody.model_validate(self.model_dump(mode="json", exclude={"observation_hash"}))
        if self.observation_hash != _hash(body):
            raise ContractInvariantError("outcome observation hash mismatch")
        return self


class HorizonReport(BoundaryModel):
    horizon_market_sessions: Literal[5, 20]
    eligible_samples: int
    mature_samples: int
    mature_coverage: Probability6
    harmed_samples: int
    harm_rate: Probability6


class PaperMetrics(BoundaryModel):
    assigned_samples: int
    target_disagreement_samples: int
    running_duration_market_sessions: int
    candidate_na_rate: Probability6
    target_na_rate: Probability6
    latency_p95_ms: int
    input_schema_drift_rate: Probability6
    shadow_vote_distribution_psi: Decimal6
    production_shadow_disagreement_rate: Probability6
    disagreement_review_flag: bool
    horizon_reports: tuple[HorizonReport, HorizonReport]


def ratio(numerator: int, denominator: int) -> str:
    value = Decimal(numerator) / Decimal(denominator) if denominator else Decimal(0)
    return f"{value:.6f}"
