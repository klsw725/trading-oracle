from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Literal, override

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from pydantic_core import PydanticCustomError

from src.v11.models import Account, GateInputs, Market, Reservation, Side


Score = Annotated[Decimal, Field(ge=0, le=1)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
Quantity = Annotated[StrictInt, Field(gt=0)]


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="forbid", strict=True
    )


class RouterPolicy(StrictModel):
    schema_version: Literal["v13.router_policy.1"]
    minimum_score: Score
    minimum_gap: Score
    policy_hash: str


class CandidateLineage(StrictModel):
    v12_bundle_hash: str
    v12_run_hash: str
    v12_candidate_id: str
    risk_input_hash: str
    causal_artifact_id: str
    causal_content_hash: str
    causal_bundle_hash: str
    verified_account_hash: str


class CandidateEvidence(StrictModel):
    candidate_id: str
    market: Annotated[Market, Field(strict=False)]
    symbol: str
    sector: str
    strategy_id: str
    strategy_version: str
    side: Annotated[Side, Field(strict=False)]
    cutoff: Annotated[datetime, Field(strict=False)]
    watermark_at: Annotated[datetime, Field(strict=False)]
    decision_ready_at: Annotated[datetime, Field(strict=False)]
    deterministic_score: Score
    llm_score: Score | None
    confidence: Score | None
    hard_veto_verified: bool
    item_valid: bool
    abstain: bool
    target_quantity: Quantity
    reference_price: PositiveDecimal
    expected_cost: Annotated[Decimal, Field(ge=0)] = Decimal(0)
    candidate_returns: Annotated[tuple[str, ...], Field(strict=False)] = ()
    gates: GateInputs

    @model_validator(mode="after")
    def valid_item_has_llm_values(self) -> CandidateEvidence:
        if self.item_valid and not self.abstain:
            if self.llm_score is None or self.confidence is None:
                raise PydanticCustomError(
                    "v13_candidate_item", "valid item requires LLM score and confidence"
                )
        return self


class BoundCandidateEvidence(CandidateEvidence):
    lineage: CandidateLineage


class RecordedCandidateFixture(StrictModel):
    schema_version: Literal["v13.prd01.candidates.1"]
    candidates: Annotated[tuple[CandidateEvidence, ...], Field(strict=False)]


class RouterRunManifest(StrictModel):
    schema_version: Literal["v13.router_run.1"]
    run_id: str
    market: Annotated[Market, Field(strict=False)]
    cutoff: Annotated[datetime, Field(strict=False)]
    policy: RouterPolicy
    account: Account
    candidates: Annotated[tuple[CandidateEvidence, ...], Field(strict=False)]
    slot_limit: Annotated[StrictInt, Field(ge=0)]
    existing_returns: dict[str, Annotated[tuple[str, ...], Field(strict=False)]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def cohort_is_consistent(self) -> RouterRunManifest:
        if any(
            item.market is not self.market or item.cutoff != self.cutoff
            for item in self.candidates
        ):
            raise PydanticCustomError(
                "v13_cohort", "router cohort market or cutoff mismatch"
            )
        if self.account.market is not self.market:
            raise PydanticCustomError("v13_account", "router account market mismatch")
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise PydanticCustomError(
                "v13_candidate_ids", "router candidate IDs must be unique"
            )
        return self


class ScoredCandidate(StrictModel):
    evidence: CandidateEvidence
    deterministic_percentile: Score
    llm_percentile: Score | None
    composite_score: Score
    expected_turnover: Annotated[Decimal, Field(ge=0)]
    quant_only: bool


class SelectedDecision(StrictModel):
    state: Literal["selected"] = "selected"
    symbol: str
    candidate: ScoredCandidate
    runner_up_score: Score | None
    score_gap: Score | None

    @property
    def allocation_candidate(self) -> ScoredCandidate:
        return self.candidate


class NoTradeDecision(StrictModel):
    state: Literal["no_trade"] = "no_trade"
    symbol: str
    reason_code: Literal[
        "NO_CANDIDATE", "MINIMUM_SCORE", "MINIMUM_GAP"
    ]
    best_score: Score | None
    score_gap: Score | None

    @property
    def allocation_candidate(self) -> None:
        return None


type SymbolDecision = SelectedDecision | NoTradeDecision


class AllocationAttempt(StrictModel):
    candidate_id: str
    symbol: str
    state: Literal["reserved", "deferred_held", "no_trade"]
    reason_code: str
    reservation: Reservation | None
    risk_input_hash: str | None


class RouterSelection(StrictModel):
    manifest_hash: str
    scored: Annotated[tuple[ScoredCandidate, ...], Field(strict=False)]
    decisions: Annotated[tuple[SymbolDecision, ...], Field(strict=False)]
    attempts: Annotated[tuple[AllocationAttempt, ...], Field(strict=False)]
    final_shadow_account: Account
    selection_hash: str


@dataclass(frozen=True, slots=True)
class V13ContractError(Exception):
    code: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"
