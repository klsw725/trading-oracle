from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash
from src.v8.event_models import (
    AccountOpenedEvent,
    CorporateActionEvent,
    CorrectionEvent,
    EntityRef,
    FeeModelEvent,
    FillEvent,
    LedgerEvent,
    OrderEvent,
    PositionEvent,
    RecommendationEvent,
    ReconciledEvent,
)
from src.v8.identity import deterministic_id, event_hash, model_json
from src.v8.fixture_validation import validate_fixture_contract
from src.v8.models import (
    FailureCode,
    LedgerContractError,
    PaperLedgerArtifact,
    PaperLedgerFixture,
)

FORBIDDEN_KEYS: Final = frozenset(
    {"access_token", "account_number", "client_secret", "live_order_id"}
)
HASH_PREFIX: Final = "sha256:"


@dataclass(frozen=True, slots=True)
class CompileIds:
    recommendation_id: str
    order_id: str | None = None
    fill_id: str | None = None
    position_id: str | None = None
    reconciliation_id: str | None = None


def _forbidden_keys(value: JsonValue) -> tuple[str, ...]:
    if value is None:
        return ()
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            own = tuple(sorted(FORBIDDEN_KEYS.intersection(record)))
            nested = tuple(
                item
                for child in record.values()
                for item in _forbidden_keys(child)
            )
            return own + nested
        case list() as items:
            return tuple(item for child in items for item in _forbidden_keys(child))
        case bool() | int() | float() | str():
            return ()


def _recommendation_id(fixture: PaperLedgerFixture) -> str:
    recommendation = fixture.recommendation
    return deterministic_id(
        "prec_v8_",
        {
            "schema_version": recommendation.schema_version,
            "paper_namespace": recommendation.paper_namespace,
            "decision_at": recommendation.decision_at.isoformat(),
            "ticker": recommendation.ticker,
            "side": recommendation.side,
            "quantity": str(recommendation.quantity),
            "limit_price": str(recommendation.limit_price),
            "source_recommendation_fingerprint": recommendation.source_recommendation_fingerprint,
        },
    )


def _event_identity(event: LedgerEvent, previous_hash: str) -> str:
    return deterministic_id(
        "pevt_v8_",
        {
            "paper_namespace": event.paper_namespace,
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "entity_ref": model_json(event.entity_ref),
            "prev_event_hash": previous_hash,
        },
    )


def _rebuild_payload(
    event: LedgerEvent, fixture: PaperLedgerFixture, ids: CompileIds
) -> tuple[LedgerEvent, CompileIds]:
    match event:  # noqa: MATCH_OK - LedgerEvent union is exhaustively handled
        case AccountOpenedEvent():
            return event, ids
        case RecommendationEvent(payload=payload):
            updated = payload.model_copy(
                update={"paper_recommendation_id": ids.recommendation_id}
            )
            entity = EntityRef(
                entity_type="paper_recommendation",
                entity_id=ids.recommendation_id,
            )
            return event.model_copy(update={"payload": updated, "entity_ref": entity}), ids
        case OrderEvent(payload=payload):
            order_id = deterministic_id(
                "pord_v8_",
                {
                    "paper_recommendation_id": ids.recommendation_id,
                    "side": payload.side,
                    "quantity": str(payload.quantity),
                    "limit_price": str(payload.limit_price),
                    "idempotency_key": payload.idempotency_key,
                    "created_at": event.occurred_at.isoformat(),
                },
            )
            updated = payload.model_copy(
                update={
                    "paper_order_id": order_id,
                    "paper_recommendation_id": ids.recommendation_id,
                }
            )
            entity = EntityRef(entity_type="paper_order", entity_id=order_id)
            return event.model_copy(update={"payload": updated, "entity_ref": entity}), CompileIds(
                ids.recommendation_id, order_id
            )
        case FillEvent(payload=payload):
            if ids.order_id is None:
                raise LedgerContractError(
                    FailureCode.MALFORMED_INPUT, "fill appears before paper order"
                )
            fill_id = deterministic_id(
                "pfill_v8_",
                {
                    "paper_order_id": ids.order_id,
                    "price_source_id": payload.price_source_id,
                    "quantity": str(payload.quantity),
                    "fill_price": str(payload.fill_price),
                    "filled_at": event.occurred_at.isoformat(),
                },
            )
            updated = payload.model_copy(
                update={"paper_fill_id": fill_id, "paper_order_id": ids.order_id}
            )
            entity = EntityRef(entity_type="paper_fill", entity_id=fill_id)
            return event.model_copy(update={"payload": updated, "entity_ref": entity}), CompileIds(
                ids.recommendation_id, ids.order_id, fill_id
            )
        case PositionEvent(payload=payload):
            position_id = deterministic_id(
                "ppos_v8_",
                {
                    "paper_namespace": fixture.paper_namespace,
                    "ticker": payload.ticker,
                    "currency": fixture.fee_model.currency,
                },
            )
            updated = payload.model_copy(update={"paper_position_id": position_id})
            entity = EntityRef(entity_type="paper_position", entity_id=position_id)
            return event.model_copy(update={"payload": updated, "entity_ref": entity}), CompileIds(
                ids.recommendation_id, ids.order_id, ids.fill_id, position_id
            )
        case ReconciledEvent(payload=payload):
            last_ref = ids.fill_id or event.prev_event_hash
            last_ref_field = "last_fill_id" if ids.fill_id else "last_event_hash"
            reconciliation_id = deterministic_id(
                "precon_v8_",
                {
                    "paper_namespace": fixture.paper_namespace,
                    "as_of": event.occurred_at.isoformat(),
                    last_ref_field: last_ref,
                },
            )
            updated = payload.model_copy(
                update={"paper_reconciliation_id": reconciliation_id}
            )
            entity = EntityRef(
                entity_type="paper_reconciliation", entity_id=reconciliation_id
            )
            return event.model_copy(update={"payload": updated, "entity_ref": entity}), CompileIds(
                ids.recommendation_id,
                ids.order_id,
                ids.fill_id,
                ids.position_id,
                reconciliation_id,
            )
        case CorporateActionEvent() | FeeModelEvent() | CorrectionEvent():
            return event, ids


