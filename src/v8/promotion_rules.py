from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Final

from src.v8.promotion_models import (
    AutomationEvidence,
    IncidentDisposition,
    IncidentEvidence,
    ObservationWindow,
    PromotionErrorCode,
    PromotionRequest,
    RepromotionEvidence,
)
from src.v8.risk_json import JsonValue, canonical_hash, model_json

_ALLOWED_SYMBOLS: Final = frozenset({"005930", "000660"})
_GENESIS: Final = "sha256:genesis"
_SOURCE_HASHES: Final = (
    "sha256:2542dfc02c813ed3856c52ce4d620349e7d149f5bd466f94dc8ae9ee479e5de2",
    "sha256:41f0fbb4ec7b68e8c3aaf4a92ec42ac040863528e155aec6342d57e526f7843c",
    "sha256:4545fac1242196432741351349698e528a7d5da0ff57a43613480d70c6a06a83",
    "sha256:e7d775aa678d5dcb92f24dfc9c9f456d0228a35a217c17bd10bc4414e303cfb5",
)


def observation_error(window: ObservationWindow) -> PromotionErrorCode | None:
    thresholds_pass = (
        window.paper_sessions >= 20
        and window.paper_order_count >= 30
        and window.live_contamination_count == 0
        and window.hash_chain_break_count == 0
        and window.reconciliation_mismatch_rate == Decimal("0.00")
        and window.dry_run_attempts >= 10
        and window.malformed_response_count == 0
        and window.duplicate_idempotency_count == 0
        and window.stale_quote_blocked_count == window.expected_stale_probes
        and window.approval_required_sessions >= 5
        and window.approval_required_count >= 10
        and window.blocker_override_count == 0
        and window.risk_false_allow_count == 0
        and window.incident_count == 0
    )
    if not thresholds_pass:
        return PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS
    if window.observed_at > window.fresh_through:
        return PromotionErrorCode.STALE_SOURCE
    return None


def policy_seed(request: PromotionRequest) -> JsonValue:
    return {
        "eligible_scope": request.eligible_scope.model_dump(mode="json"),
        "blast_radius_caps": request.blast_radius_caps.model_dump(mode="json"),
        "incident_policy": request.incident_policy.model_dump(mode="json"),
    }


def threshold_seed(window: ObservationWindow) -> JsonValue:
    return window.model_dump(mode="json")


def source_error(request: PromotionRequest) -> PromotionErrorCode | None:
    bindings = request.source_bindings
    observed = (
        bindings.paper_ledger,
        bindings.approval_dry_run,
        bindings.order_reconciliation,
        bindings.risk_controls,
    )
    if observed != _SOURCE_HASHES:
        return PromotionErrorCode.STALE_SOURCE
    if bindings.promotion_policy != canonical_hash(policy_seed(request)):
        return PromotionErrorCode.DIRTY_INPUT
    if bindings.observation_window != canonical_hash(threshold_seed(request.observation_window)):
        return PromotionErrorCode.THRESHOLD_TAMPERED
    proof = request.kill_switch_proof
    switch_seed: JsonValue = {
        "kill_switch_id": proof.kill_switch_id,
        "scope": proof.scope,
        "scope_value": proof.scope_value,
        "switch_status": proof.switch_status,
        "hash_chain_verified": proof.hash_chain_verified,
    }
    if bindings.kill_switch != canonical_hash(switch_seed) or proof.record_hash != bindings.kill_switch:
        return PromotionErrorCode.DIRTY_INPUT
    return None


def promotion_error(request: PromotionRequest) -> PromotionErrorCode | None:
    if (
        request.promotion_status_before != "approval_required"
        or request.promotion_status_after != "limited_automation"
        or request.requested_by == request.approved_by
    ):
        return PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS
    caps = request.blast_radius_caps
    if request.effective_at >= request.expires_at:
        return PromotionErrorCode.THRESHOLD_TAMPERED
    session_date = request.effective_at.date()
    duration_sessions = 0
    while session_date < request.expires_at.date():
        if session_date.weekday() < 5:
            duration_sessions += 1
        session_date += timedelta(days=1)
    if duration_sessions > caps.max_duration_trading_sessions:
        return PromotionErrorCode.THRESHOLD_TAMPERED
    if (
        caps.per_order_notional_krw != Decimal("100000.00")
        or caps.per_symbol_daily_notional_krw != Decimal("200000.00")
        or caps.total_daily_notional_krw != Decimal("300000.00")
        or caps.concurrent_requests != 1
        or caps.traffic_share_pct != Decimal("5.00")
        or caps.max_eligible_symbols != 2
        or caps.max_duration_trading_sessions != 5
    ):
        return PromotionErrorCode.THRESHOLD_TAMPERED
    scope = request.eligible_scope
    if (
        tuple(sorted(scope.symbols)) != tuple(sorted(_ALLOWED_SYMBOLS))
        or scope.markets != ("KR",)
        or set(scope.sides) != {"BUY", "SELL"}
        or scope.order_types != ("limit",)
    ):
        return PromotionErrorCode.INELIGIBLE_SCOPE
    if request.kill_switch_proof.switch_status != "inactive" or not request.kill_switch_proof.hash_chain_verified:
        return PromotionErrorCode.MISLEADING_PROMOTION_SUCCESS
    return source_error(request) or observation_error(request.observation_window)


