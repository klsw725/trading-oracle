from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel, V15Failure, V15FailureCode
from .upstream import PolicyIdentity


@unique
class ChangeKind(StrEnum):
    ROUTINE = "routine"
    POLICY_CHANGE = "policy_change"
    DATA_EXCEPTION = "data_exception"


@unique
class ApprovalPurpose(StrEnum):
    ACTIVATION = "activation"
    RECOVERY = "recovery"


@unique
class DataExceptionKind(StrEnum):
    SOURCE_FALLBACK = "source_fallback"
    DATA_EXCEPTION = "data_exception"


class DataExceptionEvidence(StrictModel):
    schema_version: Literal["v15.data_exception.1"]
    kind: DataExceptionKind
    market: Literal["KR", "US"]
    effective_session: date
    source_hash: str
    detail_hash: str
    evidence_hash: str


class ApprovalRequest(StrictModel):
    schema_version: Literal["v15.approval_request.3"]
    previous_identity: PolicyIdentity
    current_identity: PolicyIdentity
    effective_session: date
    purpose: ApprovalPurpose
    reason: str
    data_exceptions: Annotated[tuple[DataExceptionEvidence, ...],
        Field(strict=False)]


class ApprovalBody(StrictModel):
    schema_version: Literal["v15.approval.3"]
    previous_identity: PolicyIdentity
    current_identity: PolicyIdentity
    effective_session: date
    purpose: ApprovalPurpose
    change_kind: ChangeKind
    reason: str
    data_exceptions: Annotated[tuple[DataExceptionEvidence, ...],
        Field(strict=False)]
    reviewer: str
    approved_at: datetime
    automatic: bool


class Approval(ApprovalBody):
    approval_hash: str


def derive_change(request: ApprovalRequest) -> ChangeKind:
    _verify_data_exceptions(request.data_exceptions)
    if request.previous_identity != request.current_identity:
        return ChangeKind.POLICY_CHANGE
    if request.data_exceptions:
        return ChangeKind.DATA_EXCEPTION
    return ChangeKind.ROUTINE


def seal_data_exception(
    evidence: DataExceptionEvidence,
) -> DataExceptionEvidence:
    draft = evidence.model_copy(update={"evidence_hash": ""})
    return draft.model_copy(update={"evidence_hash": canonical_hash(
        model_json(draft))})


def approve(
    request: ApprovalRequest, reviewer: str, approved_at: datetime
) -> Approval:
    change = derive_change(request)
    automatic = change is ChangeKind.ROUTINE \
        and request.purpose is ApprovalPurpose.ACTIVATION
    if automatic != (reviewer == "automation") or not request.reason.strip() \
            or approved_at.date() > request.effective_session:
        raise V15Failure(V15FailureCode.APPROVAL_REQUIRED,
            request.purpose.value)
    body = ApprovalBody(schema_version="v15.approval.3",
        previous_identity=request.previous_identity,
        current_identity=request.current_identity,
        effective_session=request.effective_session, purpose=request.purpose,
        change_kind=change, reason=request.reason,
        data_exceptions=request.data_exceptions, reviewer=reviewer,
        approved_at=approved_at, automatic=automatic)
    return Approval(schema_version=body.schema_version,
        previous_identity=body.previous_identity,
        current_identity=body.current_identity,
        effective_session=body.effective_session, purpose=body.purpose,
        change_kind=body.change_kind, reason=body.reason,
        data_exceptions=body.data_exceptions,
        reviewer=body.reviewer, approved_at=body.approved_at,
        automatic=body.automatic,
        approval_hash=canonical_hash(model_json(body)))


def verify_approval(approval: Approval, request: ApprovalRequest) -> None:
    body = ApprovalBody.model_validate(approval.model_dump(
        exclude={"approval_hash"}))
    if approval.approval_hash != canonical_hash(model_json(body)) \
            or body.previous_identity != request.previous_identity \
            or body.current_identity != request.current_identity \
            or body.effective_session != request.effective_session \
            or body.purpose is not request.purpose \
            or body.change_kind is not derive_change(request) \
            or body.reason != request.reason \
            or body.data_exceptions != request.data_exceptions \
            or body.automatic != (body.change_kind is ChangeKind.ROUTINE
                and body.purpose is ApprovalPurpose.ACTIVATION) \
            or body.automatic != (body.reviewer == "automation") \
            or not body.reason.strip() \
            or body.approved_at.date() > body.effective_session:
        raise V15Failure(V15FailureCode.APPROVAL_MISMATCH,
            approval.approval_hash)


def consume_manual_approval(
    approvals: tuple[Approval, ...], request: ApprovalRequest,
) -> Approval:
    matched = tuple(item for item in approvals
        if item.purpose is request.purpose
        and item.effective_session == request.effective_session
        and item.reason == request.reason)
    if len(matched) != 1:
        raise V15Failure(V15FailureCode.APPROVAL_REQUIRED,
            request.purpose.value)
    approval = matched[0]
    verify_approval(approval, request)
    if approval.automatic:
        raise V15Failure(V15FailureCode.APPROVAL_REQUIRED,
            approval.approval_hash)
    return approval


def verify_manual_approval_artifact(approval: Approval) -> None:
    body = ApprovalBody.model_validate(approval.model_dump(
        exclude={"approval_hash"}))
    if approval.approval_hash != canonical_hash(model_json(body)) \
            or approval.automatic or approval.reviewer == "automation":
        raise V15Failure(V15FailureCode.APPROVAL_MISMATCH,
            approval.approval_hash)


def verify_manual_approval_consumption(
    available: tuple[Approval, ...], consumed: tuple[Approval, ...],
) -> None:
    available_hashes = tuple(sorted(item.approval_hash for item in available))
    consumed_hashes = tuple(sorted(item.approval_hash for item in consumed))
    if available_hashes != consumed_hashes:
        raise V15Failure(V15FailureCode.APPROVAL_MISMATCH,
            "manual_approval_inventory")


def _verify_data_exceptions(
    evidence: tuple[DataExceptionEvidence, ...],
) -> None:
    if len({item.evidence_hash for item in evidence}) != len(evidence) \
            or any(seal_data_exception(item) != item for item in evidence):
        raise V15Failure(V15FailureCode.APPROVAL_MISMATCH,
            "data_exception")
