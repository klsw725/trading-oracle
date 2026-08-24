from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.v17.database import Connection

from .canonical import JsonValue, canonical_hash, canonical_json, content_hash, model_json
from .errors import FaultInjected
from .models import LegacyQuarantineRecord
from .validation import canonical_utc


class RepositoryPort(Protocol):
    connection: Connection

    def begin(self) -> None: ...
    def reconcile(self) -> None: ...
    def stored_result(self, command: str, semantic: str, request_hash: str) -> str | None: ...
    def append_event(
        self, event_type: str, aggregate_id: str, semantic_key: str,
        payload: JsonValue, created_as_of: str,
    ) -> str: ...
    def store_result(
        self, command: str, semantic: str, request_hash: str,
        result: JsonValue, event_id: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredQuarantine:
    record: LegacyQuarantineRecord
    duplicate: bool
    event_id: str


def _hit(fault: str | None, checkpoint: str) -> None:
    if fault == checkpoint:
        raise FaultInjected(checkpoint)


def store_quarantine(
    repository: RepositoryPort,
    source: bytes,
    source_label: str,
    observed_schema_hint: str,
    rejection_codes: tuple[str, ...],
    observed_as_of: str,
    *,
    fault: str | None = None,
) -> StoredQuarantine:
    _ = canonical_utc(observed_as_of)
    provenance: JsonValue = {
        "observed_as_of": observed_as_of,
        "observed_schema_hint": observed_schema_hint,
        "rejection_codes": list(sorted(rejection_codes)),
        "source_bytes_hash": content_hash(source),
        "source_label": source_label,
    }
    quarantine_id = canonical_hash(provenance)
    record = LegacyQuarantineRecord(
        quarantine_id=quarantine_id,
        source_label=source_label,
        source_bytes_hash=content_hash(source),
        observed_schema_hint=observed_schema_hint,
        rejection_codes=tuple(sorted(rejection_codes)),
        observed_as_of=observed_as_of,
    )
    semantic = canonical_hash({"quarantine_id": quarantine_id})
    body = model_json(record)
    body_hash = canonical_hash(body)
    repository.begin()
    try:
        duplicate = repository.stored_result("quarantine_legacy", semantic, body_hash)
        if duplicate is not None:
            repository.connection.commit()
            return StoredQuarantine(record, True, duplicate)
        event_id = repository.append_event(
            "legacy.quarantined",
            quarantine_id,
            semantic,
            {"quarantine_id": quarantine_id},
            observed_as_of,
        )
        _hit(fault, "after_event_append")
        _ = repository.connection.execute(
            "INSERT INTO legacy_prediction_quarantine VALUES(?,?,?,?,?,?,?,?,?)",
            (
                quarantine_id,
                source_label,
                content_hash(source),
                observed_schema_hint,
                canonical_json(list(sorted(rejection_codes))).decode("utf-8"),
                observed_as_of,
                canonical_json(body).decode("utf-8"),
                body_hash,
                event_id,
            ),
        )
        _hit(fault, "after_immutable_row_insert")
        repository.store_result(
            "quarantine_legacy",
            semantic,
            body_hash,
            {"quarantine_id": quarantine_id},
            event_id,
        )
        _hit(fault, "after_idempotency_insert")
        repository.connection.commit()
        return StoredQuarantine(record, False, event_id)
    except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then re-raise.
        repository.connection.rollback()
        raise
