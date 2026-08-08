from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from src.v8.fixture import load_json
from .risk_acceptance_cases import EXPECTED_PROBES, build_scenarios, mutation_probes
from src.v8.risk_authority import (
    activate_switch,
    build_acknowledgement,
    reset_switch,
    verify_acknowledgement,
    verify_switch_chain,
)
from src.v8.risk_compiler import compile_risk_fixture
from src.v8.risk_ledger import RiskLedger, append_risk
from src.v8.risk_json import JsonValue, canonical_hash, canonical_json, model_json
from src.v8.risk_evaluator import evaluate_risk
from src.v8.risk_models import AckVerificationContext, ResetAttempt
from src.v8.risk_verifier import verify_risk_artifact

HAPPY_FIXTURE_PATH: Final = Path(
    "docs/specs/v8/fixtures/prd04-risk-controls-happy.json"
)
_FIXTURE_ROOT: Final = HAPPY_FIXTURE_PATH.parent
_FAILURE_PATHS: Final = (
    "prd04-risk-controls-cash-failure.json",
    "prd04-risk-controls-stale-quote-failure.json",
    "prd04-risk-controls-market-closed-failure.json",
    "prd04-risk-controls-position-failure.json",
    "prd04-risk-controls-daily-loss-failure.json",
    "prd04-risk-controls-active-switch-failure.json",
    "prd04-risk-controls-unreadable-switch-failure.json",
)
_AUTHORITY_PATHS: Final = (
    "prd04-risk-acknowledgement-authority.json",
    "prd04-risk-reset-authority.json",
)
_REQUIRED_EVIDENCE: Final = (
    "root_cause_recorded",
    "fresh_quote_evidence",
    "market_calendar_evidence",
    "daily_loss_evidence_when_applicable",
    "hash_chain_recomputed",
    "forbidden_fields_absent",
)
_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def _failure_fields_present(value: JsonValue) -> bool:
    if not isinstance(value, dict):
        return False
    expected_values: list[dict[str, JsonValue]] = []
    expected = value.get("expected_result")
    if isinstance(expected, dict):
        expected_values.append(expected)
    cases = value.get("failure_cases")
    if isinstance(cases, list):
        expected_values.extend(
            expected
            for item in cases
            if isinstance(item, dict)
            and isinstance((expected := item.get("expected_result")), dict)
        )
    required = {
        "fail_closed",
        "ack_can_override",
        "dry_run_request_allowed",
        "reset_required",
        "reset_authority",
    }
    return bool(expected_values) and all(
        required.issubset(item) and item.get("fail_closed") is True
        for item in expected_values
    )


def _reset_attempt(requester: str, activated_at: datetime) -> ResetAttempt:
    return ResetAttempt(
        requester_ref=requester,
        reviewer_refs=("reviewer_01", "reviewer_02"),
        permissions=("risk.kill_switch.reset", "risk.kill_switch.reset"),
        evidence=_REQUIRED_EVIDENCE,
        requested_at=activated_at,
        reviewed_at=activated_at + timedelta(minutes=15),
        cooldown_seconds=900,
        chain_recomputed=True,
    )


