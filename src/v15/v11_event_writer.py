from __future__ import annotations

from datetime import datetime
from typing import Final, final

from src.v11.canonical import canonical_hash
from src.v11.ledger import GENESIS
from src.v11.models import EventHash, EventType, LedgerEvent, V11ContractError
from src.v4.models import JsonValue


@final
class LedgerWriter:
    __slots__: Final = ("_events", "_manifest_hash", "_semantics")

    def __init__(self, manifest_hash: str) -> None:
        self._manifest_hash: str = manifest_hash
        self._events: list[LedgerEvent] = []
        self._semantics: set[tuple[str, str]] = set()

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._events)

    def since(self, index: int) -> tuple[LedgerEvent, ...]:
        return tuple(self._events[index:])

    def append(
        self, event_type: EventType, entity_id: str, at: datetime,
        payload: dict[str, JsonValue],
    ) -> None:
        if self._events and at < self._events[-1].occurred_at:
            raise V11ContractError("V11_EVENT_TIME_ORDER", at.isoformat())
        semantic_key = payload.get("semantic_key")
        if isinstance(semantic_key, str):
            semantic = (entity_id, semantic_key)
            if semantic in self._semantics:
                raise V11ContractError("V11_SEMANTIC_DUPLICATE", semantic_key)
            self._semantics.add(semantic)
        index = len(self._events)
        previous = self._events[-1].event_hash if self._events else GENESIS
        payload_hash = canonical_hash(payload)
        body: dict[str, JsonValue] = {"event_index": index,
            "event_type": event_type.value, "entity_id": entity_id,
            "occurred_at": at.isoformat(), "recorded_at": at.isoformat(),
            "payload_hash": payload_hash, "previous_event_hash": previous,
            "experiment_manifest_hash": self._manifest_hash,
            "payload": payload}
        digest = canonical_hash(body)
        event = LedgerEvent(
            event_id=f"v11:event:{digest.removeprefix('sha256:')[:20]}",
            event_index=index, event_type=event_type, entity_id=entity_id,
            occurred_at=at, recorded_at=at, payload_hash=payload_hash,
            previous_event_hash=previous, event_hash=EventHash(digest),
            experiment_manifest_hash=self._manifest_hash, payload=payload)
        self._events.append(event)
