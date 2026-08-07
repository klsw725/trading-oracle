from pathlib import Path

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash

from .models import BoundaryModel, ContractInvariantError, JsonBoundary
from .offline_artifact import OfflineEvaluationArtifact, build_offline_artifact
from .offline_evidence import OfflineFixture
from .paper_assignment import assign, build_policy
from .paper_ledger import GENESIS_HASH, append_event, checkpoint_from_cancelled, semantic_event_specs
from .paper_assignment_types import AssignmentInput
from .paper_models import AssignmentPolicy, AssignmentPolicyBody, IsolationEvidence, LedgerEvent, LedgerEventBody, LedgerEventType, PaperCohortInput, PaperFixture, PaperStopCode, ProductionSnapshot, ResumeRequest, ShadowVerdict
from .paper_observations import HorizonObservation, HorizonObservationBody, HorizonOutcome, HorizonOutcomeBody, MarketSession, ObservationBatch, ObservationBatchBody, OutcomeAdapter, OutcomeAdapterBody, SampleObservation, SampleObservationBody


def _json(value: BoundaryModel) -> JsonValue:
    return JsonBoundary.model_validate(value.model_dump(mode="json")).root


def _bound[T: BoundaryModel](model: type[T], body: BoundaryModel, hash_field: str) -> T:
    return model.model_validate({**body.model_dump(mode="json"), hash_field: canonical_hash(_json(body))})


def load_paper_fixture(path: Path) -> PaperFixture:
    try:
        return PaperFixture.model_validate_json(path.read_bytes())
    except ValidationError as error:
        raise ContractInvariantError(f"invalid paper fixture: {error}") from error


def build_ledger(value: PaperCohortInput) -> tuple[LedgerEvent, ...]:
    events: tuple[LedgerEvent, ...] = ()
    for index, (event_type, entity, payload) in enumerate(semantic_event_specs(value)):
        body = LedgerEventBody(schema_version="v6.paper-cohort-ledger.1", run_id=value.run_id, event_index=index, event_type=event_type, occurred_at=value.generated_at, entity_ref_id=entity, prev_event_hash=events[-1].event_hash if events else GENESIS_HASH, payload_hash=canonical_hash(payload), payload=payload)
        events = append_event(events, body)
    return events


def build_resumed_ledger(value: PaperCohortInput, cancelled: tuple[LedgerEvent, ...]) -> tuple[LedgerEvent, ...]:
    resume_payload: JsonValue = {"checkpoint_hash": cancelled[-1].event_hash}
    resume_body = LedgerEventBody(schema_version="v6.paper-cohort-ledger.1", run_id=value.run_id, event_index=len(cancelled), event_type=LedgerEventType.RESUMED, occurred_at=value.generated_at, entity_ref_id=value.run_id, prev_event_hash=cancelled[-1].event_hash, payload_hash=canonical_hash(resume_payload), payload=resume_payload)
    events = append_event(cancelled, resume_body)
    remaining = semantic_event_specs(value)[len(cancelled) - 1 :]
    for event_type, entity, payload in remaining:
        body = LedgerEventBody(schema_version="v6.paper-cohort-ledger.1", run_id=value.run_id, event_index=len(events), event_type=event_type, occurred_at=value.generated_at, entity_ref_id=entity, prev_event_hash=events[-1].event_hash, payload_hash=canonical_hash(payload), payload=payload)
        events = append_event(events, body)
    return events


