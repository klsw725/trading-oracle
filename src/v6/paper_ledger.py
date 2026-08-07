from typing import Final

from src.v4.models import JsonValue, canonical_hash

from .models import ContractInvariantError, JsonBoundary
from .paper_evaluator import derive_metrics, evaluate_paper
from .paper_models import LedgerEvent, LedgerEventBody, LedgerEventType, PaperCohortInput, PaperDecision, PaperStopCode, ResumeCheckpoint, ResumeDecision, ResumeRequest


GENESIS_HASH: Final = f"sha256:{'0' * 64}"


def _event_hash_json(value: LedgerEventBody) -> JsonValue:
    return {
        "schema_version": value.schema_version,
        "run_id": value.run_id,
        "event_index": value.event_index,
        "event_type": value.event_type.value,
        "entity_ref_id": value.entity_ref_id,
        "prev_event_hash": value.prev_event_hash,
        "payload_hash": value.payload_hash,
    }


def _json(value: JsonValue) -> JsonValue:
    return JsonBoundary.model_validate(value).root


def _validate_structure(events: tuple[LedgerEvent, ...]) -> None:
    previous = GENESIS_HASH
    run_id = events[0].run_id if events else ""
    samples: set[str] = set()
    previous_type: LedgerEventType | None = None
    allowed: dict[LedgerEventType | None, tuple[LedgerEventType, ...]] = {
        None: (LedgerEventType.STARTED,),
        LedgerEventType.STARTED: (LedgerEventType.ASSIGNED,),
        LedgerEventType.ASSIGNED: (LedgerEventType.SHADOW,),
        LedgerEventType.SHADOW: (LedgerEventType.ASSIGNED, LedgerEventType.OUTCOME, LedgerEventType.CANCELLED),
        LedgerEventType.OUTCOME: (LedgerEventType.OUTCOME, LedgerEventType.DRIFT, LedgerEventType.CANCELLED),
        LedgerEventType.DRIFT: (LedgerEventType.STOPPED, LedgerEventType.CANCELLED),
        LedgerEventType.CANCELLED: (LedgerEventType.RESUMED,),
        LedgerEventType.RESUMED: (LedgerEventType.ASSIGNED, LedgerEventType.OUTCOME, LedgerEventType.DRIFT, LedgerEventType.STOPPED),
        LedgerEventType.STOPPED: (),
    }
    for index, event in enumerate(events):
        body = LedgerEventBody.model_validate(event.model_dump(mode="json", exclude={"event_id", "event_hash"}))
        if event.run_id != run_id or event.event_index != index or event.prev_event_hash != previous:
            raise ContractInvariantError("malformed ledger identity or sequence")
        if event.event_type not in allowed[previous_type]:
            raise ContractInvariantError("invalid ledger state transition")
        if event.payload_hash != canonical_hash(event.payload) or event.event_hash != canonical_hash(_event_hash_json(body)):
            raise ContractInvariantError("malformed ledger hash chain")
        if event.event_id != f"pledge_v6_{index:04d}":
            raise ContractInvariantError("malformed ledger event id")
        if event.event_type is LedgerEventType.SHADOW:
            if event.entity_ref_id in samples:
                raise ContractInvariantError("duplicate shadow verdict")
            samples.add(event.entity_ref_id)
        previous = event.event_hash
        previous_type = event.event_type


def append_event(events: tuple[LedgerEvent, ...], body: LedgerEventBody) -> tuple[LedgerEvent, ...]:
    expected_index = len(events)
    previous = events[-1].event_hash if events else GENESIS_HASH
    if body.event_index != expected_index or body.prev_event_hash != previous:
        raise ContractInvariantError("ledger append index or previous hash mismatch")
    if body.payload_hash != canonical_hash(body.payload):
        raise ContractInvariantError("ledger payload hash mismatch")
    event_hash = canonical_hash(_event_hash_json(body))
    event = LedgerEvent.model_validate({**body.model_dump(mode="json"), "event_id": f"pledge_v6_{expected_index:04d}", "event_hash": event_hash})
    result = (*events, event)
    _validate_structure(result)
    return result


def semantic_event_specs(value: PaperCohortInput) -> tuple[tuple[LedgerEventType, str, JsonValue], ...]:
    production_hash = canonical_hash(_json(value.isolation.production_before.model_dump(mode="json")))
    started: JsonValue = _json({
        "candidate_id": value.candidate_id,
        "candidate_version": value.candidate_version,
        "offline_artifact_hash": value.offline_artifact_hash,
        "policy_hash": value.policy.policy_hash,
        "assignment_input_hash": canonical_hash(_json(value.assignment_input.model_dump(mode="json"))),
        "production_snapshot_hash": production_hash,
    })
    assigned: JsonValue = _json({
        "assignment_hash": value.assignment.assignment_hash,
        "assignment_bucket": value.assignment.assignment_bucket,
        "observation_batch_hashes": [batch.batch_hash for batch in value.observation_batches],
        "sample_record_hashes": [record.record_hash for batch in value.observation_batches for record in batch.records],
        "production_snapshot_hash": production_hash,
    })
    shadow = _json(value.shadow.model_dump(mode="json"))
    outcomes: JsonValue = _json({
        "adapter_hash": value.outcome_adapter.adapter_hash if value.outcome_adapter else None,
        "observation_hashes": [item.observation_hash for item in value.horizon_observations],
    })
    metrics = _json(derive_metrics(value).model_dump(mode="json"))
    decision = evaluate_paper(value)
    stopped: JsonValue = _json({"stop_code": decision.stop_code.value, "lifecycle_review_eligible": decision.lifecycle_review_eligible})
    return (
        (LedgerEventType.STARTED, value.run_id, started),
        (LedgerEventType.ASSIGNED, value.shadow.sample_id, assigned),
        (LedgerEventType.SHADOW, value.shadow.sample_id, shadow),
        (LedgerEventType.OUTCOME, value.run_id, outcomes),
        (LedgerEventType.DRIFT, value.run_id, metrics),
        (LedgerEventType.STOPPED, value.run_id, stopped),
    )