def run_risk_acceptance() -> JsonValue:
    fixture = load_json(HAPPY_FIXTURE_PATH)
    compiled = compile_risk_fixture(fixture)
    artifact = compiled.artifact
    assert artifact is not None
    verified = verify_risk_artifact(model_json(artifact))
    scenarios = build_scenarios(artifact.request)
    probes = mutation_probes(fixture, artifact, scenarios)
    first = append_risk(RiskLedger.empty(), artifact)
    duplicate = append_risk(first.ledger, artifact)
    warning_decision = evaluate_risk(
        artifact.request.model_copy(update={"ack_required_reasons": ("concentration_notice",)})
    )
    acknowledged_at = artifact.request.inputs.market_hours.checked_at
    acknowledgement = build_acknowledgement(
        warning_decision,
        "operator_redacted_01",
        "concentration_notice",
        acknowledged_at,
        artifact.request.inputs.quote.quote_expires_at,
    )

    activated_at = datetime.fromisoformat("2026-08-06T09:06:00+09:00")
    switch = activate_switch(
        "market",
        "KR",
        "operator_risk_admin_01",
        activated_at,
        "manual_halt",
        {"evidence": artifact.source_input_hash},
    )
    reset_attempt = _reset_attempt("operator_reset_01", activated_at)
    reset = reset_switch(switch, (switch,), reset_attempt)
    self_reset = reset_switch(switch, (switch,), _reset_attempt("reviewer_01", activated_at))
    forbidden_switch = activate_switch(
        "market",
        "KR",
        "operator_risk_admin_01",
        activated_at,
        "manual_halt",
        {"account_number": artifact.source_input_hash},
    )
    malformed_source_switch = activate_switch(
        "market",
        "KR",
        "operator_risk_admin_01",
        activated_at,
        "manual_halt",
        {"evidence": "paper_account_01"},
    )
    missing_head = switch.model_copy(
        update={"prev_record_hash": artifact.source_input_hash, "record_hash": "sha256:pending"}
    )
    missing_head = missing_head.model_copy(
        update={"record_hash": canonical_hash(model_json(missing_head, exclude={"record_hash"}))}
    )
    inactive_head = switch.model_copy(
        update={"switch_status": "inactive", "record_hash": "sha256:pending"}
    )
    inactive_head = inactive_head.model_copy(
        update={"record_hash": canonical_hash(model_json(inactive_head, exclude={"record_hash"}))}
    )
    malformed_head = switch.model_copy(update={"record_hash": "sha256:invalid"})
    invalid_stream_resets = (
        reset_switch(switch, (), reset_attempt),
        reset_switch(switch, (missing_head,), reset_attempt),
        reset_switch(switch, (inactive_head,), reset_attempt),
        reset_switch(switch, (malformed_head,), reset_attempt),
    )
    fixture_values = [load_json(_FIXTURE_ROOT / name) for name in _FAILURE_PATHS]
    all_paths = tuple(_FAILURE_PATHS) + tuple(_AUTHORITY_PATHS)
    canonical_fixtures = all(
        (_FIXTURE_ROOT / name).read_bytes().rstrip(b"\n")
        == canonical_json(load_json(_FIXTURE_ROOT / name))
        for name in all_paths
    )
    decisions = scenarios.documented_failures
    decision_json = model_json(artifact.decision)
    assert isinstance(fixture, dict)
    claimed_decision = fixture.get("risk_decision")
    assert isinstance(claimed_decision, dict)
    checks: dict[str, bool] = {
        "happy_allowed_dry_run_only": artifact.decision.risk_status == "allowed"
        and artifact.decision.next_allowed_destination == "broker_dry_run"
        and verified.verification_status == "pass",
        "eight_failure_outcomes": all(
            decision.risk_status in {"blocked", "kill_switch_active"}
            and decision.fail_closed
            and not decision.dry_run_request_allowed
            for decision in decisions
        ),
        "documented_block_codes": tuple(decision.blocking_reasons[0] for decision in decisions)
        == (
            "cash_insufficient",
            "stale_quote",
            "market_closed",
            "position_insufficient",
            "max_positions_reached",
            "daily_loss_limit_hit",
            "kill_switch_active",
            "kill_switch_unreadable",
        ),
        "normative_mutation_probes": probes == EXPECTED_PROBES,
        "required_cash_bound_to_buy_estimates": probes["required_cash_understatement"]
        == "json_malformed",
        "idempotent_retry_no_duplicate": duplicate.appended_count == 0
        and len(duplicate.ledger.entries) == 1,
        "source_hashes_recomputed": set(artifact.decision.source_hashes)
        == {"proposal", "portfolio", "quote", "calendar", "policy", "kill_switch"},
        "claimed_outcome_hashes_not_trusted": artifact.decision.risk_decision_id
        != claimed_decision.get("risk_decision_id")
        and artifact.decision.record_hash != claimed_decision.get("record_hash")
        and artifact.decision.source_hashes != claimed_decision.get("source_hashes"),
        "risk_status_only": isinstance(decision_json, dict)
        and "state" not in decision_json
        and "stage" not in decision_json,
        "ack_cannot_override_blockers": probes["ack_override_blocker"] == "blocked_preserved",
        "acknowledgement_verified_for_warning_only": acknowledgement is not None
        and verify_acknowledgement(
            warning_decision,
            acknowledgement,
            AckVerificationContext(
                operator_ref="operator_redacted_01", observed_at=acknowledged_at
            ),
        )
        and warning_decision.risk_status == "requires_ack",
        "switch_chain_verified": verify_switch_chain((switch,)),
        "switch_forbidden_payloads_rejected": not verify_switch_chain((forbidden_switch,))
        and not verify_switch_chain((malformed_source_switch,)),
        "reset_two_reviewers_evidence_chain_cooldown": reset.reset_status == "approved"
        and len(reset.records) == 3
        and tuple(record.switch_status for record in reset.records)
        == ("reset_requested", "reset_approved", "inactive")
        and verify_switch_chain((switch, *reset.records)),
        "reset_self_approval_blocked": self_reset.reset_status == "blocked",
        "reset_invalid_streams_fail_closed": all(
            result.reset_status == "blocked"
            and not result.records
            and result.error_code == "reset_requirements_not_met"
            for result in invalid_stream_resets
        ),
        "failure_fixture_fields": all(_failure_fields_present(value) for value in fixture_values),
        "canonical_fixture_documents": canonical_fixtures,
        "strict_no_side_effects": all(
            not decision.real_order_created and not decision.portfolio_mutated
            for decision in decisions
        ),
    }
    return _JSON.validate_python(
        {
            "verification_status": "pass" if all(checks.values()) else "fail",
            "acceptance_count": len(checks),
            "checks": checks,
            "failure_probes": probes,
        }
    )
