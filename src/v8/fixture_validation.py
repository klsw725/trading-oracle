from __future__ import annotations

import re
from typing import Final

from src.v8.event_models import FillEvent, OrderEvent, PositionEvent, RecommendationEvent, ReconciledEvent
from src.v8.models import FailureCode, LedgerContractError, PaperLedgerFixture

_HASH: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_fixture_contract(fixture: PaperLedgerFixture) -> None:
    if (
        not fixture.paper_namespace.startswith("paper:")
        or fixture.recommendation.paper_namespace != fixture.paper_namespace
    ):
        raise LedgerContractError(
            FailureCode.LIVE_STATE_CONTAMINATION, "paper namespace is missing"
        )
    if _HASH.fullmatch(fixture.recommendation.source_recommendation_fingerprint) is None:
        raise LedgerContractError(
            FailureCode.MALFORMED_INPUT, "bad recommendation fingerprint"
        )
    event_ids: set[str] = set()
    for event in fixture.events:
        if event.event_id in event_ids:
            raise LedgerContractError(
                FailureCode.MALFORMED_INPUT, "duplicate event ID"
            )
        event_ids.add(event.event_id)
        if event.recorded_at < event.occurred_at or event.occurred_at.tzinfo is None:
            raise LedgerContractError(
                FailureCode.MALFORMED_INPUT, "invalid event domain time"
            )
        if _HASH.fullmatch(event.event_hash) is None or (
            event.prev_event_hash != "sha256:genesis"
            and _HASH.fullmatch(event.prev_event_hash) is None
        ):
            raise LedgerContractError(FailureCode.MALFORMED_INPUT, "bad hash format")
        if not event.event_id.startswith("pevt_v8_"):
            raise LedgerContractError(
                FailureCode.LIVE_STATE_CONTAMINATION, "non-paper event identity"
            )
        match event:  # noqa: MATCH_OK - non-identity events need no prefix check
            case RecommendationEvent(payload=payload):
                identity = payload.paper_recommendation_id
                prefix = "prec_v8_"
            case OrderEvent(payload=payload):
                if payload.destination != "paper_engine":
                    raise LedgerContractError(
                        FailureCode.LIVE_STATE_CONTAMINATION,
                        "paper order destination is not paper_engine",
                    )
                identity = payload.paper_order_id
                prefix = "pord_v8_"
            case FillEvent(payload=payload):
                identity = payload.paper_fill_id
                prefix = "pfill_v8_"
            case PositionEvent(payload=payload):
                identity = payload.paper_position_id
                prefix = "ppos_v8_"
            case ReconciledEvent(payload=payload):
                identity = payload.paper_reconciliation_id
                prefix = "precon_v8_"
            case _:
                continue
        if not identity.startswith(prefix):
            raise LedgerContractError(
                FailureCode.LIVE_STATE_CONTAMINATION, "non-paper primary identity"
            )
