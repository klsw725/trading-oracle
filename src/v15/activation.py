from __future__ import annotations

from .approvals import (
    Approval,
    ApprovalPurpose,
    ApprovalRequest,
    approve,
    consume_manual_approval,
    derive_change,
    ChangeKind,
)
from .contract import V15Failure, V15FailureCode
from .operation_fixture import OperationSourceFixture
from .operation_models import MarketOperation
from .upstream import UpstreamEvidence


def activation_request(
    market: MarketOperation,
    source: OperationSourceFixture,
    upstream: UpstreamEvidence,
) -> ApprovalRequest:
    exceptions = tuple(item for item in source.data_exceptions
        if item.market == market.market)
    if any(item.effective_session
            != market.schedule.qualification_sessions[0]
            or item.source_hash != market.schedule.calendar_hash
            for item in exceptions):
        raise V15Failure(V15FailureCode.APPROVAL_MISMATCH,
            f"data_exception:{market.market}")
    return ApprovalRequest(schema_version="v15.approval_request.3",
        previous_identity=upstream.policy,
        current_identity=upstream.policy,
        effective_session=market.schedule.qualification_sessions[0],
        purpose=ApprovalPurpose.ACTIVATION,
        reason=f"verified v14 gates for {market.market}",
        data_exceptions=exceptions)


def approve_activation(
    market: MarketOperation,
    source: OperationSourceFixture,
    upstream: UpstreamEvidence,
) -> Approval:
    request = activation_request(market, source, upstream)
    if derive_change(request) is ChangeKind.ROUTINE:
        return approve(request, "automation", upstream.gate_available_at)
    return consume_manual_approval(source.manual_approvals, request)
