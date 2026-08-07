from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    model_validator,
)

from src.v4.models import JsonValue, canonical_json

from .statistical_models import ContractValueError, HashText, Relation


def _probability(value: str) -> str:
    number = Decimal(value)
    if number < 0 or number > 1 or value.startswith("-0"):
        raise ContractValueError("decimal", "probability outside [0, 1]")
    return value


def _positive(value: str) -> str:
    if Decimal(value) <= 0:
        raise ContractValueError("decimal", "must be positive")
    return value


def _alpha(value: str) -> str:
    number = Decimal(value)
    if number <= 0 or number > Decimal("0.05"):
        raise ContractValueError("alpha", "must be in (0, 0.05]")
    return value


def _nonnegative(value: str) -> str:
    if Decimal(value) < 0 or value.startswith("-0"):
        raise ContractValueError("decimal", "must be nonnegative")
    return value


DecimalSix = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{6}$")]
ProbabilitySix = Annotated[DecimalSix, AfterValidator(_probability)]
AlphaSix = Annotated[DecimalSix, AfterValidator(_alpha)]
PositiveSix = Annotated[DecimalSix, AfterValidator(_positive)]
NonnegativeSix = Annotated[DecimalSix, AfterValidator(_nonnegative)]
NonnegativeFour = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{4}$"), AfterValidator(_nonnegative)]
PositiveTwelve = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{12}$"), AfterValidator(_positive)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
VerificationStatus = Literal[
    "verified_stable", "rejected_in_sample_only", "rejected_direction_mismatch",
    "rejected_multiple_testing", "rejected_structural_break", "rejected_leakage",
    "rejected_p_hacking", "rejected_flaky", "rejected_malformed", "inconclusive",
]


class ReadModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class EvidenceRead(ReadModel):
    p_value: ProbabilitySix
    f_stat: NonnegativeFour
    direction_match: StrictBool
    rows: PositiveInt


class LagEvidenceRead(EvidenceRead):
    lag: PositiveInt


class StationarityRead(ReadModel):
    subject_diff_order: Annotated[int, Field(strict=True, ge=0, le=2)]
    object_diff_order: Annotated[int, Field(strict=True, ge=0, le=2)]
    subject_adf_p_value: ProbabilitySix
    object_adf_p_value: ProbabilitySix
    stationarity_alpha: Annotated[ProbabilitySix, AfterValidator(_positive)]


class MultipleTestingRead(ReadModel):
    alpha: AlphaSix
    tested_hypotheses: PositiveInt
    corrected_alpha: PositiveTwelve
    correction_method: Literal["bonferroni"]
    correction_scope_hash: HashText

    @model_validator(mode="after")
    def exact_correction(self) -> Self:
        expected = Decimal(self.alpha) / Decimal(self.tested_hypotheses)
        if Decimal(self.corrected_alpha) != expected.quantize(Decimal("0.000000000001")):
            raise ContractValueError("corrected_alpha", "does not equal alpha / hypotheses")
        return self


class SplitRead(ReadModel):
    pair_id: Annotated[str, Field(pattern=r"^statpair_[0-9a-f]{20}$")]
    policy: Literal["chronological_70_10_20"]
    aligned_rows: PositiveInt
    train_rows: PositiveInt
    embargo_rows: PositiveInt
    holdout_rows: PositiveInt
    train_start: AwareDatetime
    train_end: AwareDatetime
    embargo_start: AwareDatetime
    embargo_end: AwareDatetime
    holdout_start: AwareDatetime
    holdout_end: AwareDatetime

    @model_validator(mode="after")
    def contiguous_counts(self) -> Self:
        if self.train_rows + self.embargo_rows + self.holdout_rows != self.aligned_rows:
            raise ContractValueError("split", "row counts do not cover aligned rows")
        if not self.train_end < self.embargo_start <= self.embargo_end < self.holdout_start:
            raise ContractValueError("split", "timestamps are not disjoint and chronological")
        return self


class WindowRead(ReadModel):
    window_id: str
    rows: PositiveInt
    p_value: ProbabilitySix
    direction_match: StrictBool
    mean_shift: NonnegativeSix
    variance_ratio: PositiveSix
    status: Literal["pass", "fail", "inconclusive"]


class StabilityRead(ReadModel):
    structural_break_check: Literal["pass", "fail", "inconclusive"]
    predeclared_windows: tuple[WindowRead, ...]
    rolling_windows_checked: NonnegativeInt
    rolling_windows_passed: NonnegativeInt
    inconclusive_windows: NonnegativeInt
    oos_stability: Literal["pass", "fail", "inconclusive"]

    @model_validator(mode="after")
    def valid_counts(self) -> Self:
        rolling = tuple(item for item in self.predeclared_windows if item.window_id.startswith("rolling_"))
        checked = len(rolling)
        passed = sum(item.status == "pass" for item in rolling)
        if self.rolling_windows_checked != checked or self.rolling_windows_passed != passed:
            raise ContractValueError("stability", "rolling counts differ from rolling window states")
        failed = any(item.status == "fail" for item in self.predeclared_windows)
        inconclusive = any(item.status == "inconclusive" for item in self.predeclared_windows)
        if failed != (self.structural_break_check == "fail"):
            raise ContractValueError("stability", "structural break result differs from window states")
        if self.structural_break_check == "inconclusive" and (failed or not inconclusive):
            raise ContractValueError("stability", "inconclusive result lacks matching window state")
        if self.structural_break_check == "fail" and self.oos_stability == "pass":
            raise ContractValueError("stability", "failed structural check cannot pass OOS stability")
        return self


