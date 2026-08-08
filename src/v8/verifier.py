from __future__ import annotations

import re
from decimal import Decimal
from typing import Final

from src.v4.models import canonical_hash
from src.v8.event_models import (
    AccountOpenedEvent,
    CorporateActionEvent,
    FillEvent,
    OrderEvent,
    ReconciledEvent,
)
from src.v8.identity import event_hash, model_json
from src.v8.models import (
    FailureCode,
    PaperLedgerArtifact,
    VerificationContext,
    VerificationResult,
)
from src.v8.replay import position_summaries, replay_events

_HASH: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_LIVE_DESTINATIONS: Final = frozenset({"broker", "toss", "live", "real_account"})
_ERROR_PRIORITY: Final = {
    FailureCode.MISLEADING_SUCCESS_OUTPUT: 0,
    FailureCode.LIVE_STATE_CONTAMINATION: 1,
    FailureCode.REPEATED_INTERRUPTION: 2,
    FailureCode.STALE_STATE: 3,
    FailureCode.DIRTY_WORKTREE: 4,
}


def _structural_errors(artifact: PaperLedgerArtifact) -> list[FailureCode]:
    errors: list[FailureCode] = []
    event_ids: set[str] = set()
    fill_ids: set[str] = set()
    idempotency: dict[str, tuple[str, Decimal, Decimal]] = {}
    orders: dict[str, tuple[str, Decimal, Decimal]] = {}
    previous_hash = "sha256:genesis"
    for event in artifact.events:
        if event.event_id in event_ids:
            errors.append(FailureCode.MALFORMED_INPUT)
        event_ids.add(event.event_id)
        if (
            not event.paper_namespace.startswith("paper:")
            or event.paper_namespace != artifact.paper_namespace
            or not event.event_id.startswith("pevt_v8_")
        ):
            errors.append(FailureCode.LIVE_STATE_CONTAMINATION)
        if (
            event.occurred_at.tzinfo is None
            or event.recorded_at.tzinfo is None
            or event.recorded_at < event.occurred_at
        ):
            errors.append(FailureCode.MALFORMED_INPUT)
        if (
            event.prev_event_hash != previous_hash
            or _HASH.fullmatch(event.event_hash) is None
            or event_hash(event) != event.event_hash
        ):
            errors.append(FailureCode.BROKEN_HASH_CHAIN)
        previous_hash = event.event_hash
        match event:  # noqa: MATCH_OK - only orders and fills own idempotency
            case OrderEvent(payload=payload):
                seed = (payload.side, payload.quantity, payload.limit_price)
                prior = idempotency.get(payload.idempotency_key)
                if prior is not None and prior != seed:
                    errors.append(FailureCode.IDEMPOTENCY_CONFLICT)
                idempotency[payload.idempotency_key] = seed
                orders[payload.paper_order_id] = seed
                if payload.destination != "paper_engine":
                    errors.append(FailureCode.LIVE_STATE_CONTAMINATION)
            case FillEvent(payload=payload):
                if payload.paper_fill_id in fill_ids:
                    errors.append(FailureCode.REPEATED_INTERRUPTION)
                fill_ids.add(payload.paper_fill_id)
                order = orders.get(payload.paper_order_id)
                if order is None or order[:2] != (payload.side, payload.quantity):
                    errors.append(FailureCode.MALFORMED_INPUT)
                elif (
                    payload.side == "BUY" and payload.fill_price > order[2]
                ) or (
                    payload.side == "SELL" and payload.fill_price < order[2]
                ):
                    errors.append(FailureCode.MALFORMED_INPUT)
            case _:
                continue
    return errors


def _context_errors(
    artifact: PaperLedgerArtifact, context: VerificationContext
) -> list[FailureCode]:
    errors: list[FailureCode] = []
    if context.declared_input_hash != context.observed_input_hash:
        errors.append(FailureCode.DIRTY_WORKTREE)
    for event in artifact.events:
        match event:  # noqa: MATCH_OK - only sourced mutations have a cutoff
            case FillEvent() if event.occurred_at > context.replay_cutoff:
                errors.append(FailureCode.STALE_STATE)
            case CorporateActionEvent(payload=payload) if payload.effective_at > context.replay_cutoff:
                errors.append(FailureCode.STALE_STATE)
            case _:
                continue
    return errors


def _decimal_strings(values: dict[str, Decimal]) -> dict[str, str]:
    return {currency: f"{amount:.2f}" for currency, amount in sorted(values.items())}


def verify_artifact(
    artifact: PaperLedgerArtifact, context: VerificationContext
) -> VerificationResult:
    errors = _structural_errors(artifact) + _context_errors(artifact, context)
    snapshot = replay_events(artifact.events, artifact.fee_model)
    errors.extend(snapshot.errors)
    positions = position_summaries(snapshot)
    opening_cash = {
        balance.currency: balance.cash for balance in artifact.starting_balances
    }
    match artifact.events[0]:  # noqa: MATCH_OK - genesis must be account-opened
        case AccountOpenedEvent(payload=payload) if payload.cash != opening_cash:
            errors.append(FailureCode.CASH_MISMATCH)
        case AccountOpenedEvent():
            pass
        case _:
            errors.append(FailureCode.MALFORMED_INPUT)
    if snapshot.cash != artifact.expected_after_replay.cash:
        errors.append(FailureCode.CASH_MISMATCH)
    if positions != artifact.expected_after_replay.positions:
        errors.append(FailureCode.POSITION_MISMATCH)
    if snapshot.fills != artifact.expected_after_replay.fills:
        errors.append(FailureCode.FEE_MISMATCH)
    positions_hash = canonical_hash([model_json(position) for position in positions])
    for event in artifact.events:
        match event:  # noqa: MATCH_OK - only reconciliation stores this summary hash
            case ReconciledEvent(payload=payload):
                if payload.replayed_positions_hash != positions_hash:
                    errors.append(FailureCode.POSITION_MISMATCH)
            case _:
                continue
    broker_destinations = tuple(
        event.payload.destination
        for event in artifact.events
        if isinstance(event, OrderEvent)
        and event.payload.destination in _LIVE_DESTINATIONS
    )
    live_orders = tuple(
        event.entity_ref.entity_id
        for event in artifact.events
        if event.entity_ref.entity_id.startswith("live")
    )
    if not artifact.paper_namespace.startswith("paper:") or broker_destinations or live_orders:
        errors.append(FailureCode.LIVE_STATE_CONTAMINATION)
    errors = list(dict.fromkeys(errors))
    if context.claimed_success and errors:
        errors.insert(0, FailureCode.MISLEADING_SUCCESS_OUTPUT)
    errors.sort(key=lambda code: _ERROR_PRIORITY.get(code, 10))
    state = "blocked" if FailureCode.STALE_STATE in errors else "fail" if errors else "pass"
    return VerificationResult(
        state=state,
        errors=tuple(errors),
        cash=_decimal_strings(snapshot.cash),
        positions=positions,
        fills=snapshot.fills,
        last_event_hash=artifact.events[-1].event_hash,
        forbidden_keys=(),
        broker_destinations=broker_destinations,
        live_orders=live_orders,
    )