def _sample_records(offline: OfflineEvaluationArtifact, policy: AssignmentPolicy, cutoff: str) -> tuple[SampleObservation, ...]:
    records: list[SampleObservation] = []
    for index in range(360):
        sample_id = "paper_sample_v6_005930_20260806" if index == 13 else f"paper_sample_v6_{index:06d}_20260806"
        shadow_verdict = "N/A" if index < 13 or 130 <= index < 145 else "HOLD" if index < 130 else "BUY"
        production_verdict = "BUY"
        representative = index == 13
        assignment_input = AssignmentInput(production_decision_id="prod_decision_20260806_005930" if representative else f"prod_decision_20260806_{index:06d}", emitted_at=cutoff, ticker="005930" if representative else f"{index:06d}", market="KR", production_action="BUY")
        confidence = "0.000000" if shadow_verdict == "N/A" else "0.720000" if representative else "0.700000"
        action = "none" if shadow_verdict == "N/A" else "hold" if shadow_verdict == "HOLD" else "buy"
        reason = "working capital quality weakened before price momentum" if representative else f"fixture sample observation {index:03d}"
        body = SampleObservationBody(schema_version="v6.paper-sample-observation.1", sample_id=sample_id, target_disagreement=index < 130, input_schema_valid=True, assignment_input=assignment_input, assignment=assign(offline.candidate_id, offline.candidate_version, assignment_input, policy), production_verdict=production_verdict, perspective="working_capital_quality", shadow_verdict=shadow_verdict, shadow_confidence=confidence, shadow_reason=reason, shadow_action=action, vote_effect="none", shadow_visible_to_user=False, cost_units=0, shadow_recorded=True, latency_ms=2300 if index >= 340 else 2100)
        records.append(_bound(SampleObservation, body, "record_hash"))
    return tuple(records)


def _horizon_records(sample_ids: tuple[str, ...], mature_count: int, harmed_count: int) -> tuple[HorizonOutcome, ...]:
    records: list[HorizonOutcome] = []
    for index, sample_id in enumerate(sample_ids):
        body = HorizonOutcomeBody(schema_version="v6.paper-horizon-outcome.1", sample_id=sample_id, mature=index < mature_count, harmed=index < harmed_count)
        records.append(_bound(HorizonOutcome, body, "record_hash"))
    return tuple(records)


