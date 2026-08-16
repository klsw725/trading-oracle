from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json
from src.v11.ledger import append_event
from src.v11.models import EventType, LedgerEvent, ReplayState
from src.v11.replay import replay

from .approvals import Approval, ApprovalPurpose, ApprovalRequest, verify_approval
from .contract import StrictModel, V15Failure, V15FailureCode
from .liquidation import KillExecution, ScopeLevel, verify_execution
from .upstream import PolicyIdentity


@unique
class KillKind(StrEnum):
    LOSS = "loss"
    OPERATION = "operation"


class AccountRecovery(StrictModel):
    account_namespace: str
    events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    post_recovery_state: ReplayState
    reset_event_hash: str
    reconciliation_event_hash: str
    result_hash: str


class RecoveryEvidence(StrictModel):
    schema_version: Literal["v15.recovery_evidence.4"]
    kind: KillKind
    incident_hash: str
    incident_session: date
    recovery_session: date
    calendar_hash: str
    original_identity: PolicyIdentity
    current_identity: PolicyIdentity
    execution_hash: str
    actual_replay_hash: str
    accounts: Annotated[tuple[AccountRecovery, ...], Field(strict=False)]
    approval: Approval | None
    recovery_hash: str


def build_account_recoveries(
    execution: KillExecution, recovery_session: date,
) -> tuple[AccountRecovery, ...]:
    results: list[AccountRecovery] = []
    for account in execution.accounts:
        manifest = account.events[-1].experiment_manifest_hash
        events = account.events
        for index, position in enumerate(account.after_state.positions):
            entity = f"{account.account_namespace}:recovery-close:"
            entity += f"{position.symbol}:{recovery_session}"
            occurred_at = datetime.combine(recovery_session,
                time(8, 59, index), UTC)
            events = append_event(events, EventType.SIGNAL_OBSERVED, entity,
                occurred_at, {"decision_id": entity,
                    "semantic_key": "recovery_close_signal"}, manifest)
            events = append_event(events, EventType.ORDER_INTENDED, entity,
                occurred_at, {"decision_id": entity,
                    "semantic_key": "recovery_close_intent"}, manifest)
            events = append_event(events, EventType.RISK_CHECKED, entity,
                occurred_at, {"accepted": True,
                    "semantic_key": "recovery_close_risk"}, manifest)
            events = append_event(events, EventType.ORDER_ACCEPTED, entity,
                occurred_at, {"quantity": position.quantity,
                    "semantic_key": "recovery_close_accepted"}, manifest)
            events = append_event(events, EventType.FILL_COMPLETE, entity,
                occurred_at, {"quantity": position.quantity,
                    "semantic_key": "recovery_close_fill"}, manifest)
            events = append_event(events, EventType.POSITION_UPDATED, entity,
                occurred_at, {"cash_delta": "0", "symbol": position.symbol,
                    "side": position.side.value, "sector": position.sector,
                    "quantity": 0, "mark_price": position.mark_price,
                    "semantic_key": "recovery_close_position"}, manifest)
            events = append_event(events, EventType.RECONCILED, entity,
                occurred_at, {"halted": True,
                    "semantic_key": "recovery_close_reconciled"}, manifest)
        reset_entity = events[-1].entity_id
        clear_entity = f"{account.account_namespace}:clear:{recovery_session}"
        occurred_at = datetime.combine(recovery_session, time(9, 0), UTC)
        events = append_event(events, EventType.SESSION_CLOSED,
            reset_entity, occurred_at,
            {"reset": True, "semantic_key": "next_session_reset"}, manifest)
        reset_hash = str(events[-1].event_hash)
        events = append_event(events, EventType.SIGNAL_OBSERVED, clear_entity,
            occurred_at, {"decision_id": clear_entity,
                "semantic_key": "recovery_signal"}, manifest)
        events = append_event(events, EventType.ORDER_INTENDED, clear_entity,
            occurred_at, {"decision_id": clear_entity,
                "semantic_key": "recovery_intent"}, manifest)
        events = append_event(events, EventType.RISK_CHECKED, clear_entity,
            occurred_at, {"accepted": False,
                "semantic_key": "recovery_risk"}, manifest)
        events = append_event(events, EventType.ORDER_CANCELLED, clear_entity,
            occurred_at, {"reason": "recovery_clear",
                "semantic_key": "recovery_cancel"}, manifest)
        events = append_event(events, EventType.RECONCILED, clear_entity,
            occurred_at, {"halted": False, "reconciliation_clear": True,
                "semantic_key": "reconciliation_clear"}, manifest)
        state = replay(events, account.initial_cash)
        draft = AccountRecovery(account_namespace=account.account_namespace,
            events=events, post_recovery_state=state,
            reset_event_hash=reset_hash,
            reconciliation_event_hash=str(events[-1].event_hash),
            result_hash="")
        results.append(draft.model_copy(update={"result_hash": canonical_hash(
            model_json(draft))}))
    return tuple(results)


