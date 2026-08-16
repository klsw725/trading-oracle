from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.v11.canonical import decimal_value

from .incidents import IncidentRecord
from .kill_switch import TriggerKind, dominant_overlay
from .liquidation import KillExecution
from .observability import LlmOutcomeLedger, summarize_llm
from .operation_models import MarketOperation, MirrorLedger
from .recovery import RecoveryEvidence
from .reporting import (
    ActivityCounts,
    DataHealth,
    Exposure,
    PairedStatus,
    PnlBreakdown,
    SessionReport,
)
from .states import KillOverlay


def build_reports(
    markets: tuple[MarketOperation, MarketOperation],
    llm_ledgers: tuple[LlmOutcomeLedger, LlmOutcomeLedger],
    incidents: tuple[IncidentRecord, ...],
    executions: tuple[KillExecution, ...],
    recoveries: tuple[RecoveryEvidence, ...],
    manifest_hash: str,
    policy_version: str,
) -> tuple[SessionReport, ...]:
    reports: list[SessionReport] = []
    for market, llm in zip(markets, llm_ledgers, strict=True):
        for ledger in market.mirror_ledgers:
            for index, day in enumerate(ledger.days):
                reports.append(_session_report(market, ledger, llm,
                    incidents, executions, recoveries, manifest_hash,
                    policy_version, index, day.session))
    return tuple(reports)


def _session_report(
    market: MarketOperation, ledger: MirrorLedger, llm: LlmOutcomeLedger,
    incidents: tuple[IncidentRecord, ...], executions: tuple[KillExecution, ...],
    recoveries: tuple[RecoveryEvidence, ...], manifest_hash: str,
    policy_version: str, index: int, session: date,
) -> SessionReport:
    days = ledger.days[:index + 1]
    points = market.paired_series.points[:index + 1]
    llm_prefix = LlmOutcomeLedger(market=llm.market,
        outcomes=tuple(item for item in llm.outcomes if item.session == session))
    account_incidents = tuple(item for item in incidents
        if ledger.account.account_namespace in item.affected_accounts
        and item.session <= session)
    account_hashes = {item.incident_hash for item in account_incidents}
    recovered_hashes = {item.incident_hash for item in recoveries
        if item.incident_hash in account_hashes
        and item.recovery_session <= session}
    active = tuple(item.overlay for item in account_incidents
        if item.incident_hash not in recovered_hashes)
    data_triggers = {TriggerKind.SYMBOL_DATA, TriggerKind.MARKET_CALENDAR,
        TriggerKind.MARKET_SOURCE}
    active_data = tuple(item.incident_hash for item in account_incidents
        if item.incident_hash not in recovered_hashes
        and item.trigger in data_triggers)
    account_executions = tuple(item for execution in executions
        if execution.boundary_at.date() <= session
        for item in execution.accounts
        if item.account_namespace == ledger.account.account_namespace)
    completed = sum(item.completed_trades for item in days)
    account = days[-1].evidence.account_snapshot
    final_cash = decimal_value(account.cash)
    initial_cash = decimal_value(ledger.initial_cash)
    costs = sum((item.execution_cost for item in days), Decimal(0))
    summary = summarize_llm(llm_prefix)
    return SessionReport(schema_version="v15.session_report.2",
        market=market.market, arm=ledger.account.arm, session=session,
        manifest_hash=manifest_hash, policy_version=policy_version,
        data_health=DataHealth(complete=not active_data,
            degraded=bool(active_data),
            fallback_count=summary.quant_fallback_count,
            supersede_count=0, reconciled=not active_data,
            active_incident_hashes=active_data,
            recovered_incident_hashes=tuple(sorted(recovered_hashes))),
        activity=ActivityCounts(candidates=len(llm_prefix.outcomes),
            no_trade=sum(item.completed_trades == 0 for item in days),
            orders=completed, partial_fills=0,
            cancellations=sum(len(item.cancelled_intents)
                for item in account_executions)),
        exposure=Exposure(gross=Decimal(0), net=Decimal(0),
            sector=Decimal(0), correlation=Decimal(0),
            position_count=len(account.positions)),
        pnl=PnlBreakdown(realized=final_cash - initial_cash,
            unrealized=Decimal(0), commission=Decimal(0), tax=Decimal(0),
            spread=Decimal(0), slippage=Decimal(0), participation=Decimal(0),
            borrow=Decimal(0), locate=Decimal(0),
            other_execution_cost=costs), llm=summary,
        kill_overlay=dominant_overlay(active) if active else KillOverlay.CLEAR,
        recovery_state="active" if active else "recovered"
            if recovered_hashes else "clear",
        paired=PairedStatus(common_days=len(points),
            orb_completed_trades=sum(item.orb_completed_trades for item in points),
            router_completed_trades=sum(item.router_completed_trades for item in points),
            sample_sufficient=len(points) >= 60
                and sum(item.orb_completed_trades for item in points) >= 300
                and sum(item.router_completed_trades for item in points) >= 300))
