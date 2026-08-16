from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field
from src.v11.models import LedgerEvent, Money, ReplayState

from .approvals import Approval
from .contract import StrictModel
from .effects import EffectLedger, SideEffectInventory
from .incidents import IncidentRecord
from .liquidation import KillExecution
from .mirrors import MirrorAccount
from .observability import LlmOutcomeLedger
from .operation_fixture import MarketSchedule, OperationSourceFixture
from .paired import ArmDay, PairedSeries
from .recovery import RecoveryEvidence
from .reporting import SessionReport
from .retirement import RetirementRegistry
from .risk_monitor import LossResult, PnlMark
from .rollback import RollbackDecision
from .states import KillOverlay, LifecycleState, OperationEvent, OperationEventType
from .upstream import UpstreamEvidence
from .winner import IntegrityEvidence, WinnerArtifact


class EventSpec(StrictModel):
    event_type: OperationEventType
    market: Literal["KR", "US"] | None
    arm: str | None
    symbol: str | None
    session: date
    occurred_at: datetime
    evidence_refs: Annotated[tuple[str, ...], Field(strict=False)]
    detail_hash: str
    lifecycle_before: LifecycleState
    lifecycle_after: LifecycleState
    kill_before: KillOverlay
    kill_after: KillOverlay


class MirrorLedger(StrictModel):
    account: MirrorAccount
    initial_cash: Money
    events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    replay_state: ReplayState
    days: Annotated[tuple[ArmDay, ...], Field(strict=False)]
    ledger_hash: str


class OrbQualificationEvidence(StrictModel):
    schema_version: Literal["v15.orb_qualification.1"]
    ledger: MirrorLedger
    official_sessions: int
    completed_trades: int
    critical_incident_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    evidence_hash: str


class MarketOperation(StrictModel):
    market: Literal["KR", "US"]
    schedule: MarketSchedule
    orb_qualification: OrbQualificationEvidence
    mirror_ledgers: Annotated[tuple[MirrorLedger, MirrorLedger], Field(strict=False)]
    paired_series: PairedSeries
    integrity: IntegrityEvidence
    rolling_winners: Annotated[tuple[WinnerArtifact, ...], Field(strict=False)]
    initial_winner: WinnerArtifact
    router_winner: WinnerArtifact | None
    performance_rollback: RollbackDecision | None


class ReplayResultBody(StrictModel):
    schema_version: Literal["v15.replay_result.2"]
    operation_chain_hash: str
    paired_series_hashes: Annotated[tuple[str, str], Field(strict=False)]
    winner_hashes: Annotated[tuple[str, str], Field(strict=False)]
    final_router_state: Literal["router_challenger", "router_primary",
        "router_retired"]
    retired_versions: Annotated[tuple[str, ...], Field(strict=False)]
    report_inventory_hash: str
    kill_inventory_hash: str
    effect_ledger_hash: str
    side_effect_inventory: SideEffectInventory


class ReplayResult(ReplayResultBody):
    replay_hash: str


class OperationMaterial(StrictModel):
    schema_version: Literal["v15.operation_bundle.2"]
    source: OperationSourceFixture
    source_fixture_hash: str
    upstream: UpstreamEvidence
    approvals: Annotated[tuple[Approval, Approval], Field(strict=False)]
    markets: Annotated[tuple[MarketOperation, MarketOperation], Field(strict=False)]
    pnl_marks: Annotated[tuple[PnlMark, ...], Field(strict=False)]
    loss_results: Annotated[tuple[LossResult, ...], Field(strict=False)]
    kill_executions: Annotated[tuple[KillExecution, ...], Field(strict=False)]
    incidents: Annotated[tuple[IncidentRecord, ...], Field(strict=False)]
    recoveries: Annotated[tuple[RecoveryEvidence, ...], Field(strict=False)]
    retirement_registry: RetirementRegistry
    events: Annotated[tuple[OperationEvent, ...], Field(strict=False)]
    llm_outcomes: Annotated[tuple[LlmOutcomeLedger, LlmOutcomeLedger], Field(strict=False)]
    session_reports: Annotated[tuple[SessionReport, ...], Field(strict=False)]
    effects: EffectLedger


class OperationBundleBody(OperationMaterial):
    replay: ReplayResult


class OperationBundle(OperationBundleBody):
    bundle_hash: str


def material_from_bundle(bundle: OperationBundle) -> OperationMaterial:
    return OperationMaterial(schema_version=bundle.schema_version,
        source=bundle.source, source_fixture_hash=bundle.source_fixture_hash,
        upstream=bundle.upstream, approvals=bundle.approvals,
        markets=bundle.markets, pnl_marks=bundle.pnl_marks,
        loss_results=bundle.loss_results,
        kill_executions=bundle.kill_executions, incidents=bundle.incidents,
        recoveries=bundle.recoveries,
        retirement_registry=bundle.retirement_registry,
        events=bundle.events, llm_outcomes=bundle.llm_outcomes,
        session_reports=bundle.session_reports, effects=bundle.effects)
