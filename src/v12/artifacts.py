from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from src.v11.models import CostBreakdown, Decision, LedgerEvent, OrderAction, RiskResult

from .models import ArtifactRef, BorrowEligibility, CausalSizingObservation, ExecutionSnapshot, Market, Scenario, Side, StrategyInput, StrictModel


class FeatureSnapshot(StrictModel):
    cutoff: datetime
    values: dict[str, Decimal]
    input_hash: str


class Candidate(StrictModel):
    candidate_id: str
    market: Market
    symbol: str
    strategy_id: str
    strategy_version: Literal["v12.2"]
    parameter_set_id: str
    side: Side
    signal_cutoff: datetime
    feature_snapshot_hash: str
    deterministic_score: Decimal = Field(ge=0, le=1)
    entry_boundary: Literal["first_1m_after_decision"]
    exit_policy: Literal["close_minus_5_or_forced"]
    eligibility_refs: Annotated[tuple[ArtifactRef, ...], Field(strict=False)]
    lifecycle: Literal["pre_portfolio_candidate", "execution_feasible_candidate"]


class Evaluation(StrictModel):
    case_id: str
    scenario: Scenario
    strategy_id: str
    parameter_set_id: str
    candidate: Candidate | None
    result_code: str
    feature_evaluated: bool
    bound_input: StrategyInput | None = None


class GateComputation(StrictModel):
    passed: bool
    components: dict[str, Decimal]
    features: dict[str, Decimal]


class ArmManifest(StrictModel):
    arm_id: str
    account_arm_id: str
    owner_namespace: str
    strategy_id: str
    strategy_version: Literal["v12.2"]
    active_parameter_set_id: str
    source_fixture_hash: str
    registry_hash: str
    cost_policy_hash: str
    manifest_hash: str


class EmissionState(StrictModel):
    emitted_keys: Annotated[tuple[str, ...], Field(strict=False)]
    last_cutoffs: dict[str, Annotated[datetime, Field(strict=False)]]
    last_gate_states: dict[str, bool]


class FillArtifact(StrictModel):
    intent_id: str
    target_at: Annotated[datetime, Field(strict=False)]
    side: str
    action: Annotated[OrderAction, Field(strict=False)]
    requested_quantity: int
    filled_quantity: int
    cancelled_quantity: int
    price: str
    state: Literal["partial", "complete", "cancelled"]
    costs: CostBreakdown


class TradeAttribution(StrictModel):
    manifest: ArmManifest
    candidate: Candidate
    decision: Decision
    risk: RiskResult
    arm_intent_id: str
    v11_intent_id: str
    fill: FillArtifact
    entry_costs: CostBreakdown
    causal_sizing: CausalSizingObservation
    execution_snapshot: ExecutionSnapshot
    borrow: BorrowEligibility
    risk_kill_at: datetime | None
    regular_close: datetime
    exit_reason: Literal["session_close", "short_recall", "risk_kill"]
    events: Annotated[tuple[LedgerEvent, ...], Field(strict=False)]
    event_bytes_hash: str
    ledger_hash: str


class RunArtifacts(StrictModel):
    manifest_hash: str
    manifests: Annotated[tuple[ArmManifest, ...], Field(strict=False)]
    evaluations: Annotated[tuple[Evaluation, ...], Field(strict=False)]
    emission_state: EmissionState
    trades: Annotated[tuple[TradeAttribution, ...], Field(strict=False)]
