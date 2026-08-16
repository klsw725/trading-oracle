from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel
from .paired import PairedSeries, bootstrap, require_winner_sample, series_prefix


@unique
class WinnerVerdict(StrEnum):
    ROUTER = "router"
    INCONCLUSIVE = "inconclusive"
    ORB = "orb"


class IntegrityEvidence(StrictModel):
    schema_version: Literal["v15.integrity_evidence.1"]
    market: Literal["KR", "US"]
    ledger_hashes: Annotated[tuple[str, str], Field(strict=False)]
    critical_incident_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    evidence_hash: str


class WinnerArtifact(StrictModel):
    schema_version: Literal["v15.winner.2"]
    market: Literal["KR", "US"]
    evaluation_session: date
    observation_count: int
    series_hash: str
    integrity_evidence_hash: str
    verdict: WinnerVerdict
    ci_lower: Decimal
    ci_upper: Decimal
    router_stress_net_return: Decimal
    winner_hash: str


def seal_integrity(evidence: IntegrityEvidence) -> IntegrityEvidence:
    draft = evidence.model_copy(update={"evidence_hash": ""})
    return draft.model_copy(update={"evidence_hash": canonical_hash(
        model_json(draft))})


def verify_integrity(evidence: IntegrityEvidence) -> None:
    if seal_integrity(evidence) != evidence:
        from .contract import V15Failure, V15FailureCode
        raise V15Failure(V15FailureCode.LEDGER_EVIDENCE,
            evidence.market)


def decide_winner(
    series: PairedSeries, integrity: IntegrityEvidence
) -> WinnerArtifact:
    require_winner_sample(series)
    verify_integrity(integrity)
    interval = bootstrap(series)
    stress = sum((point.router_gross_return
        - point.router_execution_cost * 2 for point in series.points), Decimal(0))
    if interval.ci_lower > 0 and stress > 0 \
            and not integrity.critical_incident_hashes:
        verdict = WinnerVerdict.ROUTER
    elif interval.ci_upper < 0:
        verdict = WinnerVerdict.ORB
    else:
        verdict = WinnerVerdict.INCONCLUSIVE
    draft = WinnerArtifact(schema_version="v15.winner.2",
        market=series.plan.market, evaluation_session=series.points[-1].session,
        observation_count=len(series.points), series_hash=series.series_hash,
        integrity_evidence_hash=integrity.evidence_hash, verdict=verdict,
        ci_lower=interval.ci_lower, ci_upper=interval.ci_upper,
        router_stress_net_return=stress, winner_hash="")
    return draft.model_copy(update={"winner_hash": canonical_hash(
        model_json(draft))})


def rolling_winners(
    series: PairedSeries, integrity: IntegrityEvidence
) -> tuple[WinnerArtifact, ...]:
    results: list[WinnerArtifact] = []
    for count in range(60, len(series.points) + 1):
        prefix = series_prefix(series, count)
        orb_trades = sum(item.orb_completed_trades for item in prefix.points)
        router_trades = sum(item.router_completed_trades for item in prefix.points)
        if orb_trades >= 300 and router_trades >= 300:
            results.append(decide_winner(prefix, integrity))
    return tuple(results)
