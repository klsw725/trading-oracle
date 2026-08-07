from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Annotated, ClassVar, Final, Literal, NewType, Self, override

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel, StrictFloat, StrictInt, StrictStr, StringConstraints, TypeAdapter, model_validator

from src.v4.models import JsonValue


CONTRACT_VERSION: Final = "perspective_candidate_contract.1"
ARTIFACT_SCHEMA_VERSION: Final = "perspective-candidate-contract-artifact.1"
FIXTURE_SCHEMA_VERSION: Final = "perspective-candidate-contract-fixture.1"
DECIMAL_PATTERN: Final = r"^(?:0|1)\.[0-9]{6}$"
SNAKE_PATTERN: Final = r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"
VERSION_PATTERN: Final = r"^[a-z][a-z0-9_]*\.[0-9]+\.[0-9]+$"

CandidateId = NewType("CandidateId", str)
CandidateVersion = NewType("CandidateVersion", str)
HypothesisId = NewType("HypothesisId", str)
MetricInput = StrictStr | StrictInt | StrictFloat
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class JsonBoundary(RootModel[JsonValue]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class BoundaryModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True, slots=True)
class ContractInvariantError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


@unique
class RejectionCode(StrEnum):
    DUPLICATE = "DUPLICATES_EXISTING_PERSPECTIVE"
    NO_HYPOTHESIS = "NO_INDEPENDENT_HYPOTHESIS"
    UNTYPED = "UNTYPED_INPUT_OR_OUTPUT"
    VERDICT = "MALFORMED_VERDICT"
    CONFIDENCE = "MALFORMED_CONFIDENCE"
    NA = "MALFORMED_NA"
    BUDGET = "BUDGET_EXCEEDED_BY_DESIGN"
    IDENTITY = "MISSING_OWNER_OR_VERSION"
    ADOPTION = "ADOPTS_CANDIDATE_DIRECTLY"


@unique
class ExistingPerspective(StrEnum):
    KWANGSOO = "kwangsoo"
    OUROBOROS = "ouroboros"
    QUANT = "quant"
    MACRO = "macro"
    VALUE = "value"


@unique
class PerspectiveInputField(StrEnum):
    TICKER = "ticker"
    NAME = "name"
    OHLCV = "ohlcv"
    SIGNALS = "signals"
    FUNDAMENTALS = "fundamentals"
    POSITION = "position"
    MARKET_CONTEXT = "market_context"
    CONFIG = "config"
    WEB_CONTEXT = "web_context"
    FX_SIGNAL = "fx_signal"


@unique
class ForbiddenFamily(StrEnum):
    KWANGSOO = "trend_following"
    OUROBOROS = "forensic_risk"
    QUANT = "six_signal_vote"
    MACRO = "macro_cycle"
    VALUE = "valuation_threshold"


@unique
class OverlapReviewStatus(StrEnum):
    INDEPENDENT = "independent"
    DUPLICATE = "duplicates_existing"


