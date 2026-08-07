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
    TypeAdapter,
    model_validator,
)

from src.v4.models import JsonValue, canonical_hash, canonical_json

from .statistical_models import ContractValueError, HashText


def _probability(value: str) -> str:
    number = Decimal(value)
    if not Decimal("0") <= number <= Decimal("1"):
        raise ContractValueError("decimal", "probability outside [0, 1]")
    return value


DecimalSix = Annotated[
    str,
    Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{6}$"),
]
ProbabilitySix = Annotated[DecimalSix, AfterValidator(_probability)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
Eligibility = Literal[
    "excluded_inconclusive",
    "excluded_rejected",
    "excluded_malformed",
    "excluded_stale",
    "excluded_low_confidence",
    "excluded_budget_overflow",
]
MutationName = Literal[
    "inject_verified",
    "exclude_inconclusive",
    "exclude_rejected",
    "exclude_malformed",
    "exclude_stale",
    "exclude_low_confidence",
    "exclude_budget_overflow",
    "rollback_package",
]


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class PromptConfig(StrictModel):
    schema_version: Literal["causal-prompt-injection-build.1"]
    generated_at: AwareDatetime
    prompt_cutoff: AwareDatetime
    freshness_window_hours: PositiveInt
    package_ttl_hours: PositiveInt
    minimum_confidence: ProbabilitySix
    max_tokens: PositiveInt
    reserved_tokens: NonnegativeInt
    ordering_policy: Literal["freshness_confidence_holdout_p_lag_pair"]
    verified_section_label: Literal["데이터 검증됨, 통계적 선행 근거"]

    @model_validator(mode="after")
    def valid_budget_and_time(self) -> Self:
        if self.reserved_tokens >= self.max_tokens:
            raise ContractValueError("reserved_tokens", "must be below max_tokens")
        if self.prompt_cutoff > self.generated_at:
            raise ContractValueError("prompt_cutoff", "cannot exceed generated_at")
        return self


class VerificationArtifact(StrictModel):
    schema_version: Literal["causal-statistical-verification.1"]
    source_node_schema_version: Literal["causal-node-canonicalization.1"]
    source_mapping_schema_version: Literal["causal-series-mapping.1"]
    source_node_artifact_hash: HashText
    verification_policy_version: Literal["statistical-verifier.1"]
    generated_at: AwareDatetime
    verification_cutoff: AwareDatetime
    input_fingerprint: HashText
    run_config_hash: HashText
    correction_scope_hash: HashText
    split_policy_hash: HashText
    window_policy_hash: HashText
    metadata: JsonValue
    pair_results: tuple[JsonValue, ...]
    verification_mutations: tuple[JsonValue, ...]
    qa: JsonValue

    @model_validator(mode="after")
    def valid_source_time(self) -> Self:
        if self.verification_cutoff > self.generated_at:
            raise ContractValueError("verification_cutoff", "exceeds source generation time")
        return self


class PromptFreshness(StrictModel):
    verification_generated_at: AwareDatetime
    verification_expires_at: AwareDatetime
    mapping_expires_at: AwareDatetime
    is_fresh: Literal[True]


class PromptProvenance(StrictModel):
    source_artifact_hash: HashText
    run_config_hash: HashText
    correction_scope_hash: HashText
    subject_mapping_hash: HashText
    object_mapping_hash: HashText


class PromptEvidence(StrictModel):
    train_p_value: ProbabilitySix
    holdout_p_value: ProbabilitySix
    corrected_alpha: Annotated[str, Field(pattern=r"^0\.[0-9]{12}$")]
    direction_match_train: Literal[True]
    direction_match_holdout: Literal[True]
    stability: Literal["pass"]


class VerifiedPromptRecord(StrictModel):
    pair_id: Annotated[str, Field(pattern=r"^statpair_[0-9a-f]{20}$")]
    prompt_record_id: Annotated[str, Field(pattern=r"^promptrec_[0-9a-f]{20}$")]
    eligibility: Literal["verified_prompt_eligible"]
    claim_label: Literal["statistical_lead_evidence"]
    render_label: Literal["데이터 검증됨, 통계적 선행 근거"]
    subject_node_id: str
    object_node_id: str
    subject_label: str
    object_label: str
    relation: str
    selected_lag: PositiveInt
    confidence: ProbabilitySix
    freshness: PromptFreshness
    provenance: PromptProvenance
    evidence: PromptEvidence
    token_estimate: PositiveInt
    render_text: str


class ExcludedPromptRecord(StrictModel):
    pair_id: str
    eligibility: Eligibility
    reason: str
    rank: PositiveInt | None = None
    token_estimate: PositiveInt | None = None


class PromptMutation(StrictModel):
    mutation: MutationName
    pair_id: str | None
    from_status: str | None
    to_eligibility: str
    reason: str
    rank: PositiveInt | None = None
    token_estimate: PositiveInt | None = None
    mutated_at: AwareDatetime
    mutated_by: Literal["prompt-injection-gate.1"]


class PromptBudget(StrictModel):
    max_tokens: PositiveInt
    reserved_tokens: NonnegativeInt
    used_tokens: NonnegativeInt
    overflow_count: NonnegativeInt


class PromptQa(StrictModel):
    read_checks: tuple[str, ...]
    json_checks: tuple[str, ...]
    mutation_checks: tuple[str, ...]


class PromptPackage(StrictModel):
    schema_version: Literal["causal-prompt-injection.1"]
    source_verification_schema_version: Literal["causal-statistical-verification.1"]
    prompt_policy_version: Literal["prompt-injection-gate.1"]
    generated_at: AwareDatetime
    prompt_cutoff: AwareDatetime
    expires_at: AwareDatetime
    source_artifact_hash: HashText
    package_hash: HashText
    rollback_to_package_hash: HashText | None
    budget: PromptBudget
    verified_prompt_records: tuple[VerifiedPromptRecord, ...]
    excluded_prompt_records: tuple[ExcludedPromptRecord, ...]
    prompt_mutations: tuple[PromptMutation, ...]
    qa: PromptQa

    @model_validator(mode="after")
    def valid_package_hash(self) -> Self:
        body = self.model_dump(mode="json")
        del body["package_hash"]
        if self.package_hash != canonical_hash(body):
            raise ContractValueError("package_hash", "does not match canonical package body")
        if self.prompt_cutoff > self.generated_at or self.generated_at >= self.expires_at:
            raise ContractValueError("package_time", "requires cutoff <= generated < expiry")
        used_tokens = sum(record.token_estimate for record in self.verified_prompt_records)
        overflow_count = sum(
            record.eligibility == "excluded_budget_overflow"
            for record in self.excluded_prompt_records
        )
        if self.budget.used_tokens != used_tokens or self.budget.overflow_count != overflow_count:
            raise ContractValueError("budget", "counts differ from package records")
        if used_tokens > self.budget.max_tokens - self.budget.reserved_tokens:
            raise ContractValueError("budget", "verified records exceed available tokens")
        ordered = tuple(
            sorted(
                self.verified_prompt_records,
                key=lambda record: (
                    -record.freshness.verification_generated_at.timestamp(),
                    -Decimal(record.confidence),
                    Decimal(record.evidence.holdout_p_value),
                    record.selected_lag,
                    record.pair_id,
                ),
            )
        )
        if self.verified_prompt_records != ordered:
            raise ContractValueError("verified_prompt_records", "deterministic order violated")
        for record in self.verified_prompt_records:
            seed: JsonValue = {
                "schema_version": self.schema_version,
                "pair_id": record.pair_id,
                "prompt_cutoff": self.prompt_cutoff.isoformat(),
                "source_artifact_hash": self.source_artifact_hash,
                "render_text": record.render_text,
            }
            expected = f"promptrec_{sha256(canonical_json(seed)).hexdigest()[:20]}"
            if record.prompt_record_id != expected:
                raise ContractValueError("prompt_record_id", "does not match package cutoff")
            if record.provenance.source_artifact_hash != self.source_artifact_hash:
                raise ContractValueError("provenance", "source artifact hash differs")
            if self.expires_at > min(
                record.freshness.verification_expires_at,
                record.freshness.mapping_expires_at,
            ):
                raise ContractValueError("expires_at", "exceeds verified evidence expiry")
        return self


PROMPT_CONFIG_ADAPTER = TypeAdapter(PromptConfig)
VERIFICATION_ARTIFACT_ADAPTER = TypeAdapter(VerificationArtifact)
PROMPT_PACKAGE_ADAPTER = TypeAdapter(PromptPackage)