def _match_specs(events: tuple[LedgerEvent, ...], expected: tuple[tuple[LedgerEventType, str, JsonValue], ...]) -> None:
    if len(events) != len(expected):
        raise ContractInvariantError("ledger event cardinality mismatch")
    for event, (event_type, entity_ref_id, payload) in zip(events, expected, strict=True):
        if event.event_type is not event_type or event.entity_ref_id != entity_ref_id or event.payload != payload:
            raise ContractInvariantError("ledger semantic binding mismatch")


def validate_ledger(value: PaperCohortInput, events: tuple[LedgerEvent, ...]) -> None:
    _validate_structure(events)
    expected = semantic_event_specs(value)
    event_types = tuple(event.event_type for event in events)
    normal_types = tuple(spec[0] for spec in expected)
    if event_types == normal_types:
        _match_specs(events, expected)
        return
    cancelled_indices = tuple(index for index, event in enumerate(events) if event.event_type is LedgerEventType.CANCELLED)
    resumed_indices = tuple(index for index, event in enumerate(events) if event.event_type is LedgerEventType.RESUMED)
    if len(cancelled_indices) != 1 or len(resumed_indices) > 1:
        raise ContractInvariantError("ledger requires one cancellation lifecycle")
    cancel_index = cancelled_indices[0]
    if cancel_index < 3 or cancel_index > len(expected) - 1:
        raise ContractInvariantError("ledger cancellation point is invalid")
    _match_specs(events[:cancel_index], expected[:cancel_index])
    cancelled = events[cancel_index]
    reason = cancelled.payload.get("reason") if isinstance(cancelled.payload, dict) else None
    if cancelled.entity_ref_id != value.run_id or cancelled.payload != {"reason": reason} or not isinstance(reason, str):
        raise ContractInvariantError("cancelled event is not semantically bound")
    if not resumed_indices:
        if cancel_index != len(events) - 1:
            raise ContractInvariantError("cancelled history has trailing events")
        return
    resume_index = resumed_indices[0]
    if resume_index != cancel_index + 1:
        raise ContractInvariantError("resume must immediately follow cancellation")
    resumed = events[resume_index]
    if resumed.entity_ref_id != value.run_id or resumed.payload != {"checkpoint_hash": cancelled.event_hash}:
        raise ContractInvariantError("resumed event checkpoint mismatch")
    _match_specs(events[resume_index + 1 :], expected[cancel_index:])


def checkpoint_from_cancelled(value: PaperCohortInput, events: tuple[LedgerEvent, ...]) -> ResumeCheckpoint:
    validate_ledger(value, events)
    if not events or events[-1].event_type is not LedgerEventType.CANCELLED:
        raise ContractInvariantError("resume checkpoint requires validated cancelled head")
    samples = tuple(record.sample_id for batch in value.observation_batches for record in batch.records)
    return ResumeCheckpoint(run_id=value.run_id, policy_id=value.policy.policy_id, candidate_version=value.candidate_version, policy_hash=value.policy.policy_hash, last_event_index=events[-1].event_index, last_event_hash=events[-1].event_hash, recorded_sample_ids=samples)


def cancelled_decision(value: PaperCohortInput, events: tuple[LedgerEvent, ...]) -> PaperDecision:
    _ = checkpoint_from_cancelled(value, events)
    reason = events[-1].payload.get("reason") if isinstance(events[-1].payload, dict) else None
    if not isinstance(reason, str):
        raise ContractInvariantError("cancelled ledger requires an operator reason")
    return PaperDecision(stop_code=PaperStopCode.CANCELLED, lifecycle_review_eligible=False, reasons=(reason,), metrics=derive_metrics(value))


def decide_resume(value: PaperCohortInput, events: tuple[LedgerEvent, ...], checkpoint: ResumeCheckpoint, request: ResumeRequest) -> ResumeDecision:
    try:
        derived = checkpoint_from_cancelled(value, events)
    except ContractInvariantError:
        return ResumeDecision(resume_allowed=False, stop_code=PaperStopCode.CONTAMINATION, reason="invalid_cancelled_history")
    identity_matches = checkpoint == derived and request.run_id == derived.run_id and request.policy_id == derived.policy_id and request.candidate_version == derived.candidate_version and request.prev_event_hash == derived.last_event_hash and request.next_event_index == derived.last_event_index + 1
    if not identity_matches:
        return ResumeDecision(resume_allowed=False, stop_code=PaperStopCode.CONTAMINATION, reason="resume_identity_mismatch")
    if request.write_sample_id in derived.recorded_sample_ids:
        return ResumeDecision(resume_allowed=False, stop_code=PaperStopCode.CONTAMINATION, reason="duplicate_shadow_resume")
    return ResumeDecision(resume_allowed=True, stop_code=None, reason="resume_valid")
