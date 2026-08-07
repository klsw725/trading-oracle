from decimal import Decimal
from typing import Final

from src.v4.models import canonical_hash

from .models import ContractInvariantError, JsonBoundary
from .offline_models import OfflineCode
from .paper_assignment import assign, verify_policy
from .paper_models import PaperCohortInput, PaperDecision, PaperStopCode
from .paper_observations import HorizonReport, PaperMetrics, SampleObservation, ratio


EXPECTED_PRODUCTION_PERSPECTIVES: Final = ("kwangsoo", "ouroboros", "quant", "macro", "value")


def _validated_records(value: PaperCohortInput) -> tuple[SampleObservation, ...]:
    records = tuple(record for batch in value.observation_batches for record in batch.records)
    sample_ids = tuple(record.sample_id for record in records)
    production_decision_ids = tuple(record.assignment_input.production_decision_id for record in records)
    assignment_hashes = tuple(record.assignment.assignment_hash for record in records)
    record_markets = {record.assignment_input.market for record in records}
    session_markets = {session.market for batch in value.observation_batches for session in batch.market_sessions}
    assignments_valid = all(record.assignment.assigned_to_paper and record.assignment == assign(value.candidate_id, value.candidate_version, record.assignment_input, value.policy) and record.production_verdict == record.assignment_input.production_action for record in records)
    cutoffs_valid = all(record.assignment_input.emitted_at == batch.decision_cutoff for batch in value.observation_batches for record in batch.records)
    horizon_ids_aligned = all(tuple(record.sample_id for record in item.records) == sample_ids for item in value.horizon_observations)
    identities_unique = len(set(sample_ids)) == len(sample_ids) and len(set(production_decision_ids)) == len(production_decision_ids) and len(set(assignment_hashes)) == len(assignment_hashes)
    if not records or not identities_unique or not assignments_valid or not cutoffs_valid:
        raise ContractInvariantError("paper sample assignment inventory is invalid")
    if len(record_markets) != 1 or session_markets != record_markets or not horizon_ids_aligned:
        raise ContractInvariantError("paper cohort requires one aligned market history")
    return records


