from __future__ import annotations

import re
from typing import Final, Protocol

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash
from src.v8.approval_ledger import build_approval_artifact
from src.v8.approval_models import (
    ApprovalContractError,
    ApprovalErrorCode,
    ApprovalFixture,
    ApprovalStatus,
    BrokerDryRunResponse,
    CompileApprovalResult,
    ProposedOrder,
)
from src.v8.identity import deterministic_id, model_json


_HASH: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_KEYS: Final = frozenset(
    {
        "access_token",
        "account_number",
        "broker_order_id",
        "client_secret",
        "live_order_id",
        "state",
        "stage",
    }
)
_REQUIRED_CHECKS: Final = frozenset(
    {
        "intent_matches_recommendation",
        "quote_is_fresh",
        "notional_under_operator_limit",
        "no_live_destination_visible",
    }
)


class BrokerValidationCapability(Protocol):
    validation_available: bool

    def validate(self, fixture: ApprovalFixture) -> JsonValue: ...


def _forbidden_keys(value: JsonValue) -> tuple[str, ...]:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            own = tuple(sorted(_FORBIDDEN_KEYS.intersection(record)))
            return own + tuple(
                key for child in record.values() for key in _forbidden_keys(child)
            )
        case list() as items:
            return tuple(key for child in items for key in _forbidden_keys(child))
        case None | bool() | int() | float() | str():
            return ()


def proposal_seed(order: ProposedOrder) -> JsonValue:
    return {
        "schema_version": order.schema_version,
        "paper_order_id": order.paper_order_id,
        "ticker": order.ticker,
        "side": order.side,
        "order_type": order.order_type,
        "quantity": str(order.quantity),
        "limit_price": str(order.limit_price) if order.limit_price is not None else None,
        "quote_id": order.quote_ref.quote_id,
        "quote_as_of": order.quote_ref.quote_as_of.isoformat(),
        "idempotency_key": order.idempotency_key,
    }


def request_seed(fixture: ApprovalFixture) -> JsonValue:
    order = fixture.proposed_order
    decision = fixture.approval_decision
    return {
        "proposal": proposal_seed(order),
        "approver": decision.approved_by,
        "approved_role": decision.approved_role,
    }


def rebuild_approval_identities(fixture: ApprovalFixture) -> ApprovalFixture:
    proposed_id = deterministic_id("aprop_v8_", proposal_seed(fixture.proposed_order))
    checklist_id = deterministic_id(
        "achk_v8_",
        {
            "proposed_order_id": proposed_id,
            "checked_at": fixture.checklist.checked_at.isoformat(),
            "items": [model_json(item) for item in fixture.checklist.items],
        },
    )
    proposed = fixture.proposed_order.model_copy(
        update={"proposed_order_id": proposed_id, "checklist_id": checklist_id}
    )
    checklist = fixture.checklist.model_copy(update={"checklist_id": checklist_id})
    decision_id = deterministic_id(
        "adec_v8_",
        {
            "proposed_order_id": proposed_id,
            "approved_by": fixture.approval_decision.approved_by,
            "approved_at": fixture.approval_decision.approved_at.isoformat(),
            "idempotency_key": proposed.idempotency_key,
        },
    )
    decision = fixture.approval_decision.model_copy(
        update={"approval_decision_id": decision_id}
    )
    request_id = deterministic_id(
        "adreq_v8_",
        {
            "approval_decision_id": decision_id,
            "requested_at": fixture.dry_run_request.requested_at.isoformat(),
            "destination": proposed.destination,
            "idempotency_key": proposed.idempotency_key,
        },
    )
    request = fixture.dry_run_request.model_copy(
        update={"dry_run_request_id": request_id, "destination": proposed.destination}
    )
    response = fixture.broker_dry_run_response
    if response is not None:
        response_seed = model_json(
            response.model_copy(update={"dry_run_request_id": request_id}),
            exclude={"dry_run_response_id"},
        )
        response = response.model_copy(
            update={
                "dry_run_request_id": request_id,
                "dry_run_response_id": deterministic_id("adry_v8_", response_seed),
            }
        )
    return fixture.model_copy(
        update={
            "proposed_order": proposed,
            "checklist": checklist,
            "approval_decision": decision,
            "dry_run_request": request,
            "broker_dry_run_response": response,
        }
    )


def _failure(
    status: ApprovalStatus, code: ApprovalErrorCode
) -> CompileApprovalResult:
    return CompileApprovalResult(status, None, code)