def build_fixture(offline_fixture: OfflineFixture) -> PaperFixture:
    offline = build_offline_artifact(offline_fixture.candidate_artifact, offline_fixture.threshold_input, offline_fixture.hand_input)
    policy = build_policy(AssignmentPolicyBody(policy_id="paper_policy_v6_20260806", policy_salt="salt_v6_paper_20260806", sample_rate_bps=10000, eligible_markets=("KR", "US"), eligible_actions=("BUY", "SELL", "HOLD"), horizons=(5, 20), min_duration_market_sessions=60, min_eligible_samples=300, min_target_disagreement_samples=100, min_mature_coverage="0.700000", overall_na_ceiling="0.150000", target_na_ceiling="0.200000", schema_drift_ceiling="0.020000", verdict_psi_ceiling="0.200000", adapter_staleness_ceiling="0.100000", max_harm_rate="0.200000"))
    assignment_input = AssignmentInput(production_decision_id="prod_decision_20260806_005930", emitted_at="2026-08-06T09:35:00+09:00", ticker="005930", market="KR", production_action="BUY")
    snapshot = ProductionSnapshot(perspectives=("kwangsoo", "ouroboros", "quant", "macro", "value"), vote_summary={"BUY": 3, "SELL": 0, "HOLD": 2, "N/A": 0}, consensus_verdict="BUY", portfolio_sizing={"action": "buy", "shares": 10}, user_output={"verdict": "BUY", "ticker": "005930"})
    snapshot_hash = canonical_hash(_json(snapshot))
    run_id = "paper_run_v6_working_capital_quality_20260806"
    cutoff = assignment_input.emitted_at
    shadow = ShadowVerdict(sample_id="paper_sample_v6_005930_20260806", perspective="working_capital_quality", verdict="HOLD", confidence="0.720000", reason="working capital quality weakened before price momentum", action="hold", vote_effect="none", shadow_visible_to_user=False, cost_units=0, latency_ms=2100, decision_cutoff=cutoff)
    sample_records = _sample_records(offline, policy, cutoff)
    batch_body = ObservationBatchBody(schema_version="v6.paper-observation-batch.2", batch_id="paper_batch_v6_20260806_001", run_id=run_id, policy_hash=policy.policy_hash, production_snapshot_hash=snapshot_hash, decision_cutoff=cutoff, market_sessions=tuple(MarketSession(market="KR", session_id=f"KRX_2026_session_{index:03d}") for index in range(72)), records=sample_records, shadow_vote_distribution_psi="0.080000")
    batch = _bound(ObservationBatch, batch_body, "batch_hash")
    adapter_body = OutcomeAdapterBody(adapter_id="fixture_outcome_v6", adapter_version="1.0.0", observed_at="2026-08-06T09:35:00+09:00", staleness_rate="0.020000")
    adapter = _bound(OutcomeAdapter, adapter_body, "adapter_hash")
    sample_ids = tuple(record.sample_id for record in sample_records)
    five_body = HorizonObservationBody(schema_version="v6.paper-horizon-observation.2", batch_id=batch.batch_id, run_id=run_id, adapter_hash=adapter.adapter_hash, horizon_market_sessions=5, records=_horizon_records(sample_ids, 300, 36))
    twenty_body = HorizonObservationBody(schema_version="v6.paper-horizon-observation.2", batch_id=batch.batch_id, run_id=run_id, adapter_hash=adapter.adapter_hash, horizon_market_sessions=20, records=_horizon_records(sample_ids, 240, 24))
    horizons = (_bound(HorizonObservation, five_body, "observation_hash"), _bound(HorizonObservation, twenty_body, "observation_hash"))
    paper_input = PaperCohortInput(schema_version="v6.paper-cohort-input.1", generated_at=cutoff, run_id=run_id, candidate_id=offline.candidate_id, candidate_version=offline.candidate_version, hypothesis_id=offline.hypothesis_id, offline_artifact_hash=offline.artifact_hash, offline_artifact=offline, policy=policy, assignment_input=assignment_input, assignment=assign(offline.candidate_id, offline.candidate_version, assignment_input, policy), isolation=IsolationEvidence(production_before=snapshot, production_after=snapshot, scorer_read_shadow=False, deliberator_read_shadow=False, portfolio_read_shadow=False, tuning_read_shadow=False), shadow=shadow, observation_batches=(batch,), horizon_observations=horizons, outcome_adapter=adapter, reported_stop_code=PaperStopCode.READY)
    normal_ledger = build_ledger(paper_input)
    cancelled_payload: JsonValue = {"reason": "operator_request"}
    cancelled_body = LedgerEventBody(schema_version="v6.paper-cohort-ledger.1", run_id=run_id, event_index=3, event_type=LedgerEventType.CANCELLED, occurred_at=cutoff, entity_ref_id=run_id, prev_event_hash=normal_ledger[2].event_hash, payload_hash=canonical_hash(cancelled_payload), payload=cancelled_payload)
    cancelled_ledger = append_event(normal_ledger[:3], cancelled_body)
    checkpoint = checkpoint_from_cancelled(paper_input, cancelled_ledger)
    request = ResumeRequest(run_id=run_id, policy_id=policy.policy_id, candidate_version=offline.candidate_version, prev_event_hash=checkpoint.last_event_hash, next_event_index=checkpoint.last_event_index + 1, write_sample_id="paper_sample_v6_000660_20260806")
    vectors = (assignment_input, assignment_input.model_copy(update={"ticker": "000660", "production_decision_id": "prod_decision_20260806_000660"}), assignment_input.model_copy(update={"market": "US", "ticker": "AAPL", "production_decision_id": "prod_decision_20260806_AAPL"}))
    return PaperFixture(schema_version="v6.paper-cohort-fixture.1", paper_input=paper_input, ledger=build_resumed_ledger(paper_input, cancelled_ledger), assignment_vectors=vectors, assignment_golden_buckets=(1213, 6380, 126), cancelled_ledger=cancelled_ledger, checkpoint=checkpoint, resume_request=request)
