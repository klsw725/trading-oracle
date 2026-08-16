from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from .contract import StrictModel
from .states import KillOverlay


class DataHealth(StrictModel):
    complete: bool
    degraded: bool
    fallback_count: int
    supersede_count: int
    reconciled: bool
    active_incident_hashes: Annotated[tuple[str, ...], Field(strict=False)]
    recovered_incident_hashes: Annotated[tuple[str, ...], Field(strict=False)]


class ActivityCounts(StrictModel):
    candidates: int
    no_trade: int
    orders: int
    partial_fills: int
    cancellations: int


class Exposure(StrictModel):
    gross: Decimal
    net: Decimal
    sector: Decimal
    correlation: Decimal
    position_count: int


class PnlBreakdown(StrictModel):
    realized: Decimal
    unrealized: Decimal
    commission: Decimal
    tax: Decimal
    spread: Decimal
    slippage: Decimal
    participation: Decimal
    borrow: Decimal
    locate: Decimal
    other_execution_cost: Decimal


class LlmOperations(StrictModel):
    timeout_count: int
    abstain_count: int
    schema_failure_count: int
    circuit_open: bool
    quant_fallback_count: int
    mixed_success_count: int


class PairedStatus(StrictModel):
    common_days: int
    orb_completed_trades: int
    router_completed_trades: int
    sample_sufficient: bool


class SessionReport(StrictModel):
    schema_version: Literal["v15.session_report.2"]
    market: Literal["KR", "US"]
    arm: str
    session: date
    manifest_hash: str
    policy_version: str
    data_health: DataHealth
    activity: ActivityCounts
    exposure: Exposure
    pnl: PnlBreakdown
    llm: LlmOperations
    kill_overlay: KillOverlay
    recovery_state: str
    paired: PairedStatus


def verify_observability(report: SessionReport) -> None:
    failures = (report.llm.timeout_count + report.llm.abstain_count
        + report.llm.schema_failure_count)
    if report.llm.quant_fallback_count < failures \
            or report.llm.mixed_success_count > report.activity.candidates - failures \
            or report.data_health.degraded and (report.data_health.complete
                or report.data_health.reconciled):
        from .contract import V15Failure, V15FailureCode
        raise V15Failure(V15FailureCode.COMPARISON_INVALID, "llm_observability")