def recovery_replay_hash(accounts: tuple[AccountRecovery, ...]) -> str:
    return canonical_hash([model_json(item.post_recovery_state)
        for item in accounts])


def recover(
    evidence: RecoveryEvidence,
    expected_next_session: date,
    execution: KillExecution,
) -> Literal["recovered"]:
    verify_execution(execution)
    draft = evidence.model_copy(update={"recovery_hash": ""})
    if evidence.recovery_hash != canonical_hash(model_json(draft)) \
            or evidence.recovery_session != expected_next_session \
            or evidence.execution_hash != execution.execution_hash \
            or tuple(item.account_namespace for item in evidence.accounts) \
                != tuple(item.account_namespace for item in execution.accounts) \
            or evidence.actual_replay_hash != recovery_replay_hash(
                evidence.accounts):
        raise V15Failure(V15FailureCode.RECOVERY_BLOCKED, "replay")
    for account, killed in zip(evidence.accounts, execution.accounts, strict=True):
        state = replay(account.events, killed.initial_cash)
        account_draft = account.model_copy(update={"result_hash": ""})
        if account.events[:len(killed.events)] != killed.events \
                or state != account.post_recovery_state \
                or state.halted or state.positions or state.open_intents \
                or account.result_hash != canonical_hash(model_json(account_draft)) \
                or account.reset_event_hash != str(account.events[-6].event_hash) \
                or account.reconciliation_event_hash \
                    != str(account.events[-1].event_hash):
            raise V15Failure(V15FailureCode.RECOVERY_BLOCKED,
                account.account_namespace)
    match evidence.kind:  # noqa: MATCH_OK - KillKind exhaustively covered
        case KillKind.LOSS:
            if evidence.approval is not None:
                raise V15Failure(V15FailureCode.RECOVERY_BLOCKED, "loss_approval")
        case KillKind.OPERATION:
            if evidence.approval is None:
                raise V15Failure(V15FailureCode.RECOVERY_BLOCKED, "approval")
            match execution.scope.level:  # noqa: MATCH_OK - approved scopes covered
                case ScopeLevel.SYMBOL:
                    reason = "symbol recovery"
                case ScopeLevel.MARKET:
                    reason = "market recovery"
                case ScopeLevel.GLOBAL:
                    reason = "global recovery"
                case ScopeLevel.ARM:
                    raise V15Failure(V15FailureCode.RECOVERY_BLOCKED,
                        "arm_operation_recovery")
            request = ApprovalRequest(schema_version="v15.approval_request.3",
                previous_identity=evidence.original_identity,
                current_identity=evidence.current_identity,
                effective_session=evidence.recovery_session,
                purpose=ApprovalPurpose.RECOVERY,
                reason=reason,
                data_exceptions=())
            verify_approval(evidence.approval, request)
    return "recovered"
