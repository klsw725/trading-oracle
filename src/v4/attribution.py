from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from .attribution_models import (
    AttributionEvent,
    CandidateInventoryRecorded,
    CandidateSeen,
    CorrectedBy,
    CorrectionRecorded,
    DenominatorSummary,
    FillId,
    FillRecorded,
    IntegrityRule,
    LedgerId,
    LifecycleEventType,
    LifecycleIntegrityError,
    LifecyclePayload,
    OperatorDecisionRecorded,
    OperatorDecisionState,
    OrderLinked,
    OutcomeMatured,
    PositionClosed,
    TerminalAttribution,
)

from src.v4.models import (
    Action,
    AttributionEventId,
    CandidateId,
    ContentHash,
    IdPrefix,
    JsonValue,
    OrderId,
    PortfolioTradeId,
    RecommendationId,
    canonical_hash,
    deterministic_id,
)

EVENT_VERSION: Final = "v4.phase26.event.1"
GENESIS_HASH: Final = ContentHash("sha256:genesis")

__all__ = (
    "AttributionEvent",
    "AttributionLedger",
    "CandidateInventoryRecorded",
    "CandidateSeen",
    "CorrectedBy",
    "CorrectionRecorded",
    "DenominatorSummary",
    "FillId",
    "FillRecorded",
    "IntegrityRule",
    "LedgerId",
    "LifecycleEventType",
    "LifecycleIntegrityError",
    "OperatorDecisionRecorded",
    "OperatorDecisionState",
    "OrderLinked",
    "OutcomeMatured",
    "PositionClosed",
    "TerminalAttribution",
)


def _event_type(payload: LifecyclePayload) -> LifecycleEventType:
    match payload:  # noqa: MATCH_OK - exhaustive payload union
        case CandidateInventoryRecorded(): return LifecycleEventType.CANDIDATE_INVENTORY_RECORDED
        case CandidateSeen(): return LifecycleEventType.CANDIDATE_SEEN
        case TerminalAttribution(action=Action.CANDIDATE_REJECTED): return LifecycleEventType.CANDIDATE_REJECTED
        case TerminalAttribution(): return LifecycleEventType.RECOMMENDATION_EMITTED
        case OperatorDecisionRecorded(): return LifecycleEventType.OPERATOR_DECISION_RECORDED
        case OrderLinked(): return LifecycleEventType.ORDER_LINKED
        case FillRecorded(): return LifecycleEventType.FILL_RECORDED
        case PositionClosed(): return LifecycleEventType.POSITION_CLOSED
        case OutcomeMatured(): return LifecycleEventType.OUTCOME_MATURED
        case CorrectionRecorded(): return LifecycleEventType.CORRECTION_RECORDED


def _candidate_id(payload: LifecyclePayload) -> CandidateId | None:
    match payload:  # noqa: MATCH_OK - inventory is the only stream-level payload
        case CandidateInventoryRecorded(): return None
        case CandidateSeen() | TerminalAttribution() | OperatorDecisionRecorded() | OrderLinked() | FillRecorded() | PositionClosed() | OutcomeMatured() | CorrectionRecorded(): return payload.candidate_id


def _payload_document(payload: LifecyclePayload) -> JsonValue:
    match payload:  # noqa: MATCH_OK - exhaustive payload union
        case CandidateInventoryRecorded() as value: return {"candidate_ids": list(value.candidate_ids), "candidate_count": value.candidate_count, "inventory_hash": value.inventory_hash}
        case CandidateSeen() as value: return {"candidate_id": value.candidate_id}
        case TerminalAttribution() as value: return {"candidate_id": value.candidate_id, "recommendation_id": value.recommendation_id, "ticker": value.ticker, "action": value.action, "confidence_probability": value.confidence_probability, "horizons": list(value.horizons)}
        case OperatorDecisionRecorded() as value: return {"candidate_id": value.candidate_id, "recommendation_id": value.recommendation_id, "state": value.state}
        case OrderLinked() as value: return {"candidate_id": value.candidate_id, "order_id": value.order_id, "portfolio_trade_id": value.portfolio_trade_id}
        case FillRecorded() as value: return {"candidate_id": value.candidate_id, "order_id": value.order_id, "fill_id": value.fill_id}
        case PositionClosed() as value: return {"candidate_id": value.candidate_id, "portfolio_trade_id": value.portfolio_trade_id}
        case OutcomeMatured() as value: return {"candidate_id": value.candidate_id, "recommendation_id": value.recommendation_id, "horizon": value.horizon}
        case CorrectionRecorded() as value: return {"candidate_id": value.candidate_id, "target_event_id": value.target_event_id, "field_path": value.field_path, "old_value_hash": value.old_value_hash, "new_value": value.new_value, "reason": value.reason, "corrected_by": value.corrected_by}


