from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field
from src.v11.canonical import canonical_hash, model_json

from .contract import StrictModel, V15Failure, V15FailureCode
from .liquidation import KillExecution
from .paired import PairedSeries, bootstrap
from .recovery import RecoveryEvidence, recover
from .retirement import RetirementRegistry, require_active
from .winner import IntegrityEvidence, verify_integrity


@unique
class RollbackKind(StrEnum):
    OPERATIONAL = "operational"
    PERFORMANCE = "performance"


class RouterVersion(StrictModel):
    market: Literal["KR", "US"]
    version: str
    manifest_hash: str


class IncidentEvidence(StrictModel):
    incident_hash: str
    critical_codes: Annotated[tuple[str, ...], Field(strict=False)]
    input_hash: str
    replay_before_hash: str


class RollbackDecision(StrictModel):
    schema_version: Literal["v15.rollback.3"]
    market: Literal["KR", "US"]
    kind: RollbackKind
    router_version: str
    primary_after: Literal["orb"]
    evidence_hash: str
    integrity_evidence_hash: str
    window_sessions: Annotated[tuple[date, ...], Field(strict=False)]
    ci_upper: Decimal | None
    retired: bool


def operational_rollback(
    version: RouterVersion, incident: IncidentEvidence
) -> RollbackDecision:
    if not incident.critical_codes:
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "incident_evidence")
    return RollbackDecision(schema_version="v15.rollback.3",
        market=version.market, kind=RollbackKind.OPERATIONAL,
        router_version=version.version, primary_after="orb",
        evidence_hash=incident.incident_hash,
        integrity_evidence_hash=incident.input_hash, window_sessions=(),
        ci_upper=None, retired=False)


def resume_operational(
    version: RouterVersion, evidence: RecoveryEvidence,
    expected_next_session: date, execution: KillExecution,
) -> Literal["router"]:
    if version.manifest_hash != evidence.original_identity.manifest_hash:
        raise V15Failure(V15FailureCode.RECOVERY_BLOCKED, version.version)
    _ = recover(evidence, expected_next_session, execution)
    return "router"


def performance_rollback(
    series: PairedSeries,
    version: RouterVersion,
    integrity: IntegrityEvidence,
) -> RollbackDecision:
    verify_integrity(integrity)
    if len(series.points) < 20 or series.plan.market != version.market:
        raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT, "performance")
    points = series.points[-20:]
    orb_trades = sum(item.orb_completed_trades for item in points)
    router_trades = sum(item.router_completed_trades for item in points)
    if orb_trades < 100 or router_trades < 100:
        raise V15Failure(V15FailureCode.SAMPLE_INSUFFICIENT, "performance")
    interval = bootstrap(series, window=20)
    if interval.ci_upper > 0:
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "performance_hold")
    sessions = tuple(item.session for item in points)
    evidence_hash = canonical_hash({"bootstrap": model_json(interval),
        "sessions": [item.isoformat() for item in sessions],
        "orb_trades": orb_trades, "router_trades": router_trades,
        "series_hash": series.series_hash,
        "integrity_evidence_hash": integrity.evidence_hash})
    return RollbackDecision(schema_version="v15.rollback.3",
        market=version.market, kind=RollbackKind.PERFORMANCE,
        router_version=version.version, primary_after="orb",
        evidence_hash=evidence_hash,
        integrity_evidence_hash=integrity.evidence_hash,
        window_sessions=sessions, ci_upper=interval.ci_upper, retired=True)


def require_promotable(
    registry: RetirementRegistry,
    market: Literal["KR", "US"],
    version: str,
) -> None:
    require_active(registry, market, version)
