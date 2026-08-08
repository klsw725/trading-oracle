from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from src.v8.fixture import load_json
from src.v8.promotion_compiler import HappyPromotionFixture, compile_incident_fixture, compile_promotion_fixture
from src.v8.promotion_ledger import PromotionLedger, append_promotion, complete_interrupted_incident
from src.v8.promotion_models import BlastRadiusCaps, IncidentRecord, PromotionArtifact, PromotionErrorCode, RepromotionEvidence
from src.v8.promotion_rules import (
    incident_disposition,
    repromotion_error,
    sample_selected,
    threshold_seed,
)
from .promotion_verifier import all_severity_records_verify, forged_automation_id_rejected, forged_incident_sla_rejected, forged_sample_rejected, verify_incident_record, verify_promotion_artifact
from src.v8.risk_json import JsonValue, canonical_hash, canonical_json, model_json

HAPPY_FIXTURE_PATH: Final = Path(
    "docs/specs/v8/fixtures/prd05-limited-automation-promotion-happy.json"
)
INCIDENT_FIXTURE_PATH: Final = Path(
    "docs/specs/v8/fixtures/prd05-limited-automation-promotion-incident.json"
)
_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def _code(value: JsonValue) -> str | None:
    error = compile_promotion_fixture(value).error_code
    return error.value if error is not None else None


def _record(value: JsonValue, key: str) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    child = value[key]
    assert isinstance(child, dict)
    return child


def _mutations(fixture: JsonValue, artifact: PromotionArtifact) -> dict[str, str | None]:
    malformed = deepcopy(fixture)
    assert isinstance(malformed, dict)
    _ = malformed.pop("schema_version")
    state = deepcopy(fixture)
    stage = deepcopy(fixture)
    forbidden_null = deepcopy(fixture)
    live_null = deepcopy(fixture)
    _record(state, "promotion_request")["state"] = None
    _record(stage, "promotion_request")["stage"] = None
    _record(forbidden_null, "promotion_request")["account_number"] = None
    _record(live_null, "promotion_request")["raw_broker_order_id"] = None
    threshold = deepcopy(fixture)
    threshold_window = _record(_record(threshold, "promotion_request"), "observation_window")
    threshold_window["paper_sessions"] = 19
    unlimited = deepcopy(fixture)
    _record(_record(unlimited, "promotion_request"), "blast_radius_caps")[
        "per_order_notional_krw"
    ] = "unlimited"
    misleading = deepcopy(fixture)
    misleading_request = _record(misleading, "promotion_request")
    misleading_window = _record(misleading_request, "observation_window")
    misleading_window["incident_count"] = 1
    misleading_request_bindings = _record(misleading_request, "source_bindings")
    window_model = artifact.decision.observation_window.model_copy(update={"incident_count": 1})
    misleading_request_bindings["observation_window"] = canonical_hash(
        threshold_seed(window_model)
    )
    real_order = deepcopy(fixture)
    _record(real_order, "automation_evidence")["live_submission"] = True
    live_destination = deepcopy(fixture)
    _record(live_destination, "automation_evidence")["destination"] = "broker_live"
    stale = deepcopy(fixture)
    _record(_record(stale, "promotion_request"), "source_bindings")["paper_ledger"] = (
        f"sha256:{'0' * 64}"
    )
    dirty = deepcopy(fixture)
    _record(_record(dirty, "promotion_request"), "source_bindings")["promotion_policy"] = (
        f"sha256:{'1' * 64}"
    )
    reversed_window = deepcopy(fixture)
    reversed_request = _record(reversed_window, "promotion_request")
    reversed_request["effective_at"] = "2026-08-13T15:30:00+09:00"
    reversed_request["expires_at"] = "2026-08-06T09:00:00+09:00"
    excessive_window = deepcopy(fixture)
    _record(excessive_window, "promotion_request")["expires_at"] = "2026-08-14T15:30:00+09:00"
    expired_evidence = deepcopy(fixture)
    _record(expired_evidence, "automation_evidence")["trading_session"] = (
        "2026-08-13/KR/regular"
    )
    return {
        "json_malformed": _code(malformed),
        "state_field_present": _code(state),
        "stage_field_present": _code(stage),
        "forbidden_key_even_null": _code(forbidden_null),
        "live_key_even_null": _code(live_null),
        "threshold_relaxed_in_place": _code(threshold),
        "cap_unlimited": _code(unlimited),
        "misleading_success": _code(misleading),
        "real_order_mutation": _code(real_order),
        "live_destination": _code(live_destination),
        "stale_source": _code(stale),
        "dirty_policy": _code(dirty),
        "reversed_promotion_window": _code(reversed_window),
        "excessive_promotion_window": _code(excessive_window),
        "expired_automation_session": _code(expired_evidence),
    }


