from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import NewType, override

from src.v4.models import (
    Action,
    AttributionEventId,
    CandidateId,
    ContentHash,
    JsonValue,
    OrderId,
    PortfolioTradeId,
    RecommendationId,
    canonical_hash,
)


LedgerId = NewType("LedgerId", str)
FillId = NewType("FillId", str)
CorrectedBy = NewType("CorrectedBy", str)


@unique
class LifecycleEventType(StrEnum):
    CANDIDATE_INVENTORY_RECORDED = "CANDIDATE_INVENTORY_RECORDED"
    CANDIDATE_SEEN = "CANDIDATE_SEEN"
    RECOMMENDATION_EMITTED = "RECOMMENDATION_EMITTED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    OPERATOR_DECISION_RECORDED = "OPERATOR_DECISION_RECORDED"
    ORDER_LINKED = "ORDER_LINKED"
    FILL_RECORDED = "FILL_RECORDED"
    POSITION_CLOSED = "POSITION_CLOSED"
    OUTCOME_MATURED = "OUTCOME_MATURED"
    CORRECTION_RECORDED = "CORRECTION_RECORDED"


@unique
class IntegrityRule(StrEnum):
    INVALID_TERMINAL = "invalid_terminal"
    DUPLICATE_TERMINAL = "duplicate_terminal"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    INVENTORY_REQUIRED = "inventory_required"
    INVENTORY_MISMATCH = "inventory_mismatch"
    ORPHAN_EVENT = "orphan_event"
    DISAPPEARED_CANDIDATE = "disappeared_candidate"
    LIFECYCLE_ORDER = "lifecycle_order"
    EXECUTION_LINK = "execution_link"
    CORRECTION_TARGET = "correction_target"
    OLD_VALUE_HASH = "old_value_hash"
    HASH_CHAIN = "hash_chain"
    TIMEZONE_REQUIRED = "timezone_required"
    INVALID_OPERATOR_DECISION = "invalid_operator_decision"


@dataclass(frozen=True, slots=True)
class LifecycleIntegrityError(Exception):
    rule: IntegrityRule
    candidate_id: CandidateId | None = None

    @override
    def __str__(self) -> str:
        return f"attribution lifecycle violation: {self.rule} ({self.candidate_id})"


@dataclass(frozen=True, slots=True)
class CandidateInventoryRecorded:
    candidate_ids: tuple[CandidateId, ...]
    candidate_count: int
    inventory_hash: ContentHash

    @classmethod
    def create(cls, candidate_ids: tuple[CandidateId, ...]) -> "CandidateInventoryRecorded":
        return cls(candidate_ids, len(candidate_ids), canonical_hash(list(candidate_ids)))


@dataclass(frozen=True, slots=True)
class CandidateSeen:
    candidate_id: CandidateId


@dataclass(frozen=True, slots=True)
class TerminalAttribution:
    candidate_id: CandidateId
    recommendation_id: RecommendationId | None
    ticker: str
    action: Action
    confidence_probability: float | None
    horizons: tuple[int, ...]

    def __post_init__(self) -> None:
        common = bool(self.horizons) and all(value > 0 for value in self.horizons) and (self.confidence_probability is None or 0 <= self.confidence_probability <= 1)
        match self.action:  # noqa: MATCH_OK - every Action member is explicit
            case Action.BUY | Action.SELL | Action.HOLD | Action.BLOCKED: valid = self.recommendation_id is not None and self.confidence_probability is not None
            case Action.CANDIDATE_REJECTED: valid = self.recommendation_id is None
        if not common or not valid: raise LifecycleIntegrityError(IntegrityRule.INVALID_TERMINAL, self.candidate_id)


@unique
class OperatorDecisionState(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"
    PARTIAL_EXECUTION = "partial_execution"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True, init=False)
class OperatorDecisionRecorded:
    candidate_id: CandidateId
    recommendation_id: RecommendationId
    state: OperatorDecisionState

    def __init__(
        self,
        candidate_id: CandidateId,
        recommendation_id: RecommendationId,
        state: OperatorDecisionState | str,
    ) -> None:
        try:
            parsed_state = OperatorDecisionState(state)
        except ValueError as error:
            raise LifecycleIntegrityError(
                IntegrityRule.INVALID_OPERATOR_DECISION, candidate_id
            ) from error
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "recommendation_id", recommendation_id)
        object.__setattr__(self, "state", parsed_state)


@dataclass(frozen=True, slots=True)
class OrderLinked:
    candidate_id: CandidateId
    order_id: OrderId
    portfolio_trade_id: PortfolioTradeId


@dataclass(frozen=True, slots=True)
class FillRecorded:
    candidate_id: CandidateId
    order_id: OrderId
    fill_id: FillId


@dataclass(frozen=True, slots=True)
class PositionClosed:
    candidate_id: CandidateId
    portfolio_trade_id: PortfolioTradeId


@dataclass(frozen=True, slots=True)
class OutcomeMatured:
    candidate_id: CandidateId
    recommendation_id: RecommendationId
    horizon: int


@dataclass(frozen=True, slots=True)
class CorrectionRecorded:
    candidate_id: CandidateId
    target_event_id: AttributionEventId
    field_path: str
    old_value_hash: ContentHash
    new_value: JsonValue
    reason: str
    corrected_by: CorrectedBy


type LifecyclePayload = CandidateInventoryRecorded | CandidateSeen | TerminalAttribution | OperatorDecisionRecorded | OrderLinked | FillRecorded | PositionClosed | OutcomeMatured | CorrectionRecorded


@dataclass(frozen=True, slots=True)
class AttributionEvent:
    event_id: AttributionEventId
    event_type: LifecycleEventType
    occurred_at: datetime
    recorded_at: datetime
    prev_event_hash: ContentHash
    event_hash: ContentHash
    payload: LifecyclePayload


@dataclass(frozen=True, slots=True)
class DenominatorSummary:
    buy: int
    sell: int
    hold: int
    blocked: int
    candidate_rejected: int
    decision_quality_total: int
    execution_quality_total: int
    selection_quality_total: int

    def cohort_count(self, action: Action) -> int:
        return (self.buy, self.sell, self.hold, self.blocked, self.candidate_rejected)[list(Action).index(action)]
