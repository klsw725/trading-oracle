from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from src.v4.models import JsonValue, canonical_json
from src.v11.canonical import canonical_hash, model_json
from src.v11.costs import execution_costs, freeze_policy
from src.v11.decisions import target_minute, verify_intent_timing
from src.v11.execution_ledger import record_fill
from src.v11.fills import simulate_fill, verify_fill
from src.v11.identity import intent_id
from src.v11.models import Decision, EventType, Market, OrderAction, Position, RiskResult, Side
from src.v11.risk import check_risk
from src.v11.shorts import borrow_cost
from src.v11.sizing import causal_quantity

from .artifacts import ArmManifest, Candidate, FillArtifact, TradeAttribution
from .integrity import verify_attribution, verify_candidate
from .execution_events import record_close_exit
from .models import ExecutionInputs, StrategyInput, V12ContractError


def make_execution_feasible(candidate: Candidate, source: StrategyInput,
                            inputs: ExecutionInputs, manifest: ArmManifest) -> tuple[Candidate, Decision, RiskResult]:
    verify_candidate(candidate)
    snapshot = source.execution_snapshot
    causal = source.causal_sizing
    verify_causal_timing(candidate, source)
    ready = source.watermark_at + timedelta(seconds=2)
    decision_body: dict[str, JsonValue] = {"candidate_id": candidate.candidate_id,
        "arm_id": manifest.arm_id, "account_arm_id": manifest.account_arm_id}
    decision = Decision(decision_id=f"v12:decision:{canonical_hash(decision_body)[7:27]}",
        candidate_id=candidate.candidate_id, router_decision_id=f"deterministic:{manifest.manifest_hash}",
        strategy_id=candidate.strategy_id, strategy_version=candidate.strategy_version,
        market=Market(candidate.market.value), symbol=candidate.symbol, sector=source.sector,
        side=Side(candidate.side.value), action="open", cutoff=candidate.signal_cutoff,
        watermark_at=source.watermark_at, decision_ready_at=ready,
        deterministic_score=str(candidate.deterministic_score), market_input_hash=candidate.feature_snapshot_hash)
    target = target_minute(decision)
    verify_intent_timing(decision, ready, target)
    if snapshot.target_at != target:
        raise V12ContractError("V12_EXECUTION_SNAPSHOT_TARGET", manifest.arm_id)
    frozen_policy = freeze_policy(inputs.cost_policy, source.session_date.isoformat())
    turnovers = tuple(str(value) for value in causal.prior_turnovers)
    quantity, _ = causal_quantity(inputs.account, str(causal.close), turnovers)
    action = OrderAction.BUY if decision.side is Side.LONG else OrderAction.SHORT
    expected = execution_costs(frozen_policy, decision.market, action,
        str(Decimal(quantity) * causal.close)).total
    risk = check_risk(inputs.account, decision, quantity, str(causal.close), None,
        gates=inputs.gates, expected_cost=expected)
    if risk.state != "accepted" or risk.reservation is None:
        raise V12ContractError("V12_EXECUTION_INFEASIBLE", risk.reason_code)
    return candidate.model_copy(update={"lifecycle": "execution_feasible_candidate"}), decision, risk


def verify_causal_timing(candidate: Candidate, source: StrategyInput) -> None:
    if not source.causal_sizing.observed_at <= candidate.signal_cutoff < source.execution_snapshot.target_at:
        raise V12ContractError("V12_CAUSAL_LOOKAHEAD", candidate.candidate_id)