def _repromotion(artifact: PromotionArtifact) -> tuple[bool, bool]:
    prior = artifact.decision.blast_radius_caps
    half = BlastRadiusCaps(
        per_order_notional_krw=prior.per_order_notional_krw / 2,
        per_symbol_daily_notional_krw=prior.per_symbol_daily_notional_krw / 2,
        total_daily_notional_krw=prior.total_daily_notional_krw / 2,
        concurrent_requests=1,
        traffic_share_pct=prior.traffic_share_pct / 2,
        max_eligible_symbols=1,
        max_duration_trading_sessions=5,
        unlimited_allowed=False,
    )
    clean = RepromotionEvidence(
        root_cause="stale quote freshness comparison reversed",
        affected_scope="ticker:005930",
        corrective_artifact_hash=f"sha256:{'2' * 64}",
        clean_sessions=5,
        prior_caps=prior,
        proposed_caps=half,
        requested_by="operator_recovery_03",
        approved_by="operator_independent_04",
        incident_operator="system.promotion_guard",
        kill_switch_proof=artifact.decision.kill_switch,
        replay_clean=True,
        same_scope_incident_count=0,
    )
    missing = clean.model_copy(update={"clean_sessions": 4})
    second_incident = clean.model_copy(update={"same_scope_incident_count": 1})
    return (
        repromotion_error(clean) is None
        and repromotion_error(missing) == PromotionErrorCode.REPROMOTION_BLOCKED,
        repromotion_error(second_incident) == PromotionErrorCode.REPROMOTION_BLOCKED,
    )