def _validate_lifecycle(fixture: ApprovalFixture) -> CompileApprovalResult | None:
    order = fixture.proposed_order
    decision = fixture.approval_decision
    request = fixture.dry_run_request
    quote = order.quote_ref
    times = (
        quote.quote_as_of,
        quote.quote_expires_at,
        fixture.checklist.checked_at,
        decision.approved_at,
        request.requested_at,
        order.approval_expires_at,
    )
    if any(value.tzinfo is None for value in times):
        return _failure("proposed", ApprovalErrorCode.MALFORMED_INPUT)
    if _HASH.fullmatch(quote.source_hash) is None or quote.source_hash == "sha256:" + "0" * 64:
        return _failure("dry_run_failed", ApprovalErrorCode.DIRTY_INPUT)
    if decision.approval_status != "approved":
        return _failure("rejected", ApprovalErrorCode.PERMISSION_DENIED)
    checked = {
        item.item
        for item in fixture.checklist.items
        if item.result in {"checked", "not_applicable"}
    }
    if not _REQUIRED_CHECKS.issubset(checked):
        return _failure("proposed", ApprovalErrorCode.CHECKLIST_INCOMPLETE)
    if decision.approver_is_proposer or decision.approved_by == order.permission_context.proposed_by:
        return _failure("checklisted", ApprovalErrorCode.SELF_APPROVAL_FORBIDDEN)
    if decision.approved_role != order.permission_context.eligible_approver_role:
        return _failure("checklisted", ApprovalErrorCode.PERMISSION_DENIED)
    if order.estimated_notional > order.permission_context.max_notional:
        return _failure("checklisted", ApprovalErrorCode.PERMISSION_DENIED)
    if order.limit_price is not None and order.estimated_notional != order.quantity * order.limit_price:
        return _failure("proposed", ApprovalErrorCode.MALFORMED_INPUT)
    if decision.idempotency_key != order.idempotency_key or request.idempotency_key != order.idempotency_key:
        return _failure("proposed", ApprovalErrorCode.IDEMPOTENCY_CONFLICT)
    if decision.approved_at > order.approval_expires_at or request.requested_at > order.approval_expires_at:
        return _failure("expired", ApprovalErrorCode.APPROVAL_EXPIRED)
    approval_age = (decision.approved_at - quote.quote_as_of).total_seconds()
    request_age = (request.requested_at - quote.quote_as_of).total_seconds()
    if (
        decision.approved_at > quote.quote_expires_at
        or request.requested_at > quote.quote_expires_at
        or approval_age > quote.max_quote_age_seconds
        or request_age > quote.max_quote_age_seconds
    ):
        return _failure("expired", ApprovalErrorCode.STALE_QUOTE)
    return None


def compile_approval_fixture(
    value: JsonValue, broker: BrokerValidationCapability | None = None
) -> CompileApprovalResult:
    forbidden = _forbidden_keys(value)
    if forbidden:
        code = (
            ApprovalErrorCode.FORBIDDEN_FIELD_PRESENT
            if any(key not in {"state", "stage"} for key in forbidden)
            else ApprovalErrorCode.MALFORMED_INPUT
        )
        status: ApprovalStatus = "dry_run_failed" if code is ApprovalErrorCode.FORBIDDEN_FIELD_PRESENT else "proposed"
        return _failure(status, code)
    try:
        fixture = rebuild_approval_identities(ApprovalFixture.model_validate(value))
    except (ValidationError, ApprovalContractError):
        return _failure("proposed", ApprovalErrorCode.MALFORMED_INPUT)
    lifecycle_error = _validate_lifecycle(fixture)
    if lifecycle_error is not None:
        return lifecycle_error
    response = fixture.broker_dry_run_response
    if response is None:
        if broker is None or not broker.validation_available:
            return _failure(
                "dry_run_failed", ApprovalErrorCode.BROKER_VALIDATION_UNAVAILABLE
            )
        try:
            response = BrokerDryRunResponse.model_validate(broker.validate(fixture))
        except (ValidationError, ApprovalContractError):
            return _failure("dry_run_failed", ApprovalErrorCode.MALFORMED_INPUT)
        fixture = rebuild_approval_identities(
            fixture.model_copy(update={"broker_dry_run_response": response})
        )
        response = fixture.broker_dry_run_response
        assert response is not None
    if response.live_submission or not response.forbidden_fields_absent:
        return _failure(
            "dry_run_failed", ApprovalErrorCode.MISLEADING_SUCCESS_OUTPUT
        )
    if not response.would_accept:
        return _failure("dry_run_failed", ApprovalErrorCode.MISLEADING_SUCCESS_OUTPUT)
    source_hash = canonical_hash(value)
    artifact = build_approval_artifact(
        fixture, source_hash, canonical_hash(request_seed(fixture))
    )
    return CompileApprovalResult("dry_run_passed", artifact)