def execute(candidate: Candidate, source: StrategyInput, inputs: ExecutionInputs,
            manifest: ArmManifest) -> TradeAttribution:
    if candidate.lifecycle != "execution_feasible_candidate":
        raise V12ContractError("V12_CANDIDATE_LIFECYCLE", candidate.candidate_id)
    if manifest.active_parameter_set_id != candidate.parameter_set_id:
        raise V12ContractError("V12_MANIFEST_PARAMETER", manifest.arm_id)
    feasible, decision, risk_value = make_execution_feasible(
        candidate.model_copy(update={"lifecycle": "pre_portfolio_candidate"}), source, inputs, manifest)
    if feasible != candidate:
        raise V12ContractError("V12_FEASIBLE_CANDIDATE_MISMATCH", manifest.arm_id)
    risk = risk_value
    snapshot = source.execution_snapshot
    target = snapshot.target_at
    frozen_policy = freeze_policy(inputs.cost_policy, source.session_date.isoformat())
    quantity = risk.quantity
    action = OrderAction.BUY if decision.side is Side.LONG else OrderAction.SHORT
    fill = simulate_fill(intent_id(decision), decision.market, decision.side, quantity,
        snapshot.volume, str(snapshot.open), target, frozen_policy, action)
    verify_fill(fill, snapshot.volume)
    position = Position(symbol=decision.symbol, side=decision.side, sector=decision.sector,
        quantity=fill.filled_quantity, mark_price=fill.price)
    events = record_fill((), decision, fill, position, target, manifest.manifest_hash)
    if fill.cancelled_quantity:
        from src.v11.ledger import append_event
        events = append_event(events, EventType.RECONCILED, fill.intent_id, target,
            {"semantic_key": "entry_reconciled"}, manifest.manifest_hash)
    borrow = source.borrow
    if borrow is None:
        raise V12ContractError("V12_EXECUTION_BORROW_MISSING", manifest.arm_id)
    recalled_at = borrow.recalled_at if decision.side is Side.SHORT else None
    if recalled_at is not None and not target < recalled_at < source.regular_close:
        raise V12ContractError("V12_SHORT_RECALL_TIME", manifest.arm_id)
    risk_kill_at = source.risk_kill_at
    if risk_kill_at is not None and not target < risk_kill_at < source.regular_close:
        raise V12ContractError("V12_RISK_KILL_TIME", manifest.arm_id)
    forced_at = risk_kill_at if risk_kill_at is not None else recalled_at
    exit_reason = ("risk_kill" if risk_kill_at is not None else "short_recall"
        if recalled_at is not None else "session_close")
    exit_signal_at = (source.regular_close - timedelta(minutes=5)
        if forced_at is None else forced_at)
    exit_fill_at = (source.regular_close - timedelta(minutes=4)
        if forced_at is None else forced_at.replace(second=0, microsecond=0) + timedelta(minutes=1))
    holding_days = max(1, (exit_fill_at.date() - target.date()).days)
    executed_notional = Decimal(position.quantity) * Decimal(position.mark_price)
    borrow_fee = (borrow_cost(str(executed_notional), str(borrow.annual_fee), holding_days)
        if decision.side is Side.SHORT else "0")
    events = record_close_exit(events, f"{fill.intent_id}:exit", position,
        exit_signal_at, exit_fill_at, exit_reason, manifest.manifest_hash,
        frozen_policy, decision.market, borrow_fee)
    arm_intent = f"v12:intent:{canonical_hash({'arm': manifest.account_arm_id, 'v11': fill.intent_id})[7:]}"
    event_hash = canonical_hash(canonical_json([model_json(item) for item in events]).decode())
    fill_artifact = FillArtifact(intent_id=fill.intent_id, target_at=fill.target_at,
        side=fill.side.value, action=fill.action, requested_quantity=fill.requested_quantity,
        filled_quantity=fill.filled_quantity, cancelled_quantity=fill.cancelled_quantity,
        price=fill.price, state=fill.state, costs=fill.costs)
    trade = TradeAttribution(manifest=manifest, candidate=candidate, decision=decision,
        risk=risk, arm_intent_id=arm_intent, v11_intent_id=fill.intent_id,
        fill=fill_artifact, entry_costs=fill.costs, causal_sizing=source.causal_sizing,
        execution_snapshot=source.execution_snapshot, borrow=borrow,
        risk_kill_at=risk_kill_at, regular_close=source.regular_close,
        exit_reason=exit_reason, events=events,
        event_bytes_hash=event_hash, ledger_hash="sha256:pending")
    trade = trade.model_copy(update={"ledger_hash": canonical_hash(
        trade.model_dump(mode="json", exclude={"ledger_hash"}))})
    verify_attribution(trade, inputs.account)
    return trade
