from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json
from src.v11.models import EventType

from .contract import V15Failure, V15FailureCode
from .mirrors import create_mirrors
from .operation_fixture import MarketSchedule, OperationSourceFixture
from .operation_models import OrbQualificationEvidence
from .promotion import OperationalSample, require_strategies_shadow
from .upstream import UpstreamEvidence
from .v11_mirror_ledger import (
    MirrorBuildContext,
    build_mirror_ledger,
    verify_mirror_ledger,
)


def build_orb_qualification(
    source: OperationSourceFixture,
    schedule: MarketSchedule,
    upstream: UpstreamEvidence,
) -> OrbQualificationEvidence:
    account = create_mirrors((schedule.market,
        schedule.qualification_sessions[0]), source.initial_nav,
        (upstream.v14_bundle_hash, upstream.v14_result_manifest_hash,
            upstream.policy.risk_version, upstream.policy.cost_model))[0]
    ledger = build_mirror_ledger(MirrorBuildContext(mirror=account,
        schedule=schedule, sessions=schedule.qualification_sessions,
        initial_nav=source.initial_nav,
        completed_trades_per_trade_day=source.completed_trades_per_trade_day,
        returns=source.returns, manifest_hash=upstream.policy.manifest_hash))
    draft = OrbQualificationEvidence(
        schema_version="v15.orb_qualification.1", ledger=ledger,
        official_sessions=len(ledger.days),
        completed_trades=sum(day.completed_trades for day in ledger.days),
        critical_incident_hashes=(), evidence_hash="")
    return draft.model_copy(update={"evidence_hash": canonical_hash(
        model_json(draft))})


def verify_orb_qualification(
    evidence: OrbQualificationEvidence,
    schedule: MarketSchedule,
    upstream: UpstreamEvidence,
) -> None:
    verify_mirror_ledger(evidence.ledger)
    sessions = tuple(day.session for day in evidence.ledger.days)
    trades = sum(day.completed_trades for day in evidence.ledger.days)
    critical = tuple(str(event.event_hash) for event in evidence.ledger.events
        if (event.event_type is EventType.RISK_CHECKED
            and event.payload.get("accepted") is not True)
        or (event.event_type is EventType.RECONCILED
            and event.payload.get("halted") is True))
    draft = evidence.model_copy(update={"evidence_hash": ""})
    if evidence.ledger.account.market != schedule.market \
            or evidence.ledger.account.arm != "orb" \
            or sessions != schedule.qualification_sessions \
            or evidence.official_sessions != len(sessions) \
            or evidence.completed_trades != trades \
            or evidence.critical_incident_hashes != critical \
            or evidence.evidence_hash != canonical_hash(model_json(draft)):
        raise V15Failure(V15FailureCode.PROMOTION_BLOCKED,
            f"qualification:{schedule.market}")
    _ = require_strategies_shadow(upstream, schedule.market,
        OperationalSample(official_sessions=evidence.official_sessions,
            completed_trades=evidence.completed_trades,
            critical_incidents=len(evidence.critical_incident_hashes)))
