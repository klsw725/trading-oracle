import ast
from pathlib import Path

from pydantic import BaseModel, ValidationError

from src.v4.models import JsonValue, canonical_hash

from .models import BoundaryModel, ContractInvariantError, JsonBoundary
from .offline_models import OfflineCode
from .paper_artifact import PaperArtifactBody, PaperCohortArtifact, boundary_json, build_paper_artifact
from .paper_assignment import assign, build_policy
from .paper_attacks import rebuilt_duplicate_assignment_rejected, rebuilt_ineligible_300_rejected, rebuilt_mixed_market_60_rejected, unbound_cancelled_checkpoint_rejected
from .paper_evaluator import evaluate_paper
from .paper_fixture import build_ledger
from .paper_ledger import cancelled_decision, checkpoint_from_cancelled, decide_resume, validate_ledger
from .paper_models import AssignmentPolicyBody, PaperDecision, PaperFixture, PaperStopCode
from .paper_observations import HorizonObservation, HorizonObservationBody, HorizonOutcome, HorizonOutcomeBody, MarketSession, ObservationBatch, ObservationBatchBody, OutcomeAdapter, OutcomeAdapterBody, SampleObservation, SampleObservationBody


def _parser_rejects(model: type[BaseModel], raw: JsonValue) -> bool:
    try:
        _ = model.model_validate(raw)
    except (ValidationError, ContractInvariantError):
        return True
    return False


def _build_rejects(fixture: PaperFixture) -> bool:
    try:
        _ = build_paper_artifact(fixture.paper_input, fixture.ledger)
    except ContractInvariantError:
        return True
    return False


def _bound[T: BoundaryModel](model: type[T], body: BoundaryModel, hash_field: str) -> T:
    raw = JsonBoundary.model_validate(body.model_dump(mode="json")).root
    return model.model_validate({**body.model_dump(mode="json"), hash_field: canonical_hash(raw)})


def _batch(batch: ObservationBatch, records: tuple[SampleObservation, ...] | None = None, market_sessions: tuple[MarketSession, ...] | None = None, verdict_psi: str | None = None) -> ObservationBatch:
    body = ObservationBatchBody.model_validate({**batch.model_dump(mode="json", exclude={"batch_hash"}), "records": records or batch.records, "market_sessions": market_sessions or batch.market_sessions, "shadow_vote_distribution_psi": verdict_psi or batch.shadow_vote_distribution_psi})
    return _bound(ObservationBatch, body, "batch_hash")


def _horizon(item: HorizonObservation, records: tuple[HorizonOutcome, ...]) -> HorizonObservation:
    body = HorizonObservationBody.model_validate({**item.model_dump(mode="json", exclude={"observation_hash"}), "records": records})
    return _bound(HorizonObservation, body, "observation_hash")


def _sample(item: SampleObservation, **updates: JsonValue) -> SampleObservation:
    body = SampleObservationBody.model_validate({**item.model_dump(mode="json", exclude={"record_hash"}), **updates})
    return _bound(SampleObservation, body, "record_hash")


def _outcome(item: HorizonOutcome, **updates: JsonValue) -> HorizonOutcome:
    body = HorizonOutcomeBody.model_validate({**item.model_dump(mode="json", exclude={"record_hash"}), **updates})
    return _bound(HorizonOutcome, body, "record_hash")


def _inflated_rebuild_rejected(fixture: PaperFixture) -> bool:
    batch = fixture.paper_input.observation_batches[0]
    inflated = tuple(batch.records[index % len(batch.records)] for index in range(999))
    draft = batch.model_copy(update={"records": inflated})
    raw = JsonBoundary.model_validate(draft.model_dump(mode="json", exclude={"batch_hash"})).root
    forged_batch = draft.model_copy(update={"batch_hash": canonical_hash(raw)})
    forged = fixture.paper_input.model_copy(update={"observation_batches": (forged_batch,)})
    try:
        rebuilt = build_ledger(forged)
        _ = build_paper_artifact(forged, rebuilt)
    except ContractInvariantError:
        return True
    return False