def _compile_events(
    fixture: PaperLedgerFixture, recommendation_id: str
) -> tuple[tuple[LedgerEvent, ...], CompileIds]:
    previous_hash = "sha256:genesis"
    ids = CompileIds(recommendation_id)
    compiled: list[LedgerEvent] = []
    for source_event in fixture.events:
        event, ids = _rebuild_payload(source_event, fixture, ids)
        event_id = _event_identity(event, previous_hash)
        event = event.model_copy(
            update={
                "event_id": event_id,
                "prev_event_hash": previous_hash,
                "event_hash": HASH_PREFIX + "0" * 64,
            }
        )
        event = event.model_copy(update={"event_hash": event_hash(event)})
        compiled.append(event)
        previous_hash = event.event_hash
    return tuple(compiled), ids


def compile_fixture(value: JsonValue) -> PaperLedgerArtifact:
    forbidden = _forbidden_keys(value)
    if forbidden:
        raise LedgerContractError(
            FailureCode.LIVE_STATE_CONTAMINATION,
            f"forbidden keys: {','.join(sorted(set(forbidden)))}",
        )
    try:
        fixture = PaperLedgerFixture.model_validate(value)
    except ValidationError as error:
        raise LedgerContractError(FailureCode.MALFORMED_INPUT, str(error)) from error
    validate_fixture_contract(fixture)
    recommendation_id = _recommendation_id(fixture)
    events, ids = _compile_events(fixture, recommendation_id)
    recommendation = fixture.recommendation.model_copy(
        update={"paper_recommendation_id": recommendation_id}
    )
    positions = tuple(
        position.model_copy(update={"paper_position_id": ids.position_id})
        for position in fixture.expected_after_replay.positions
    )
    fills = tuple(
        fill.model_copy(update={"paper_fill_id": ids.fill_id})
        for fill in fixture.expected_after_replay.fills
    )
    expected = fixture.expected_after_replay.model_copy(
        update={
            "positions": positions,
            "fills": fills,
            "last_reconciliation_id": ids.reconciliation_id,
        }
    )
    return PaperLedgerArtifact(
        schema_version=fixture.schema_version,
        fixture_name=fixture.fixture_name,
        paper_namespace=fixture.paper_namespace,
        live_namespace_forbidden=fixture.live_namespace_forbidden,
        credential_fields_forbidden=fixture.credential_fields_forbidden,
        fee_model=fixture.fee_model,
        starting_balances=fixture.starting_balances,
        recommendation=recommendation,
        expected_after_replay=expected,
        events=events,
        source_input_hash=canonical_hash(value),
    )