@unique
class Verdict(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NA = "N/A"


@unique
class ActionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    NONE = "none"


@unique
class RequestedStage(StrEnum):
    OFFLINE = "offline_evaluation"
    PRODUCTION = "production_adoption"


class CandidateIdentity(BoundaryModel):
    candidate_id: Annotated[CandidateId, Field(pattern=r"^pcand_v6_[a-z][a-z0-9_]*$")]
    candidate_name: Annotated[str, Field(pattern=SNAKE_PATTERN)]
    owner: NonBlank
    candidate_version: Annotated[CandidateVersion, Field(pattern=VERSION_PATTERN)]
    contract_version: NonBlank
    created_at: AwareDatetime
    change_summary: NonBlank


class Purpose(BoundaryModel):
    one_sentence: NonBlank
    decision_impact: NonBlank


class ExpectedDisagreement(BoundaryModel):
    with_existing: Annotated[tuple[ExistingPerspective, ...], Field(min_length=1)]
    direction: Literal[
        "downgrade_buy_to_hold_or_sell",
        "upgrade_hold_to_buy",
        "upgrade_hold_to_sell",
        "na_boundary_only",
    ]


class IndependentHypothesis(BoundaryModel):
    hypothesis_id: Annotated[HypothesisId, Field(pattern=r"^hyp_v6_[a-z][a-z0-9_]*_[0-9]{3}$")]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    error_mode_explained: NonBlank
    novel_signal_family: Annotated[str, Field(pattern=SNAKE_PATTERN)]
    primary_observations: Annotated[tuple[NonBlank, ...], Field(min_length=2, max_length=8)]
    expected_disagreement: ExpectedDisagreement
    falsifiable_claim: NonBlank


class ExtraInput(BoundaryModel):
    name: Annotated[str, Field(pattern=SNAKE_PATTERN)]
    type: str | None = None
    source_contract: str | None = None
    required_for_verdict: bool
    missing_behavior: str
    freshness_budget_hours: StrictInt | None = None


class InputContract(BoundaryModel):
    uses_perspective_input_fields: tuple[PerspectiveInputField, ...]
    required_extra_inputs: tuple[ExtraInput, ...]
    missing_behavior: Literal["N/A"]


class OutputContract(BoundaryModel):
    verdict_enum: tuple[str, ...]
    confidence_range: tuple[MetricInput, MetricInput]
    na_requires_confidence_zero: bool
    na_requires_action_none: bool


class OverlapReview(BoundaryModel):
    reviewer: NonBlank
    status: OverlapReviewStatus
    forbidden_families: tuple[ForbiddenFamily, ...]


class OverlapEntry(BoundaryModel):
    compared_to: ExistingPerspective
    input_overlap: MetricInput
    verdict_correlation_proxy: MetricInput
    overlap_score: MetricInput
    manual_review: OverlapReview


class CandidateBudget(BoundaryModel):
    max_wall_ms_per_ticker: StrictInt
    max_llm_calls_per_ticker: StrictInt
    max_prompt_tokens_per_ticker: StrictInt
    max_output_tokens_per_ticker: StrictInt
    max_extra_fetches_per_ticker: StrictInt
    cache_ttl_hours: StrictInt | None = None
    timeout_behavior: str


class CandidateProposal(BoundaryModel):
    candidate_identity: CandidateIdentity
    purpose: Purpose
    independent_hypothesis: IndependentHypothesis
    input_contract: InputContract
    output_contract: OutputContract
    overlap_matrix: Annotated[tuple[OverlapEntry, ...], Field(min_length=1)]
    budget: CandidateBudget
    requested_stage: RequestedStage = RequestedStage.OFFLINE

    @model_validator(mode="after")
    def bound_identity(self) -> Self:
        identity = self.candidate_identity
        name = identity.candidate_name
        hypothesis_id = self.independent_hypothesis.hypothesis_id
        if identity.candidate_id != f"pcand_v6_{name}":
            raise ContractInvariantError("candidate identity does not match candidate_name")
        if not identity.candidate_version.startswith(f"{name}."):
            raise ContractInvariantError("candidate_version does not match candidate_name")
        if not hypothesis_id.startswith(f"hyp_v6_{name}_"):
            raise ContractInvariantError("hypothesis identity does not match candidate_name")
        return self


class CandidateAction(BoundaryModel):
    type: ActionType
    watch: NonBlank | None = None


class CandidateOutputExtra(BoundaryModel):
    contract_version: NonBlank
    candidate_version: Annotated[str, Field(pattern=VERSION_PATTERN)]
    hypothesis_id: Annotated[str, Field(pattern=r"^hyp_v6_[a-z][a-z0-9_]*_[0-9]{3}$")]
    overlap_score: MetricInput
    novel_evidence: tuple[str, ...]
    not_applicable_reason: str | None = None
    missing_inputs: tuple[str, ...] = ()


class CandidateOutput(BoundaryModel):
    perspective: Annotated[str, Field(pattern=SNAKE_PATTERN)]
    verdict: str
    confidence: MetricInput
    reasoning: Annotated[tuple[NonBlank, ...], Field(min_length=1)]
    reason: NonBlank
    action: CandidateAction
    extra: CandidateOutputExtra


class CandidateDecision(BoundaryModel):
    accepted_for_evaluation: bool
    rejection_code: RejectionCode | None


CANDIDATE_ADAPTER: Final = TypeAdapter(CandidateProposal)
OUTPUT_ADAPTER: Final = TypeAdapter(CandidateOutput)