def _forbidden_imports_absent() -> bool:
    forbidden = ("src.consensus", "src.common", "src.portfolio", "src.performance", "src.output")
    root = Path(__file__).resolve().parents[2]
    paths = tuple((root / "src/v6").glob("paper_*.py"))
    if not paths:
        return False
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
        modules.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        if any(module.startswith(forbidden) for module in modules):
            return False
    return True


def verify_paper_fixture(fixture: PaperFixture) -> JsonValue:
    value = fixture.paper_input
    artifact = build_paper_artifact(value, fixture.ledger)
    vectors = tuple(assign(value.candidate_id, value.candidate_version, item, value.policy) for item in fixture.assignment_vectors)
    contaminated_snapshot = value.isolation.production_before.model_copy(update={"perspectives": (*value.isolation.production_before.perspectives, value.shadow.perspective)})
    contaminated = value.model_copy(update={"isolation": value.isolation.model_copy(update={"production_after": contaminated_snapshot})})
    leaked = value.model_copy(update={"assignment_input": value.assignment_input.model_copy(update={"production_action": "SELL"})})
    early_batch = _batch(value.observation_batches[0], value.observation_batches[0].records[:120], value.observation_batches[0].market_sessions[:30])
    early_horizons = tuple(_horizon(item, item.records[:120]) for item in value.horizon_observations)
    early = value.model_copy(update={"observation_batches": (early_batch,), "horizon_observations": early_horizons, "reported_stop_code": PaperStopCode.INSUFFICIENT})
    missing_adapter = value.model_copy(update={"outcome_adapter": None, "reported_stop_code": PaperStopCode.PENDING_ADAPTER})
    schema_records = tuple(_sample(record, input_schema_valid=False) if index < 11 else record for index, record in enumerate(value.observation_batches[0].records))
    schema_batch = _batch(value.observation_batches[0], schema_records)
    schema = value.model_copy(update={"observation_batches": (schema_batch,), "reported_stop_code": PaperStopCode.SCHEMA_DRIFT})
    coverage_records = tuple(_sample(record, shadow_verdict="N/A", shadow_confidence="0.000000", shadow_action="none") if index >= 305 else record for index, record in enumerate(value.observation_batches[0].records))
    coverage_batch = _batch(value.observation_batches[0], coverage_records)
    coverage = value.model_copy(update={"observation_batches": (coverage_batch,), "reported_stop_code": PaperStopCode.COVERAGE_DRIFT})
    verdict_batch = _batch(value.observation_batches[0], verdict_psi="0.210000")
    verdict = value.model_copy(update={"observation_batches": (verdict_batch,), "reported_stop_code": PaperStopCode.VERDICT_DRIFT})
    latency_records = tuple(_sample(record, latency_ms=3001) if index >= 340 else record for index, record in enumerate(value.observation_batches[0].records))
    latency_batch = _batch(value.observation_batches[0], latency_records)
    latency = value.model_copy(update={"observation_batches": (latency_batch,), "reported_stop_code": PaperStopCode.LATENCY_DRIFT})
    harmful_records = tuple(_outcome(record, harmed=True) if index < 61 else record for index, record in enumerate(value.horizon_observations[0].records))
    harmful_five = _horizon(value.horizon_observations[0], harmful_records)
    harmful = value.model_copy(update={"horizon_observations": (harmful_five, value.horizon_observations[1]), "reported_stop_code": PaperStopCode.HARMFUL})
    policy_body = AssignmentPolicyBody.model_validate(value.policy.model_dump(mode="json", exclude={"policy_hash"}))
    rehashed_policy = build_policy(policy_body.model_copy(update={"sample_rate_bps": 9999}))
    dirty = value.model_copy(update={"policy": rehashed_policy})
    shadow_mismatch = value.model_copy(update={"shadow": value.shadow.model_copy(update={"reason": "forged reason"})})
    cutoff = value.model_copy(update={"shadow": value.shadow.model_copy(update={"decision_cutoff": "2026-08-06T09:36:00+09:00"})})
    missing_twenty = value.model_copy(update={"horizon_observations": (value.horizon_observations[0],)})
    harmful_without_adapter = harmful.model_copy(update={"outcome_adapter": None, "reported_stop_code": PaperStopCode.PENDING_ADAPTER})
    stale_body = OutcomeAdapterBody.model_validate({**value.outcome_adapter.model_dump(mode="json", exclude={"adapter_hash"}), "staleness_rate": "0.200000"}) if value.outcome_adapter else None
    stale_adapter = _bound(OutcomeAdapter, stale_body, "adapter_hash") if stale_body else None
    stale = value.model_copy(update={"outcome_adapter": stale_adapter, "reported_stop_code": PaperStopCode.PENDING_ADAPTER})
    fabricated = fixture.checkpoint.model_copy(update={"last_event_index": 999, "last_event_hash": f"sha256:{'f' * 64}"})
    checks: dict[str, bool] = {
        "happy_ready": artifact.decision.stop_code is PaperStopCode.READY,
        "offline_v2_revalidated": value.offline_artifact.schema_version == "v6.offline-evaluation-artifact.2" and value.offline_artifact.terminal_code is OfflineCode.PASS,
        "production_snapshots_equal": value.isolation.production_before == value.isolation.production_after,
        "production_vote_mutation": evaluate_paper(contaminated).stop_code is PaperStopCode.CONTAMINATION,
        "eligibility_leakage": evaluate_paper(leaked).stop_code is PaperStopCode.CONTAMINATION,
        "ready_too_early": evaluate_paper(early).stop_code is PaperStopCode.INSUFFICIENT,
        "missing_adapter": evaluate_paper(missing_adapter).stop_code is PaperStopCode.PENDING_ADAPTER,
        "schema_drift": evaluate_paper(schema).stop_code is PaperStopCode.SCHEMA_DRIFT,
        "coverage_drift": evaluate_paper(coverage).stop_code is PaperStopCode.COVERAGE_DRIFT,
        "verdict_drift": evaluate_paper(verdict).stop_code is PaperStopCode.VERDICT_DRIFT,
        "latency_drift": evaluate_paper(latency).stop_code is PaperStopCode.LATENCY_DRIFT,
        "harmful_shadow": evaluate_paper(harmful).stop_code is PaperStopCode.HARMFUL,
        "oracle_rehashed_policy_ledger_mismatch": _build_rejects(fixture.model_copy(update={"paper_input": dirty})),
        "oracle_shadow_ledger_mismatch": _build_rejects(fixture.model_copy(update={"paper_input": shadow_mismatch})),
        "oracle_fully_rebuilt_count_inflation": _inflated_rebuild_rejected(fixture),
        "oracle_fabricated_checkpoint": decide_resume(value, fixture.cancelled_ledger, fabricated, fixture.resume_request).stop_code is PaperStopCode.CONTAMINATION,
        "oracle_missing_adapter_precedes_harm": evaluate_paper(harmful_without_adapter).stop_code is PaperStopCode.PENDING_ADAPTER,
        "oracle_cutoff_mismatch": evaluate_paper(cutoff).stop_code is PaperStopCode.CONTAMINATION,
        "oracle_missing_twenty_report": evaluate_paper(missing_twenty).stop_code is PaperStopCode.CONTAMINATION,
        "stale_adapter_pending": evaluate_paper(stale).stop_code is PaperStopCode.PENDING_ADAPTER,
        "resume_from_cancelled_head": decide_resume(value, fixture.cancelled_ledger, fixture.checkpoint, fixture.resume_request).resume_allowed,
        "resume_hash_mismatch": decide_resume(value, fixture.cancelled_ledger, fixture.checkpoint, fixture.resume_request.model_copy(update={"prev_event_hash": f"sha256:{'f' * 64}"})).stop_code is PaperStopCode.CONTAMINATION,
        "resume_duplicate_contamination": decide_resume(value, fixture.cancelled_ledger, fixture.checkpoint, fixture.resume_request.model_copy(update={"write_sample_id": value.shadow.sample_id})).stop_code is PaperStopCode.CONTAMINATION,
        "checkpoint_derived": checkpoint_from_cancelled(value, fixture.cancelled_ledger) == fixture.checkpoint,
        "cancelled_terminal_connected": cancelled_decision(value, fixture.cancelled_ledger).stop_code is PaperStopCode.CANCELLED,
        "assignment_golden_buckets": tuple(item.assignment_bucket for item in vectors) == fixture.assignment_golden_buckets,
        "assignment_vectors_distinct": len({item.assignment_hash for item in vectors}) == len(vectors),
        "ledger_semantic_roundtrip": validate_ledger(value, fixture.ledger) is None,
        "resumed_terminal_artifact": any(event.event_type.value == "paper_run_resumed" for event in artifact.ledger),
        "oracle_ineligible_300_rebuilt": rebuilt_ineligible_300_rejected(value),
        "oracle_duplicate_assignment_rebuilt": rebuilt_duplicate_assignment_rejected(value),
        "oracle_mixed_market_60_rebuilt": rebuilt_mixed_market_60_rejected(value),
        "oracle_unbound_cancelled_checkpoint": unbound_cancelled_checkpoint_rejected(value),
        "forbidden_imports_absent": _forbidden_imports_absent(),
    }
    shadow_raw: JsonValue = {"sample_id": value.shadow.sample_id, "perspective": value.shadow.perspective, "verdict": value.shadow.verdict, "confidence": value.shadow.confidence, "reason": value.shadow.reason, "action": value.shadow.action, "shadow_visible_to_user": value.shadow.shadow_visible_to_user, "cost_units": value.shadow.cost_units, "latency_ms": value.shadow.latency_ms, "decision_cutoff": value.shadow.decision_cutoff}
    malformed = [item.model_dump(mode="json") for item in fixture.ledger]
    malformed[1] = {**malformed[1], "event_index": 9}
    parser_checks = {
        "missing_vote_effect": _parser_rejects(type(value.shadow), shadow_raw),
        "bad_confidence": _parser_rejects(type(value.shadow), {**value.shadow.model_dump(mode="json"), "confidence": "1.200000"}),
        "malformed_ledger": _parser_rejects(type(artifact), JsonBoundary.model_validate({**artifact.model_dump(mode="json"), "ledger": malformed}).root),
        "aggregate_count_fields_forbidden": _parser_rejects(ObservationBatchBody, JsonBoundary.model_validate({**value.observation_batches[0].model_dump(mode="json", exclude={"batch_hash"}), "assigned_samples": 999}).root),
    }
    fake_decision = PaperDecision(stop_code=PaperStopCode.CANCELLED, lifecycle_review_eligible=False, reasons=("forged",), metrics=artifact.decision.metrics)
    forged_body = PaperArtifactBody.model_validate({**artifact.model_dump(mode="json", exclude={"artifact_hash"}), "decision": fake_decision.model_dump(mode="json")})
    forged = artifact.model_copy(update={"decision": fake_decision, "artifact_hash": canonical_hash(boundary_json(forged_body))})
    artifact_checks = {
        "artifact_roundtrip": PaperCohortArtifact.model_validate(artifact.model_dump(mode="json")) == artifact,
        "artifact_hash_tamper": _parser_rejects(type(artifact), artifact.model_copy(update={"artifact_hash": f"sha256:{'0' * 64}"}).model_dump(mode="json")),
        "decision_forgery": _parser_rejects(type(artifact), forged.model_dump(mode="json")),
        "misleading_ready_rejected": _build_rejects(fixture.model_copy(update={"paper_input": early.model_copy(update={"reported_stop_code": PaperStopCode.READY})})),
        "nonpass_offline_start_rejected": _parser_rejects(type(artifact), {**artifact.model_dump(mode="json"), "paper_input": {**value.model_dump(mode="json"), "offline_artifact": {**value.offline_artifact.model_dump(mode="json"), "terminal_code": OfflineCode.NO_LIFT.value}}}),
    }
    all_checks = {**checks, **parser_checks, **artifact_checks}
    result = {"state": "pass" if all(all_checks.values()) else "fail", "schema_version": fixture.schema_version, "pass_count": sum(all_checks.values()), "total": len(all_checks), "terminal_code": artifact.decision.stop_code.value, "artifact_hash": artifact.artifact_hash, "paper_input_hash": artifact.paper_input_hash, "ledger_head_hash": artifact.ledger_head_hash, "production_before_hash": artifact.production_before_hash, "production_after_hash": artifact.production_after_hash, "derived_metrics": artifact.decision.metrics.model_dump(mode="json"), "checks": all_checks}
    return JsonBoundary.model_validate(result).root
