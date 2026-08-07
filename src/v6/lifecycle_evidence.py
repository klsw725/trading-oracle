from decimal import Decimal, ROUND_HALF_EVEN
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from src.v4.models import canonical_hash

from .lifecycle_models import Probability6
from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, JsonBoundary
from .offline_models import ContentHash
from .paper_artifact import PaperCohortArtifact


def hash_body(value: BoundaryModel) -> str:
    return canonical_hash(JsonBoundary.model_validate(value.model_dump(mode="json")).root)


class ErrorOutcomeBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-error-outcome.1"]
    sample_id: str
    paper_horizon_record_hash: ContentHash
    candidate_error: bool
    baseline_error: bool


class ErrorOutcome(ErrorOutcomeBody):
    record_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = ErrorOutcomeBody.model_validate(self.model_dump(mode="json", exclude={"record_hash"}))
        if self.record_hash != hash_body(body):
            raise ContractInvariantError("error outcome hash mismatch")
        return self


class PromotionErrorWindowBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-promotion-window.1"]
    paper_artifact_hash: ContentHash
    market: Literal["KR", "US"]
    window_end_session_id: str
    records: tuple[ErrorOutcome, ...]


class PromotionErrorWindow(PromotionErrorWindowBody):
    window_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = PromotionErrorWindowBody.model_validate(self.model_dump(mode="json", exclude={"window_hash"}))
        if self.window_hash != hash_body(body):
            raise ContractInvariantError("promotion window hash mismatch")
        if not self.records or len({record.sample_id for record in self.records}) != len(self.records):
            raise ContractInvariantError("promotion error records must be non-empty and unique")
        return self


class ErrorMetrics(BoundaryModel):
    mature_samples: int
    candidate_error_rate: Probability6
    baseline_error_rate: Probability6
    error_delta: Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$")]


def validate_promotion_window(paper: PaperCohortArtifact, window: PromotionErrorWindow) -> ErrorMetrics:
    if window.paper_artifact_hash != paper.artifact_hash:
        raise ContractInvariantError("promotion window paper artifact mismatch")
    five = next(item for item in paper.paper_input.horizon_observations if item.horizon_market_sessions == 5)
    mature = tuple(record for record in five.records if record.mature)
    expected = tuple((record.sample_id, record.record_hash) for record in mature)
    observed = tuple((record.sample_id, record.paper_horizon_record_hash) for record in window.records)
    if observed != expected:
        raise ContractInvariantError("promotion records must align to every mature five-session outcome")
    count = len(window.records)
    candidate = Decimal(sum(record.candidate_error for record in window.records)) / Decimal(count)
    baseline = Decimal(sum(record.baseline_error for record in window.records)) / Decimal(count)
    quant = Decimal("0.000001")
    return ErrorMetrics(mature_samples=count, candidate_error_rate=f"{candidate.quantize(quant, rounding=ROUND_HALF_EVEN):.6f}", baseline_error_rate=f"{baseline.quantize(quant, rounding=ROUND_HALF_EVEN):.6f}", error_delta=f"{(candidate - baseline).quantize(quant, rounding=ROUND_HALF_EVEN):.6f}")


def raw_promotion_error_delta(window: PromotionErrorWindow) -> Decimal:
    return raw_error_delta(sum(record.candidate_error for record in window.records), sum(record.baseline_error for record in window.records), len(window.records))


def raw_error_delta(candidate_errors: int, baseline_errors: int, count: int) -> Decimal:
    return Decimal(candidate_errors - baseline_errors) / Decimal(count)


class AttemptObservationBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-attempt-observation.1"]
    attempt_id: str
    production_decision_id: str
    market_session_ordinal: Annotated[int, Field(strict=True, ge=1)]
    target_disagreement: bool
    parser_failed: bool
    candidate_verdict: Literal["BUY", "SELL", "HOLD", "N/A"] | None
    latency_ms: Annotated[int, Field(strict=True, ge=0)]


class AttemptObservation(AttemptObservationBody):
    record_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = AttemptObservationBody.model_validate(self.model_dump(mode="json", exclude={"record_hash"}))
        if self.record_hash != hash_body(body):
            raise ContractInvariantError("attempt observation hash mismatch")
        return self


class MonitoringWindowBody(BoundaryModel):
    schema_version: Literal["v6.lifecycle-monitoring-window.1"]
    window_id: str
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    policy_version: str
    market: Literal["KR", "US"]
    window_index: Annotated[int, Field(strict=True, ge=0)]
    previous_window_hash: ContentHash | None
    records: tuple[AttemptObservation, ...]


class MonitoringWindow(MonitoringWindowBody):
    window_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = MonitoringWindowBody.model_validate(self.model_dump(mode="json", exclude={"window_hash"}))
        if self.window_hash != hash_body(body) or not self.records or len({item.attempt_id for item in self.records}) != len(self.records):
            raise ContractInvariantError("monitoring window integrity mismatch")
        return self
