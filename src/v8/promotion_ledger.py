from __future__ import annotations

from dataclasses import dataclass

from src.v8.promotion_models import (
    IncidentRecord,
    PromotionArtifact,
    PromotionErrorCode,
)
from src.v8.risk_json import JsonValue, canonical_hash, model_json

type PromotionRecord = PromotionArtifact | IncidentRecord


@dataclass(frozen=True, slots=True)
class StoredPromotion:
    idempotency_key: str
    seed_hash: str
    record: PromotionRecord


@dataclass(frozen=True, slots=True)
class PromotionLedger:
    entries: tuple[StoredPromotion, ...]
    incident_pending: bool

    @classmethod
    def empty(cls) -> PromotionLedger:
        return cls((), False)


@dataclass(frozen=True, slots=True)
class AppendPromotionResult:
    ledger: PromotionLedger
    record: PromotionRecord | None
    appended_count: int
    returned_existing: bool
    error_code: PromotionErrorCode | None = None


def _identity(record: PromotionRecord) -> tuple[str, JsonValue]:
    match record:  # noqa: MATCH_OK - PromotionRecord variants are fully returned
        case PromotionArtifact(decision=decision):
            return decision.idempotency_key, model_json(decision, exclude={"record_hash"})
        case IncidentRecord(incident_id=incident_id, evidence=evidence):
            return incident_id, model_json(evidence)


def _append(ledger: PromotionLedger, record: PromotionRecord) -> AppendPromotionResult:
    key, seed = _identity(record)
    seed_hash = canonical_hash(seed)
    for stored in ledger.entries:
        if stored.idempotency_key != key:
            continue
        if stored.seed_hash == seed_hash:
            return AppendPromotionResult(ledger, stored.record, 0, True)
        return AppendPromotionResult(
            ledger, None, 0, False, PromotionErrorCode.IDEMPOTENCY_CONFLICT
        )
    stored = StoredPromotion(key, seed_hash, record)
    return AppendPromotionResult(
        PromotionLedger((*ledger.entries, stored), ledger.incident_pending), record, 1, False
    )


def append_promotion(ledger: PromotionLedger, record: PromotionRecord) -> AppendPromotionResult:
    if ledger.incident_pending:
        return AppendPromotionResult(
            ledger,
            None,
            0,
            False,
            PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED,
        )
    return _append(ledger, record)


def complete_interrupted_incident(
    ledger: PromotionLedger, incident: IncidentRecord | None
) -> AppendPromotionResult:
    if incident is None:
        return AppendPromotionResult(
            PromotionLedger(ledger.entries, True),
            None,
            0,
            False,
            PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED,
        )
    completion = _append(PromotionLedger(ledger.entries, False), incident)
    if completion.error_code is not None:
        return AppendPromotionResult(
            ledger,
            None,
            0,
            False,
            completion.error_code,
        )
    return completion
