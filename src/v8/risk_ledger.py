from __future__ import annotations

from dataclasses import dataclass

from src.v8.risk_json import canonical_hash, model_json
from src.v8.risk_models import RiskArtifact, RiskErrorCode


@dataclass(frozen=True, slots=True)
class RiskLedger:
    entries: tuple[RiskArtifact, ...]

    @classmethod
    def empty(cls) -> RiskLedger:
        return cls(())


@dataclass(frozen=True, slots=True)
class AppendRiskResult:
    ledger: RiskLedger
    artifact: RiskArtifact | None
    appended_count: int
    returned_existing: bool
    error_code: RiskErrorCode | None = None


def append_risk(ledger: RiskLedger, artifact: RiskArtifact) -> AppendRiskResult:
    matching = tuple(
        entry
        for entry in ledger.entries
        if entry.request.idempotency_key == artifact.request.idempotency_key
    )
    if matching:
        existing = matching[0]
        existing_seed = canonical_hash(model_json(existing.request))
        candidate_seed = canonical_hash(model_json(artifact.request))
        if existing_seed != candidate_seed:
            return AppendRiskResult(
                ledger, None, 0, False, RiskErrorCode.IDEMPOTENCY_CONFLICT
            )
        return AppendRiskResult(ledger, existing, 0, True)
    return AppendRiskResult(
        RiskLedger((*ledger.entries, artifact)), artifact, 1, False
    )
