from __future__ import annotations

from enum import StrEnum, unique
from typing import ClassVar, Final, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .errors import InputValueError
from .validation import canonical_date, canonical_decimal, canonical_utc


PERSPECTIVE_IDS: Final = ("kwangsoo", "ouroboros", "quant", "macro", "value")


@unique
class Market(StrEnum):
    KR = "KR"
    US = "US"


@unique
class Currency(StrEnum):
    KRW = "KRW"
    USD = "USD"


@unique
class Action(StrEnum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


@unique
class SessionStatus(StrEnum):
    OPEN = "OPEN"
    EARLY_CLOSE = "EARLY_CLOSE"
    CLOSED = "CLOSED"


@unique
class Verdict(StrEnum):
    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"
    NEUTRAL = "NEUTRAL"


@unique
class CandidateStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


@unique
class CandidateTransition(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    SCHEDULE = "schedule"
    ROLLBACK = "rollback"


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)


class MeasurementNamespace(StrictModel):
    market: Market
    currency: Currency
    account_id: str
    arm_id: str

    @model_validator(mode="after")
    def validate_namespace(self) -> Self:
        expected = Currency.KRW if self.market is Market.KR else Currency.USD
        if self.currency is not expected or any(
            not value or value != value.strip()
            for value in (self.account_id, self.arm_id)
        ):
            raise InputValueError("invalid market namespace")
        return self


class Namespace(MeasurementNamespace):
    symbol: str

    @model_validator(mode="after")
    def validate_symbol(self) -> Self:
        if not self.symbol or self.symbol != self.symbol.strip():
            raise InputValueError("invalid symbol")
        return self


class Lineage(StrictModel):
    runtime_identity: str
    config_version: str
    source_policy_version: str
    calendar_version: str
    calendar_hash: str
    price_adjustment_version: str

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        values = (
            self.runtime_identity,
            self.config_version,
            self.source_policy_version,
            self.calendar_version,
            self.calendar_hash,
            self.price_adjustment_version,
        )
        if any(not value or value != value.strip() for value in values):
            raise InputValueError("lineage values must be canonical")
        return self


class PredictionInput(StrictModel):
    schema_version: str
    recommendation_id: str
    namespace: Namespace
    lineage: Lineage
    prediction_session: str
    horizon_sessions: int
    action: Action
    reference_price_minor: int
    perspective_scores: dict[str, str]
    perspective_scores_as_of: str
    recorded_as_of: str

    @field_validator("prediction_session")
    @classmethod
    def validate_session(cls, value: str) -> str:
        return canonical_date(value)

    @field_validator("perspective_scores_as_of", "recorded_as_of")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return canonical_utc(value)

    @model_validator(mode="after")
    def validate_prediction(self) -> Self:
        if self.schema_version not in {
            "v18.normalized-recommendation.1",
            "v18.prediction.1",
        }:
            raise InputValueError("unknown prediction input schema")
        if not self.recommendation_id or self.recommendation_id != self.recommendation_id.strip():
            raise InputValueError("recommendation_id must be canonical")
        if self.horizon_sessions not in {1, 3} or self.reference_price_minor <= 0:
            raise InputValueError("invalid horizon or reference price")
        if tuple(sorted(self.perspective_scores)) != tuple(sorted(PERSPECTIVE_IDS)):
            raise InputValueError("perspective set mismatch")
        for score in self.perspective_scores.values():
            _ = canonical_decimal(score)
            if not 0 <= int(score.replace(".", "")) <= 1_000_000:
                raise InputValueError("perspective score outside range")
        if self.perspective_scores_as_of > self.recorded_as_of:
            raise InputValueError("perspective score leakage")
        return self


class PredictionRecord(PredictionInput):
    schema_version: str = "v18.prediction.1"
    prediction_id: str
    source_payload_hash: str
    current_state: str = "REGISTERED"


class LegacyQuarantineRecord(StrictModel):
    schema_version: str = "v18.legacy-quarantine.1"
    quarantine_id: str
    source_label: str
    source_bytes_hash: str
    observed_schema_hint: str
    rejection_codes: tuple[str, ...]
    observed_as_of: str

    @field_validator("observed_as_of")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return canonical_utc(value)


class CalendarSession(StrictModel):
    market: Market
    session: str
    status: SessionStatus
    close_at: str | None
    calendar_version: str
    calendar_hash: str

    @field_validator("session")
    @classmethod
    def validate_session(cls, value: str) -> str:
        return canonical_date(value)

    @field_validator("close_at")
    @classmethod
    def validate_close(cls, value: str | None) -> str | None:
        return None if value is None else canonical_utc(value)


class AdjustedClose(StrictModel):
    schema_version: str = "v18.adjusted-close.1"
    namespace: Namespace
    session: str
    adjusted_close_minor: int
    adjustment_version: str
    dataset_hash: str

    @field_validator("session")
    @classmethod
    def validate_session(cls, value: str) -> str:
        return canonical_date(value)


class OutcomeEvaluation(StrictModel):
    schema_version: str = "v18.outcome.1"
    outcome_id: str
    prediction_id: str
    target_session: str
    target_adjusted_price_minor: int
    return_bps: int
    verdict: Verdict
    maturity_as_of: str
    evaluator_policy_version: str
    calendar_hash: str
    price_dataset_hash: str

    @field_validator("maturity_as_of")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return canonical_utc(value)


class CohortSpecification(StrictModel):
    namespace: MeasurementNamespace
    horizon_sessions: int
    source_policy_version: str
    evaluator_policy_version: str
    calendar_version: str
    price_adjustment_version: str
    eligibility_policy_version: str
    cutoff_as_of: str
    prediction_ids: tuple[str, ...]

    @field_validator("cutoff_as_of")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return canonical_utc(value)


class CohortManifest(StrictModel):
    schema_version: str = "v18.cohort-manifest.1"
    cohort_id: str
    specification: CohortSpecification
    member_ids: tuple[str, ...]
    decisions: dict[str, str]
    outcome_hashes: dict[str, str]
    manifest_hash: str


class PolicyCandidate(StrictModel):
    schema_version: str = "v18.policy-candidate.1"
    candidate_id: str
    candidate_version: str
    base_policy_version: str
    namespace: MeasurementNamespace
    cohort_id: str
    objective_version: str
    weights: dict[str, str]
    effective_session: str
    created_as_of: str
    evidence_hash: str
    status: CandidateStatus

    @field_validator("effective_session")
    @classmethod
    def validate_session(cls, value: str) -> str:
        return canonical_date(value)

    @field_validator("created_as_of")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return canonical_utc(value)
