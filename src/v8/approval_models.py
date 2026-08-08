from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, Literal, override

from pydantic import BeforeValidator, Field, model_validator

from src.v4.models import JsonValue
from src.v8.event_models import FrozenModel, Side

type ApprovalStatus = Literal[
    "proposed",
    "checklisted",
    "approved",
    "rejected",
    "expired",
    "dry_run_requested",
    "dry_run_passed",
    "dry_run_failed",
]


@unique
class ApprovalErrorCode(StrEnum):
    MALFORMED_INPUT = "malformed_input"
    STALE_QUOTE = "stale_quote"
    APPROVAL_EXPIRED = "approval_expired"
    CHECKLIST_INCOMPLETE = "checklist_incomplete"
    PERMISSION_DENIED = "permission_denied"
    SELF_APPROVAL_FORBIDDEN = "self_approval_forbidden"
    FORBIDDEN_FIELD_PRESENT = "forbidden_field_present"
    DIRTY_INPUT = "dirty_input"
    MISLEADING_SUCCESS_OUTPUT = "misleading_success_output"
    BROKER_VALIDATION_UNAVAILABLE = "broker_validation_unavailable"
    BROKER_REJECTED = "broker_rejected"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    REPEATED_INTERRUPTION = "repeated_interruption"
    BROKEN_HASH_CHAIN = "broken_hash_chain"


@dataclass(frozen=True, slots=True)
class ApprovalContractError(Exception):
    code: ApprovalErrorCode
    detail: str
    approval_status: ApprovalStatus = "proposed"

    @override
    def __str__(self) -> str:
        return f"{self.code.value}: {self.detail}"


def _decimal_text(value: JsonValue) -> str:
    match value:  # noqa: MATCH_OK - JsonValue variants are fully handled
        case str() as text:
            return text
        case None | bool() | int() | float() | list() | dict():
            raise ApprovalContractError(
                ApprovalErrorCode.MALFORMED_INPUT,
                "decimal fields require JSON strings",
            )


type DecimalText = Annotated[Decimal, BeforeValidator(_decimal_text)]


class QuoteRef(FrozenModel):
    quote_id: str = Field(min_length=1)
    quote_as_of: datetime
    quote_expires_at: datetime
    max_quote_age_seconds: int = Field(gt=0)
    source_hash: str


class PermissionContext(FrozenModel):
    proposed_by: str = Field(min_length=1)
    eligible_approver_role: str = Field(min_length=1)
    max_notional: DecimalText = Field(gt=0)


class ProposedOrder(FrozenModel):
    schema_version: Literal["v8.operator_approval_dry_run.proposed_order.1"]
    proposed_order_id: str
    paper_order_id: str = Field(pattern=r"^pord_v8_")
    paper_recommendation_id: str = Field(pattern=r"^prec_v8_")
    ticker: str = Field(min_length=1)
    side: Side
    order_type: Literal["market", "limit"]
    quantity: DecimalText = Field(gt=0)
    limit_price: DecimalText | None = Field(default=None, gt=0)
    currency: Literal["KRW", "USD"]
    estimated_notional: DecimalText = Field(gt=0)
    destination: Literal["broker_dry_run", "internal_dry_run"]
    quote_ref: QuoteRef
    checklist_id: str = Field(pattern=r"^achk_v8_")
    idempotency_key: str = Field(min_length=1)
    approval_expires_at: datetime
    permission_context: PermissionContext
    forbidden_fields_absent: Literal[True]

    @model_validator(mode="after")
    def validate_order_price(self) -> ProposedOrder:
        if self.order_type == "limit" and self.limit_price is None:
            raise ApprovalContractError(
                ApprovalErrorCode.MALFORMED_INPUT, "limit order requires limit_price"
            )
        if self.order_type == "market" and "limit_price" in self.model_fields_set:
            raise ApprovalContractError(
                ApprovalErrorCode.MALFORMED_INPUT,
                "market order must omit limit_price",
            )
        return self


class ChecklistItem(FrozenModel):
    item: Literal[
        "intent_matches_recommendation",
        "quote_is_fresh",
        "notional_under_operator_limit",
        "cash_or_position_reviewed",
        "stop_loss_visible",
        "no_live_destination_visible",
        "risk_notice_acknowledged",
    ]
    result: Literal["checked", "rejected", "not_applicable"]
    rule: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_not_applicable(self) -> ChecklistItem:
        if self.result == "not_applicable" and (self.rule is None or self.reason is None):
            raise ApprovalContractError(
                ApprovalErrorCode.MALFORMED_INPUT,
                "not_applicable checklist item requires rule and reason",
            )
        return self