def run_promotion_acceptance() -> JsonValue:
    happy_value = load_json(HAPPY_FIXTURE_PATH)
    incident_value = load_json(INCIDENT_FIXTURE_PATH)
    happy = compile_promotion_fixture(happy_value)
    incident = compile_incident_fixture(incident_value)
    assert isinstance(happy.artifact, PromotionArtifact)
    assert isinstance(incident.artifact, IncidentRecord)
    artifact = happy.artifact
    happy_fixture = HappyPromotionFixture.model_validate(happy_value)
    incident_record = incident.artifact
    verified = verify_promotion_artifact(model_json(artifact))
    incident_verified = verify_incident_record(model_json(incident_record))
    first = append_promotion(PromotionLedger.empty(), artifact)
    duplicate = append_promotion(first.ledger, artifact)
    conflict_decision = artifact.decision.model_copy(
        update={"approved_by": "operator_conflicting_09"}
    )
    conflict_artifact = artifact.model_copy(update={"decision": conflict_decision})
    conflict = append_promotion(first.ledger, conflict_artifact)
    interrupted = complete_interrupted_incident(first.ledger, None)
    completed = complete_interrupted_incident(interrupted.ledger, incident_record)
    admitted_while_pending = append_promotion(interrupted.ledger, incident_record)
    pending_again = complete_interrupted_incident(completed.ledger, None)
    conflicting_incident = incident_record.model_copy(update={"evidence": incident_record.evidence.model_copy(update={"ticker": "000660"})})
    failed_completion = complete_interrupted_incident(pending_again.ledger, conflicting_incident)
    admitted_after_failed_completion = append_promotion(failed_completion.ledger, artifact)
    probes = _mutations(happy_value, artifact)
    repromotion, second_incident = _repromotion(artifact)
    critical = incident_disposition("real_order_attempt")
    high = incident_disposition("stale_quote_falsely_fresh")
    medium = incident_disposition("approval_evidence_missing")
    low = incident_disposition("non_blocking_evidence_lag")
    expected_probes: dict[str, str] = {
        "json_malformed": "json_malformed",
        "state_field_present": "forbidden_lifecycle_field",
        "stage_field_present": "forbidden_lifecycle_field",
        "forbidden_key_even_null": "real_order_mutation",
        "live_key_even_null": "real_order_mutation",
        "threshold_relaxed_in_place": "threshold_tampered",
        "cap_unlimited": "unlimited_automation_forbidden",
        "misleading_success": "misleading_promotion_success",
        "real_order_mutation": "real_order_mutation",
        "live_destination": "real_order_mutation",
        "stale_source": "stale_source",
        "dirty_policy": "dirty_input",
        "reversed_promotion_window": "threshold_tampered",
        "excessive_promotion_window": "threshold_tampered",
        "expired_automation_session": "stale_source",
    }
    evidence = artifact.automation_result
    incident_evidence = incident_record.evidence
    checks: dict[str, bool] = {
        "happy_promotes_exact_rung": artifact.decision.promotion_status_before
        == "approval_required" and artifact.promotion_status == "limited_automation",
        "deny_by_default_scope": set(artifact.decision.eligible_scope.symbols)
        == {"005930", "000660"} and artifact.decision.eligible_scope.order_types == ("limit",),
        "exact_blast_radius_caps": artifact.decision.blast_radius_caps
        == BlastRadiusCaps(
            per_order_notional_krw=Decimal("100000.00"),
            per_symbol_daily_notional_krw=Decimal("200000.00"),
            total_daily_notional_krw=Decimal("300000.00"), concurrent_requests=1,
            traffic_share_pct=Decimal("5.00"), max_eligible_symbols=2,
            max_duration_trading_sessions=5, unlimited_allowed=False,
        ),
        "observation_thresholds_derived": artifact.decision.observation_window.paper_sessions >= 20
        and artifact.decision.observation_window.dry_run_attempts >= 10,
        "deterministic_five_percent_sample": sample_selected(
            artifact.decision.promotion_decision_id,
            happy_fixture.automation_evidence,
            Decimal("5.00"),
        ),
        "dry_run_destination_only": evidence.destination == "broker_dry_run",
        "no_real_side_effects": not evidence.real_order_created and not evidence.portfolio_mutated,
        "source_ids_hashes_recomputed": verified.verification_status == "pass",
        "forged_sample_fails_closed": forged_sample_rejected(artifact),
        "forged_automation_id_fails_closed": forged_automation_id_rejected(artifact),
        "append_only_duplicate_no_append": duplicate.appended_count == 0
        and duplicate.returned_existing and len(duplicate.ledger.entries) == 1,
        "idempotency_conflict_no_append": conflict.error_code
        == PromotionErrorCode.IDEMPOTENCY_CONFLICT and conflict.appended_count == 0,
        "incident_high_rolls_to_dry_run": incident_record.severity == "high"
        and incident_record.promotion_status == "dry_run",
        "incident_sla_and_scoped_switch": incident_record.stop_sla_met
        and incident_record.append_sla_met and incident_record.kill_switch.scope == "ticker"
        and critical is not None and critical.promotion_status_after == "paper"
        and high is not None and high.promotion_status_after == "dry_run"
        and medium is not None and medium.promotion_status_after == "approval_required"
        and low is not None and low.automatic is False,
        "incident_blocks_without_side_effects": not incident_record.dry_run_request_allowed
        and not incident_evidence.real_order_created and not incident_evidence.portfolio_mutated,
        "incident_record_verifies": incident_verified.verification_status == "pass",
        "forged_incident_sla_fails_closed": forged_incident_sla_rejected(incident_record),
        "all_severity_records_compile_and_verify": all_severity_records_verify(incident_value),
        "interruption_completed_before_admission": interrupted.error_code
        == PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED
        and admitted_while_pending.error_code
        == PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED
        and completed.appended_count == 1
        and failed_completion.error_code == PromotionErrorCode.IDEMPOTENCY_CONFLICT
        and admitted_after_failed_completion.error_code
        == PromotionErrorCode.INTERRUPTION_COMPLETION_REQUIRED,
        "normative_mutation_results": probes == expected_probes,
        "repromotion_all_requirements": repromotion,
        "second_incident_blocks_repromotion": second_incident,
    }
    return _JSON.validate_python(
        {
            "verification_status": "pass" if all(checks.values()) else "fail",
            "acceptance_count": len(checks),
            "checks": checks,
            "mutation_probes": probes,
            "canonical_fixtures": all(
                path.read_bytes().rstrip(b"\n") == canonical_json(load_json(path))
                for path in (HAPPY_FIXTURE_PATH, INCIDENT_FIXTURE_PATH)
            ),
        }
    )