def derive_metrics(value: PaperCohortInput) -> PaperMetrics:
    batches = value.observation_batches
    records = _validated_records(value)
    assigned = len(records)
    target = sum(record.target_disagreement for record in records)
    candidate_na = sum(record.shadow_verdict == "N/A" for record in records)
    target_na = sum(record.target_disagreement and record.shadow_verdict == "N/A" for record in records)
    schema_drift = sum(not record.input_schema_valid for record in records)
    disagreements = sum(record.production_verdict != record.shadow_verdict for record in records)
    latencies = sorted(record.latency_ms for record in records)
    percentile_index = max(0, (95 * len(latencies) + 99) // 100 - 1)
    reports: list[HorizonReport] = []
    for horizon in (5, 20):
        observations = tuple(item for item in value.horizon_observations if item.horizon_market_sessions == horizon)
        outcomes = tuple(record for item in observations for record in item.records)
        eligible = len(outcomes)
        mature = sum(record.mature for record in outcomes)
        harmed = sum(record.harmed for record in outcomes)
        reports.append(HorizonReport(horizon_market_sessions=horizon, eligible_samples=eligible, mature_samples=mature, mature_coverage=ratio(mature, eligible), harmed_samples=harmed, harm_rate=ratio(harmed, mature)))
    disagreement_rate = ratio(disagreements, assigned)
    return PaperMetrics(
        assigned_samples=assigned,
        target_disagreement_samples=target,
        running_duration_market_sessions=len({session.session_id for batch in batches for session in batch.market_sessions}),
        candidate_na_rate=ratio(candidate_na, assigned),
        target_na_rate=ratio(target_na, target),
        latency_p95_ms=latencies[percentile_index] if latencies else 0,
        input_schema_drift_rate=ratio(schema_drift, assigned),
        shadow_vote_distribution_psi=max((batch.shadow_vote_distribution_psi for batch in batches), default="0.000000"),
        production_shadow_disagreement_rate=disagreement_rate,
        disagreement_review_flag=Decimal(disagreement_rate) > Decimal("0.800000") or Decimal(disagreement_rate) < Decimal("0.020000"),
        horizon_reports=(reports[0], reports[1]),
    )


def _decision(code: PaperStopCode, metrics: PaperMetrics, reason: str) -> PaperDecision:
    return PaperDecision(stop_code=code, lifecycle_review_eligible=code is PaperStopCode.READY, reasons=(reason,), metrics=metrics)


def evaluate_paper(value: PaperCohortInput) -> PaperDecision:
    offline = value.offline_artifact
    if offline.terminal_code is not OfflineCode.PASS:
        raise ContractInvariantError("only PASS_OFFLINE_EVALUATION may start paper")
    if value.offline_artifact_hash != offline.artifact_hash:
        raise ContractInvariantError("offline artifact hash pointer mismatch")
    if (value.candidate_id, value.candidate_version, value.hypothesis_id) != (offline.candidate_id, offline.candidate_version, offline.hypothesis_id):
        raise ContractInvariantError("paper lineage mismatch")
    metrics = derive_metrics(value)
    if not verify_policy(value.policy):
        return _decision(PaperStopCode.CONTAMINATION, metrics, "dirty_policy")
    if value.assignment != assign(value.candidate_id, value.candidate_version, value.assignment_input, value.policy):
        return _decision(PaperStopCode.CONTAMINATION, metrics, "assignment_or_eligibility_leakage")
    isolation = value.isolation
    readers_clean = not any((isolation.scorer_read_shadow, isolation.deliberator_read_shadow, isolation.portfolio_read_shadow, isolation.tuning_read_shadow))
    isolation_clean = isolation.production_before == isolation.production_after and isolation.production_before.perspectives == EXPECTED_PRODUCTION_PERSPECTIVES
    if not isolation_clean or not readers_clean or value.assignment_input.production_action != isolation.production_before.consensus_verdict:
        return _decision(PaperStopCode.CONTAMINATION, metrics, "production_isolation_changed")
    if value.shadow.decision_cutoff != value.assignment_input.emitted_at:
        return _decision(PaperStopCode.CONTAMINATION, metrics, "decision_cutoff_mismatch")
    production_hash = canonical_hash(JsonBoundary.model_validate(isolation.production_before.model_dump(mode="json")).root)
    batches_bound = all(batch.run_id == value.run_id and batch.policy_hash == value.policy.policy_hash and batch.production_snapshot_hash == production_hash and batch.decision_cutoff == value.assignment_input.emitted_at for batch in value.observation_batches)
    batch_ids = {batch.batch_id for batch in value.observation_batches}
    outcomes_bound_to_batches = all(item.batch_id in batch_ids for item in value.horizon_observations)
    records = _validated_records(value)
    sample_ids = tuple(record.sample_id for record in records)
    horizon_ids_aligned = all(tuple(record.sample_id for record in item.records) == sample_ids for item in value.horizon_observations)
    representative = tuple(record for record in records if record.sample_id == value.shadow.sample_id)
    shadow_bound = len(representative) == 1 and (representative[0].perspective, representative[0].shadow_verdict, representative[0].shadow_confidence, representative[0].shadow_reason, representative[0].shadow_action, representative[0].vote_effect, representative[0].shadow_visible_to_user, representative[0].cost_units, representative[0].latency_ms) == (value.shadow.perspective, value.shadow.verdict, value.shadow.confidence, value.shadow.reason, value.shadow.action, value.shadow.vote_effect, value.shadow.shadow_visible_to_user, value.shadow.cost_units, value.shadow.latency_ms)
    representative_assignment_bound = len(representative) == 1 and representative[0].assignment_input == value.assignment_input and representative[0].assignment == value.assignment
    inventory_clean = len(set(sample_ids)) == len(sample_ids) and horizon_ids_aligned and shadow_bound and representative_assignment_bound
    if not batches_bound or not outcomes_bound_to_batches or not inventory_clean:
        return _decision(PaperStopCode.CONTAMINATION, metrics, "observation_input_binding_mismatch")
    if not value.assignment.assigned_to_paper:
        return _decision(PaperStopCode.INSUFFICIENT, metrics, "sample_not_assigned")
    policy = value.policy
    if Decimal(metrics.input_schema_drift_rate) > Decimal(policy.schema_drift_ceiling):
        return _decision(PaperStopCode.SCHEMA_DRIFT, metrics, "input_schema_drift")
    if Decimal(metrics.candidate_na_rate) > Decimal(policy.overall_na_ceiling) or Decimal(metrics.target_na_rate) > Decimal(policy.target_na_ceiling):
        return _decision(PaperStopCode.COVERAGE_DRIFT, metrics, "candidate_na_rate")
    if Decimal(metrics.shadow_vote_distribution_psi) > Decimal(policy.verdict_psi_ceiling):
        return _decision(PaperStopCode.VERDICT_DRIFT, metrics, "shadow_vote_distribution_shift")
    budget = offline.candidate_artifact.candidate_proposal.budget.max_wall_ms_per_ticker
    if metrics.latency_p95_ms > min(budget, 6000):
        return _decision(PaperStopCode.LATENCY_DRIFT, metrics, "latency_p95_exceeded")
    five, twenty = metrics.horizon_reports
    minimums_met = metrics.running_duration_market_sessions >= policy.min_duration_market_sessions and metrics.assigned_samples >= policy.min_eligible_samples and metrics.target_disagreement_samples >= policy.min_target_disagreement_samples and Decimal(five.mature_coverage) >= Decimal(policy.min_mature_coverage)
    if not minimums_met:
        return _decision(PaperStopCode.INSUFFICIENT, metrics, "duration_sample_or_horizon_minimum")
    adapter = value.outcome_adapter
    if adapter is None or Decimal(adapter.staleness_rate) > Decimal(policy.adapter_staleness_ceiling):
        return _decision(PaperStopCode.PENDING_ADAPTER, metrics, "outcome_adapter_missing_or_stale")
    observations_bound = all(item.adapter_hash == adapter.adapter_hash and item.run_id == value.run_id for item in value.horizon_observations)
    if not observations_bound or five.eligible_samples != metrics.assigned_samples or twenty.eligible_samples != metrics.assigned_samples:
        return _decision(PaperStopCode.CONTAMINATION, metrics, "outcome_adapter_evidence_mismatch")
    if Decimal(five.harm_rate) > Decimal(policy.max_harm_rate):
        return _decision(PaperStopCode.HARMFUL, metrics, "shadow_outcome_harm")
    return _decision(PaperStopCode.READY, metrics, "all_paper_gates_passed")
