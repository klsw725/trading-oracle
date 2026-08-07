from enum import StrEnum, unique
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from src.v4.models import canonical_hash

from .models import BoundaryModel, CandidateId, CandidateVersion, ContractInvariantError, HypothesisId, JsonBoundary
from .offline_models import ContentHash, Decimal6
from .lifecycle_registry import PolicyVersionRegistry


Probability6 = Annotated[str, Field(pattern=r"^(?:0\.[0-9]{6}|1\.000000)$")]
BasePerspective = Literal["kwangsoo", "ouroboros", "quant", "macro", "value"]
BASE_PERSPECTIVES: tuple[BasePerspective, ...] = ("kwangsoo", "ouroboros", "quant", "macro", "value")


@unique
class LifecycleState(StrEnum):
    PROPOSAL_RECEIVED = "proposal_received"
    OFFLINE_PASSED = "offline_passed"
    PAPER_READY = "paper_ready"
    LIMITED_PRODUCTION = "limited_production"
    RENEWAL_REVIEW = "renewal_review"
    ROLLED_BACK = "rolled_back"
    RETIRED = "retired"
    REJECTED = "rejected"


@unique
class LifecycleResultCode(StrEnum):
    CREATED_PAPER_READY = "CREATED_PAPER_READY"
    PROMOTION_APPROVED_LIMITED = "PROMOTION_APPROVED_LIMITED"
    PROMOTION_REJECTED_GATE = "PROMOTION_REJECTED_GATE"
    RENEWAL_REVIEW_OPENED = "RENEWAL_REVIEW_OPENED"
    RENEWAL_APPROVED_LIMITED = "RENEWAL_APPROVED_LIMITED"
    INCIDENT_NO_ACTION = "INCIDENT_NO_ACTION"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    ROLLBACK_COMPLETED = "ROLLBACK_COMPLETED"
    RETIREMENT_REQUIRED = "RETIREMENT_REQUIRED"
    RETIREMENT_COMPLETED = "RETIREMENT_COMPLETED"
    REOPENED_PAPER_READY = "REOPENED_PAPER_READY"
    RESUME_REJECTED = "RESUME_REJECTED"
    RESUME_READY = "RESUME_READY"
    NOOP_ALREADY_COMMITTED = "NOOP_ALREADY_COMMITTED"


@unique
class ApprovalAction(StrEnum):
    PROMOTE = "limited_promotion"
    RENEW = "limited_renewal"
    ROLLBACK = "rollback"
    RETIRE = "retirement"


class OperatorApprovalBody(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.approval.1"]
    approval_id: str
    operator_id: str
    approved_at: AwareDatetime
    action: ApprovalAction
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    from_state: LifecycleState
    to_state: LifecycleState
    policy_version: str | None
    initial_weight: Decimal6 | None
    approval_start_session_ordinal: Annotated[int, Field(strict=True, ge=1)] | None
    approval_duration_market_sessions: Annotated[int, Field(strict=True, ge=1, le=60)] | None
    rollback_policy_version: str | None
    rollback_policy_hash: ContentHash | None
    prior_history_hash: ContentHash | None
    reason: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def action_shape(self) -> Self:
        promotion = (self.policy_version, self.initial_weight, self.approval_start_session_ordinal, self.approval_duration_market_sessions, self.rollback_policy_version, self.rollback_policy_hash)
        match self.action:  # noqa: MATCH_OK - all ApprovalAction members are handled
            case ApprovalAction.PROMOTE:
                if self.from_state is not LifecycleState.PAPER_READY or self.to_state is not LifecycleState.LIMITED_PRODUCTION or any(value is None for value in promotion):
                    raise ContractInvariantError("promotion approval shape mismatch")
            case ApprovalAction.RENEW:
                if self.from_state is not LifecycleState.RENEWAL_REVIEW or self.to_state is not LifecycleState.LIMITED_PRODUCTION or any(value is None for value in promotion):
                    raise ContractInvariantError("renewal approval shape mismatch")
            case ApprovalAction.ROLLBACK:
                if self.to_state is not LifecycleState.ROLLED_BACK or self.rollback_policy_version is None or self.rollback_policy_hash is None:
                    raise ContractInvariantError("rollback approval shape mismatch")
            case ApprovalAction.RETIRE:
                if self.to_state is not LifecycleState.RETIRED:
                    raise ContractInvariantError("retirement approval shape mismatch")
        return self


class OperatorApproval(OperatorApprovalBody):
    approval_hash: ContentHash

    @model_validator(mode="after")
    def hash_bound(self) -> Self:
        body = OperatorApprovalBody.model_validate(self.model_dump(mode="json", exclude={"approval_hash"}))
        raw = JsonBoundary.model_validate(body.model_dump(mode="json")).root
        if self.approval_hash != canonical_hash(raw):
            raise ContractInvariantError("operator approval hash mismatch")
        return self


class LifecycleDecision(BoundaryModel):
    result_code: LifecycleResultCode
    prior_state: LifecycleState
    next_state: LifecycleState
    reasons: tuple[str, ...]
    audit_failure: bool = False


class LifecycleInput(BoundaryModel):
    schema_version: Literal["v6.consensus_lifecycle.input.1"]
    operation_id: str
    idempotency_key: str
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    current_session_ordinal: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: AwareDatetime
    policy_registry: PolicyVersionRegistry