def sample_selected(decision_id: str, evidence: AutomationEvidence, share: Decimal) -> bool:
    seed: JsonValue = {
        "promotion_decision_id": decision_id,
        "proposal_id": evidence.proposal_id,
        "trading_session": evidence.trading_session,
    }
    bucket = int(canonical_hash(seed)[7:15], 16) % 10_000
    return bucket < int(share * 100)


def automation_error(
    request: PromotionRequest, evidence: AutomationEvidence, decision_id: str
) -> PromotionErrorCode | None:
    session_date = date.fromisoformat(evidence.trading_session.partition("/")[0])
    if not request.effective_at.date() <= session_date < request.expires_at.date():
        return PromotionErrorCode.STALE_SOURCE
    scope = request.eligible_scope
    if (
        evidence.ticker not in scope.symbols
        or evidence.market not in scope.markets
        or evidence.side not in scope.sides
        or evidence.order_type not in scope.order_types
        or (evidence.side == "SELL" and not evidence.risk_reducing)
        or not evidence.market_open
        or not evidence.quote_fresh
        or evidence.risk_status != "allowed"
    ):
        return PromotionErrorCode.INELIGIBLE_SCOPE
    if (
        evidence.destination not in {"broker_dry_run", "internal_dry_run"}
        or evidence.live_submission
        or evidence.real_order_created
        or evidence.portfolio_mutated
    ):
        return PromotionErrorCode.REAL_ORDER_MUTATION
    caps = request.blast_radius_caps
    total = evidence.estimated_notional + evidence.estimated_fee + evidence.estimated_tax
    if (
        total > caps.per_order_notional_krw
        or evidence.symbol_daily_notional_before + total > caps.per_symbol_daily_notional_krw
        or evidence.total_daily_notional_before + total > caps.total_daily_notional_krw
        or evidence.concurrent_requests >= caps.concurrent_requests
    ):
        return PromotionErrorCode.BLAST_RADIUS_EXCEEDED
    if not sample_selected(decision_id, evidence, caps.traffic_share_pct):
        return PromotionErrorCode.TRAFFIC_NOT_SELECTED
    return None


def repromotion_error(evidence: RepromotionEvidence) -> PromotionErrorCode | None:
    caps = evidence.proposed_caps
    prior = evidence.prior_caps
    valid = (
        bool(evidence.root_cause)
        and bool(evidence.affected_scope)
        and evidence.corrective_artifact_hash.startswith("sha256:")
        and evidence.clean_sessions >= 5
        and caps.per_order_notional_krw <= prior.per_order_notional_krw / 2
        and caps.per_symbol_daily_notional_krw <= prior.per_symbol_daily_notional_krw / 2
        and caps.total_daily_notional_krw <= prior.total_daily_notional_krw / 2
        and caps.traffic_share_pct <= prior.traffic_share_pct / 2
        and len({evidence.requested_by, evidence.approved_by, evidence.incident_operator}) == 3
        and evidence.kill_switch_proof.switch_status == "inactive"
        and evidence.kill_switch_proof.hash_chain_verified
        and evidence.replay_clean
        and evidence.same_scope_incident_count == 0
    )
    return None if valid else PromotionErrorCode.REPROMOTION_BLOCKED


def incident_disposition(reason_code: str) -> IncidentDisposition | None:
    if reason_code in {
        "forbidden_credential_field", "live_destination", "real_order_attempt",
        "unlimited_cap", "kill_switch_unreadable",
    }:
        return IncidentDisposition("critical", "paper", "global", 30, 120, True)
    if reason_code in {
        "cap_breach", "stale_quote_falsely_fresh", "market_closed_falsely_open",
        "risk_blocker_marked_safe",
    }:
        return IncidentDisposition("high", "dry_run", "ticker", 60, 300, True)
    if reason_code in {
        "duplicate_promotion_record", "delayed_dry_run_response",
        "approval_evidence_missing",
    }:
        return IncidentDisposition("medium", "approval_required", "ticker", 300, 900, True)
    if reason_code == "non_blocking_evidence_lag":
        return IncidentDisposition("low", "limited_automation", "none", 0, 86_400, False)
    return None


def incident_sla(
    evidence: IncidentEvidence, disposition: IncidentDisposition
) -> tuple[bool, bool]:
    stop_met = (
        not disposition.automatic
        or evidence.new_automation_stopped_at
        <= evidence.detected_at + timedelta(seconds=disposition.stop_sla_seconds)
    )
    append_met = evidence.incident_appended_at <= evidence.detected_at + timedelta(
        seconds=disposition.append_sla_seconds
    )
    return stop_met, append_met


def incident_switch_seed(
    evidence: IncidentEvidence, disposition: IncidentDisposition
) -> JsonValue:
    return {
        "incident": canonical_hash(model_json(evidence)),
        "scope": disposition.switch_scope,
        "scope_value": evidence.ticker if disposition.switch_scope == "ticker" else None,
        "switch_status": "active" if disposition.automatic else "inactive",
    }


def genesis_hash() -> str:
    return _GENESIS