class PairResultRead(ReadModel):
    pair_id: Annotated[str, Field(pattern=r"^statpair_[0-9a-f]{20}$")]
    subject_node_id: Annotated[str, Field(min_length=1)]
    object_node_id: Annotated[str, Field(min_length=1)]
    subject_label: Annotated[str, Field(min_length=1)]
    object_label: Annotated[str, Field(min_length=1)]
    relation: Relation
    subject_series_id: Annotated[str, Field(min_length=1)]
    object_series_id: Annotated[str, Field(min_length=1)]
    subject_mapping_hash: HashText
    object_mapping_hash: HashText
    mapping_expires_at: AwareDatetime
    verification_expires_at: AwareDatetime
    verification_cutoff: AwareDatetime
    declared_lag_grid: tuple[PositiveInt, ...]
    input_fingerprint: HashText
    run_config_hash: HashText
    correction_scope_hash: HashText
    split_policy_hash: HashText
    window_policy_hash: HashText
    verification_status: VerificationStatus
    method: Literal["granger_predictive_lead"]
    claim_label: Literal["statistical_lead_evidence"]
    selected_lag: PositiveInt | None
    train: EvidenceRead | None
    holdout: EvidenceRead | None
    stationarity: StationarityRead | None
    train_lag_table: tuple[LagEvidenceRead, ...]
    multiple_testing: MultipleTestingRead | None
    split: SplitRead | None
    stability: StabilityRead | None
    confidence: ProbabilitySix
    rejection_reason: str | None

    @model_validator(mode="after")
    def terminal_contract(self) -> Self:
        seed: JsonValue = {
            "schema_version": "causal-statistical-verification.1",
            "subject_node_id": self.subject_node_id,
            "object_node_id": self.object_node_id,
            "relation": self.relation,
            "subject_mapping_hash": self.subject_mapping_hash,
            "object_mapping_hash": self.object_mapping_hash,
            "verification_cutoff": self.verification_cutoff.isoformat(),
            "lag_grid": list(self.declared_lag_grid),
        }
        expected = f"statpair_{sha256(canonical_json(seed)).hexdigest()[:20]}"
        if self.pair_id != expected:
            raise ContractValueError("pair_id", "does not match canonical seed")
        if tuple(sorted(set(self.declared_lag_grid))) != self.declared_lag_grid:
            raise ContractValueError("declared_lag_grid", "must be unique and ascending")
        if self.verification_expires_at > self.mapping_expires_at:
            raise ContractValueError("verification_expires_at", "exceeds mapping expiry")
        tested = self.selected_lag is not None
        evidence = (self.train, self.holdout, self.stationarity, self.multiple_testing, self.split, self.stability)
        if tested != all(item is not None for item in evidence):
            raise ContractValueError("pair_result", "tested evidence is incomplete")
        if self.selected_lag is not None and self.selected_lag not in self.declared_lag_grid:
            raise ContractValueError("selected_lag", "not in declared grid")
        if self.selected_lag is not None and self.selected_lag not in {item.lag for item in self.train_lag_table}:
            raise ContractValueError("selected_lag", "missing from train lag table")
        if self.multiple_testing is not None and self.multiple_testing.correction_scope_hash != self.correction_scope_hash:
            raise ContractValueError("correction_scope_hash", "pair and evidence differ")
        if self.split is not None and self.split.pair_id != self.pair_id:
            raise ContractValueError("split.pair_id", "does not match pair")
        if self.verification_status == "verified_stable":
            if self.rejection_reason is not None or self.train is None or self.holdout is None or self.stability is None:
                raise ContractValueError("verified_stable", "success evidence is incomplete")
            if not self.train.direction_match or not self.holdout.direction_match or self.stability.structural_break_check != "pass" or self.stability.oos_stability != "pass":
                raise ContractValueError("verified_stable", "direction or stability failed")
            if self.multiple_testing is None or Decimal(self.train.p_value) >= Decimal(self.multiple_testing.corrected_alpha) or Decimal(self.holdout.p_value) >= Decimal(self.multiple_testing.corrected_alpha):
                raise ContractValueError("verified_stable", "p-value does not pass correction")
        elif not self.rejection_reason:
            raise ContractValueError("rejection_reason", "terminal non-success requires reason")
        return self


PAIR_RESULT_ADAPTER = TypeAdapter(PairResultRead)
