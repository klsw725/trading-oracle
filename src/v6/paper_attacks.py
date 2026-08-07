from src.v4.models import JsonValue, canonical_hash

from .models import BoundaryModel, ContractInvariantError, JsonBoundary
from .paper_artifact import build_paper_artifact
from .paper_assignment import assign
from .paper_fixture import build_ledger
from .paper_ledger import append_event, checkpoint_from_cancelled
from .paper_models import LedgerEvent, LedgerEventBody, LedgerEventType, PaperCohortInput
from .paper_observations import HorizonObservation, HorizonObservationBody, HorizonOutcome, HorizonOutcomeBody, MarketSession, ObservationBatch, ObservationBatchBody, SampleObservation, SampleObservationBody


def _bound[T: BoundaryModel](model: type[T], body: BoundaryModel, hash_field: str) -> T:
    raw = JsonBoundary.model_validate(body.model_dump(mode="json")).root
    return model.model_validate({**body.model_dump(mode="json"), hash_field: canonical_hash(raw)})


def _batch(source: ObservationBatch, records: tuple[SampleObservation, ...], sessions: tuple[MarketSession, ...]) -> ObservationBatch:
    body = ObservationBatchBody.model_validate({**source.model_dump(mode="json", exclude={"batch_hash"}), "records": records, "market_sessions": sessions})
    return _bound(ObservationBatch, body, "batch_hash")


def _horizon(source: HorizonObservation, sample_ids: set[str]) -> HorizonObservation:
    records = tuple(record for record in source.records if record.sample_id in sample_ids)
    body = HorizonObservationBody.model_validate({**source.model_dump(mode="json", exclude={"observation_hash"}), "records": records})
    return _bound(HorizonObservation, body, "observation_hash")


def _rebuilt_ready_rejected(value: PaperCohortInput) -> bool:
    try:
        ledger = build_ledger(value)
        artifact = build_paper_artifact(value, ledger)
    except ContractInvariantError:
        return True
    return not artifact.decision.lifecycle_review_eligible


def rebuilt_ineligible_300_rejected(value: PaperCohortInput) -> bool:
    records: list[SampleObservation] = []
    for index, record in enumerate(value.observation_batches[0].records[:300]):
        if 130 <= index < 145:
            assignment_input = record.assignment_input.model_copy(update={"production_action": "N/A"})
            body = SampleObservationBody.model_validate({**record.model_dump(mode="json", exclude={"record_hash"}), "assignment_input": assignment_input.model_dump(mode="json"), "assignment": assign(value.candidate_id, value.candidate_version, assignment_input, value.policy).model_dump(mode="json"), "production_verdict": "N/A"})
            records.append(_bound(SampleObservation, body, "record_hash"))
        else:
            records.append(record)
    sample_ids = {record.sample_id for record in records}
    batch = _batch(value.observation_batches[0], tuple(records), value.observation_batches[0].market_sessions)
    horizons = tuple(_horizon(item, sample_ids) for item in value.horizon_observations)
    forged = value.model_copy(update={"observation_batches": (batch,), "horizon_observations": horizons})
    return _rebuilt_ready_rejected(forged)


def rebuilt_mixed_market_60_rejected(value: PaperCohortInput) -> bool:
    sessions = tuple(MarketSession(market="KR", session_id=f"KRX_{index:03d}") for index in range(30)) + tuple(MarketSession(market="US", session_id=f"NYSE_{index:03d}") for index in range(30))
    batch = _batch(value.observation_batches[0], value.observation_batches[0].records, sessions)
    forged = value.model_copy(update={"observation_batches": (batch,)})
    return _rebuilt_ready_rejected(forged)


def rebuilt_duplicate_assignment_rejected(value: PaperCohortInput) -> bool:
    source = value.observation_batches[0].records[13]
    records: list[SampleObservation] = []
    for index in range(360):
        sample_id = value.shadow.sample_id if index == 0 else f"paper_clone_v6_{index:06d}"
        body = SampleObservationBody.model_validate({**source.model_dump(mode="json", exclude={"record_hash"}), "sample_id": sample_id})
        records.append(_bound(SampleObservation, body, "record_hash"))
    batch = _batch(value.observation_batches[0], tuple(records), value.observation_batches[0].market_sessions)
    horizons: list[HorizonObservation] = []
    for item in value.horizon_observations:
        outcome_source = item.records[100]
        outcomes: list[HorizonOutcome] = []
        for record in records:
            outcome_body = HorizonOutcomeBody.model_validate({**outcome_source.model_dump(mode="json", exclude={"record_hash"}), "sample_id": record.sample_id})
            outcomes.append(_bound(HorizonOutcome, outcome_body, "record_hash"))
        horizon_body = HorizonObservationBody.model_validate({**item.model_dump(mode="json", exclude={"observation_hash"}), "records": outcomes})
        horizons.append(_bound(HorizonObservation, horizon_body, "observation_hash"))
    forged = value.model_copy(update={"observation_batches": (batch,), "horizon_observations": tuple(horizons)})
    return _rebuilt_ready_rejected(forged)


def _append_copy(events: tuple[LedgerEvent, ...], source: LedgerEvent, payload: JsonValue) -> tuple[LedgerEvent, ...]:
    body = LedgerEventBody(schema_version="v6.paper-cohort-ledger.1", run_id=source.run_id, event_index=len(events), event_type=source.event_type, occurred_at=source.occurred_at, entity_ref_id=source.entity_ref_id, prev_event_hash=events[-1].event_hash, payload_hash=canonical_hash(payload), payload=payload)
    return append_event(events, body)


def unbound_cancelled_checkpoint_rejected(value: PaperCohortInput) -> bool:
    normal = build_ledger(value)
    assigned_payload: JsonValue = {"assignment_hash": value.assignment.assignment_hash, "assignment_bucket": value.assignment.assignment_bucket, "sample_record_hashes": [], "observation_batch_hashes": [], "production_snapshot_hash": normal[1].payload.get("production_snapshot_hash") if isinstance(normal[1].payload, dict) else None}
    events = _append_copy((normal[0],), normal[1], assigned_payload)
    events = _append_copy(events, normal[2], normal[2].payload)
    cancel_payload: JsonValue = {"reason": "operator_request"}
    cancel_source = normal[2].model_copy(update={"event_type": LedgerEventType.CANCELLED, "entity_ref_id": value.run_id})
    events = _append_copy(events, cancel_source, cancel_payload)
    try:
        _ = checkpoint_from_cancelled(value, events)
    except ContractInvariantError:
        return True
    return False