def _field_value(payload: LifecyclePayload, field_path: str) -> JsonValue:
    value = _payload_document(payload)
    for part in field_path.split("."):
        match value:  # noqa: MATCH_OK - JSON traversal intentionally rejects scalars
            case dict():
                if part not in value: raise LifecycleIntegrityError(IntegrityRule.CORRECTION_TARGET, _candidate_id(payload))
                value = value[part]
            case list():
                try: value = value[int(part)]
                except (ValueError, IndexError) as error: raise LifecycleIntegrityError(IntegrityRule.CORRECTION_TARGET, _candidate_id(payload)) from error
            case _: raise LifecycleIntegrityError(IntegrityRule.CORRECTION_TARGET, _candidate_id(payload))
    return value


def _event_id(ledger_id: LedgerId, event: AttributionEvent) -> AttributionEventId:
    return deterministic_id(IdPrefix.ATTRIBUTION_EVENT, {"entity_ref": _candidate_id(event.payload), "event_type": event.event_type, "event_version": EVENT_VERSION, "ledger_id": ledger_id, "occurred_at": event.occurred_at.isoformat(), "prev_event_hash": event.prev_event_hash})


def _event_hash(event: AttributionEvent) -> ContentHash:
    return canonical_hash({"event_id": event.event_id, "event_type": event.event_type, "event_version": EVENT_VERSION, "occurred_at": event.occurred_at.isoformat(), "recorded_at": event.recorded_at.isoformat(), "prev_event_hash": event.prev_event_hash, "payload": _payload_document(event.payload)})