class OperatorChecklist(FrozenModel):
    checklist_id: str = Field(pattern=r"^achk_v8_")
    checked_at: datetime
    items: tuple[ChecklistItem, ...]


class ApprovalDecision(FrozenModel):
    approval_decision_id: str
    approval_status: Literal["approved", "rejected"]
    approved_by: str
    approved_role: str
    approved_at: datetime
    approver_is_proposer: bool
    idempotency_key: str


class DryRunRequest(FrozenModel):
    dry_run_request_id: str
    requested_at: datetime
    destination: Literal["broker_dry_run", "internal_dry_run"]
    live_submission: Literal[False]
    idempotency_key: str


class BrokerAdapter(FrozenModel):
    name: str
    version: str
    validation_mode: Literal["dry_run", "internal_validation"]


class BrokerDryRunResponse(FrozenModel):
    schema_version: Literal["v8.operator_approval_dry_run.broker_response.1"]
    dry_run_response_id: str
    dry_run_request_id: str
    broker_adapter: BrokerAdapter
    live_submission: bool
    would_accept: bool
    estimated_fee: DecimalText | Literal["not_available"]
    estimated_tax: DecimalText | Literal["not_available"]
    estimated_cash_effect: DecimalText | Literal["not_available"]
    reject_code: str | None = None
    reject_message: str | None = None
    forbidden_fields_absent: bool

    @model_validator(mode="after")
    def validate_rejection(self) -> BrokerDryRunResponse:
        if not self.would_accept and (
            self.reject_code is None or self.reject_message is None
        ):
            raise ApprovalContractError(
                ApprovalErrorCode.MALFORMED_INPUT,
                "rejected response requires code and message",
                "dry_run_failed",
            )
        return self


class ExpectedIndexEntry(FrozenModel):
    idempotency_key: str
    proposed_order_id: str
    approval_decision_id: str
    dry_run_request_id: str
    dry_run_response_id: str
    approval_status: Literal["dry_run_passed"]


class ExpectedApprovalReplay(FrozenModel):
    approval_status: Literal["dry_run_passed"]
    real_order_created: Literal[False]
    portfolio_mutated: Literal[False]
    idempotency_index_entry: ExpectedIndexEntry


class ApprovalFixture(FrozenModel):
    schema_version: Literal["v8.operator_approval_dry_run.prd02.fixture.1"]
    fixture_name: str
    strict_no_real_order: Literal[True]
    forbidden_fields: tuple[str, ...]
    proposed_order: ProposedOrder
    checklist: OperatorChecklist
    approval_decision: ApprovalDecision
    dry_run_request: DryRunRequest
    broker_dry_run_response: BrokerDryRunResponse | None
    expected_after_replay: ExpectedApprovalReplay


class ApprovalRecord(FrozenModel):
    artifact_type: Literal["proposal", "checklist", "decision", "dry_run_request", "dry_run_response"]
    artifact_id: str
    approval_status: ApprovalStatus
    payload: JsonValue
    source_hashes: tuple[str, ...]
    prev_record_hash: str
    record_hash: str


class IdempotencyIndexEntry(FrozenModel):
    idempotency_key: str
    proposal_seed_hash: str
    proposed_order_id: str
    approval_decision_id: str
    dry_run_request_id: str
    dry_run_response_id: str
    approval_status: ApprovalStatus
    response_hash: str


class ApprovalArtifact(FrozenModel):
    schema_version: Literal["v8.operator_approval_dry_run.artifact.1"]
    approval_status: ApprovalStatus
    source_input_hash: str
    proposed_order: ProposedOrder
    checklist: OperatorChecklist
    approval_decision: ApprovalDecision
    dry_run_request: DryRunRequest
    broker_dry_run_response: BrokerDryRunResponse
    records: tuple[ApprovalRecord, ...]
    idempotency_index_entry: IdempotencyIndexEntry
    live_submission: Literal[False]
    would_accept: bool
    real_order_created: Literal[False]
    portfolio_mutated: Literal[False]


@dataclass(frozen=True, slots=True)
class CompileApprovalResult:
    approval_status: ApprovalStatus
    artifact: ApprovalArtifact | None
    error_code: ApprovalErrorCode | None = None


class ApprovalVerificationResult(FrozenModel):
    verification_status: Literal["pass", "fail"]
    approval_status: ApprovalStatus
    errors: tuple[ApprovalErrorCode, ...]
    record_count: int
    live_submission: bool
    would_accept: bool
    real_order_created: bool
    portfolio_mutated: bool