@dataclass(frozen=True, slots=True)
class AttributionLedger:
    ledger_id: LedgerId
    events: tuple[AttributionEvent, ...] = ()

    def append(self, payload: LifecyclePayload, occurred_at: datetime, recorded_at: datetime) -> "AttributionLedger":
        candidate = _candidate_id(payload)
        if occurred_at.tzinfo is None or recorded_at.tzinfo is None: raise LifecycleIntegrityError(IntegrityRule.TIMEZONE_REQUIRED, candidate)
        previous = self.events[-1].event_hash if self.events else GENESIS_HASH
        draft = AttributionEvent(AttributionEventId(""), _event_type(payload), occurred_at, recorded_at, previous, ContentHash(""), payload)
        identified = replace(draft, event_id=_event_id(self.ledger_id, draft))
        ledger = AttributionLedger(self.ledger_id, (*self.events, replace(identified, event_hash=_event_hash(identified))))
        ledger.validate_chain()
        return ledger

    def validate_chain(self) -> None:
        inventory: CandidateInventoryRecorded | None = None; seen: set[CandidateId] = set(); terminals: dict[CandidateId, Action] = {}; recommendations: dict[CandidateId, RecommendationId | None] = {}; operators: set[CandidateId] = set(); orders: dict[OrderId, CandidateId] = {}; trades: dict[CandidateId, PortfolioTradeId] = {}; fills: set[CandidateId] = set(); indexed: dict[AttributionEventId, AttributionEvent] = {}; effective: dict[tuple[AttributionEventId, str], JsonValue] = {}; previous = GENESIS_HASH
        for event in self.events:
            candidate = _candidate_id(event.payload)
            if event.event_type is not _event_type(event.payload) or event.prev_event_hash != previous or event.event_id != _event_id(self.ledger_id, event) or event.event_hash != _event_hash(event): raise LifecycleIntegrityError(IntegrityRule.HASH_CHAIN, candidate)
            match event.payload:  # noqa: MATCH_OK - exhaustive payload union
                case CandidateInventoryRecorded() as declared:
                    valid = inventory is None and not seen and declared.candidate_count == len(declared.candidate_ids) == len(set(declared.candidate_ids)) and declared.inventory_hash == canonical_hash(list(declared.candidate_ids))
                    if not valid: raise LifecycleIntegrityError(IntegrityRule.INVENTORY_MISMATCH)
                    inventory = declared
                case CandidateSeen(candidate_id=candidate_id):
                    if inventory is None: raise LifecycleIntegrityError(IntegrityRule.INVENTORY_REQUIRED, candidate_id)
                    if candidate_id not in inventory.candidate_ids or candidate_id in seen: raise LifecycleIntegrityError(IntegrityRule.INVENTORY_MISMATCH, candidate_id)
                    seen.add(candidate_id)
                case TerminalAttribution(candidate_id=candidate_id, action=action, recommendation_id=recommendation_id):
                    if candidate_id not in seen: raise LifecycleIntegrityError(IntegrityRule.ORPHAN_EVENT, candidate_id)
                    if candidate_id in terminals: raise LifecycleIntegrityError(IntegrityRule.DUPLICATE_TERMINAL, candidate_id)
                    terminals[candidate_id] = action; recommendations[candidate_id] = recommendation_id
                case OperatorDecisionRecorded(candidate_id=candidate_id, recommendation_id=recommendation_id, state=state):
                    if recommendations.get(candidate_id) != recommendation_id: raise LifecycleIntegrityError(IntegrityRule.ORPHAN_EVENT, candidate_id)
                    match terminals.get(candidate_id):  # noqa: MATCH_OK - Action and None are exhaustive
                        case Action.BUY | Action.SELL:
                            valid = state in (
                                OperatorDecisionState.ACCEPTED,
                                OperatorDecisionState.REJECTED,
                                OperatorDecisionState.IGNORED,
                                OperatorDecisionState.PARTIAL_EXECUTION,
                            )
                        case Action.HOLD:
                            valid = state in (
                                OperatorDecisionState.IGNORED,
                                OperatorDecisionState.NOT_APPLICABLE,
                            )
                        case Action.BLOCKED | Action.CANDIDATE_REJECTED:
                            valid = state is OperatorDecisionState.NOT_APPLICABLE
                        case None:
                            valid = False
                    if not valid: raise LifecycleIntegrityError(IntegrityRule.INVALID_OPERATOR_DECISION, candidate_id)
                    operators.add(candidate_id)
                case OrderLinked(candidate_id=candidate_id, order_id=order_id, portfolio_trade_id=trade_id):
                    if candidate_id not in operators or terminals.get(candidate_id) not in (Action.BUY, Action.SELL): raise LifecycleIntegrityError(IntegrityRule.EXECUTION_LINK, candidate_id)
                    orders[order_id] = candidate_id; trades[candidate_id] = trade_id
                case FillRecorded(candidate_id=candidate_id, order_id=order_id):
                    if orders.get(order_id) != candidate_id: raise LifecycleIntegrityError(IntegrityRule.LIFECYCLE_ORDER, candidate_id)
                    fills.add(candidate_id)
                case PositionClosed(candidate_id=candidate_id, portfolio_trade_id=trade_id):
                    if candidate_id not in fills or trades.get(candidate_id) != trade_id: raise LifecycleIntegrityError(IntegrityRule.LIFECYCLE_ORDER, candidate_id)
                case OutcomeMatured(candidate_id=candidate_id, recommendation_id=recommendation_id):
                    if recommendations.get(candidate_id) != recommendation_id: raise LifecycleIntegrityError(IntegrityRule.ORPHAN_EVENT, candidate_id)
                case CorrectionRecorded(candidate_id=candidate_id, target_event_id=target, field_path=path, old_value_hash=old_hash, new_value=new_value):
                    target_event = indexed.get(target)
                    if target_event is None or _candidate_id(target_event.payload) != candidate_id: raise LifecycleIntegrityError(IntegrityRule.CORRECTION_TARGET, candidate_id)
                    key = (target, path); current = effective.get(key, _field_value(target_event.payload, path))
                    if canonical_hash(current) != old_hash: raise LifecycleIntegrityError(IntegrityRule.OLD_VALUE_HASH, candidate_id)
                    effective[key] = new_value
            indexed[event.event_id] = event; previous = event.event_hash

    def reconcile_candidates(self) -> None:
        self.validate_chain(); inventories = tuple(event.payload for event in self.events if isinstance(event.payload, CandidateInventoryRecorded))
        if len(inventories) != 1: raise LifecycleIntegrityError(IntegrityRule.INVENTORY_REQUIRED)
        expected = set(inventories[0].candidate_ids); seen = {event.payload.candidate_id for event in self.events if isinstance(event.payload, CandidateSeen)}; terminal = {event.payload.candidate_id for event in self.events if isinstance(event.payload, TerminalAttribution)}
        if seen != expected: raise LifecycleIntegrityError(IntegrityRule.INVENTORY_MISMATCH, sorted(expected ^ seen)[0])
        if disappeared := expected - terminal: raise LifecycleIntegrityError(IntegrityRule.DISAPPEARED_CANDIDATE, sorted(disappeared)[0])
        if terminal != expected: raise LifecycleIntegrityError(IntegrityRule.INVENTORY_MISMATCH, sorted(terminal ^ expected)[0])

    def effective_value(self, target_event_id: AttributionEventId, field_path: str) -> JsonValue:
        self.validate_chain(); target = next((event for event in self.events if event.event_id == target_event_id), None)
        if target is None: raise LifecycleIntegrityError(IntegrityRule.CORRECTION_TARGET)
        value = _field_value(target.payload, field_path)
        for event in self.events:
            if isinstance(event.payload, CorrectionRecorded) and event.payload.target_event_id == target_event_id and event.payload.field_path == field_path: value = event.payload.new_value
        return value

    def denominator_summary(self) -> DenominatorSummary:
        actions = tuple(event.payload.action for event in self.events if isinstance(event.payload, TerminalAttribution)); counts = tuple(actions.count(action) for action in Action); total = len(actions)
        return DenominatorSummary(counts[0], counts[1], counts[2], counts[3], counts[4], total, counts[0] + counts[1], total)
