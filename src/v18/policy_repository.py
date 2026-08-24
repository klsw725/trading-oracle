from typing import Final, Never

from pydantic import TypeAdapter

from .canonical import JsonValue, canonical_hash, canonical_json, model_json
from .candidates import build_candidate, validate_candidate
from .cohorts import load_manifest
from .errors import V18Error
from .fixtures import load_fixture
from .models import CandidateStatus, CandidateTransition, PolicyCandidate
from .objective import perspective_contributions
from .policies import WEIGHT_POLICY
from .repository import MeasurementRepository, hit
from .schema import GENESIS_HASH
from .validation import canonical_utc

_CANDIDATE: Final = TypeAdapter(PolicyCandidate)


def _candidate(repository: MeasurementRepository, candidate_id: str) -> PolicyCandidate:
    row = repository.connection.execute(
        "SELECT body_json,current_status FROM policy_candidates WHERE candidate_id=?",
        (candidate_id,),
    ).fetchone()
    match row:  # noqa: MATCH_OK - SQLite candidate rows are runtime-shaped.
        case (str(body), str(status)):
            candidate = _CANDIDATE.validate_json(body)
            return candidate.model_copy(update={"status": CandidateStatus(status)})
        case None:
            raise V18Error("CANDIDATE_NOT_FOUND", candidate_id)
        case _:
            raise V18Error("DATABASE_ROW_INVALID", "candidate")


def _append_candidate_event(
    repository: MeasurementRepository,
    candidate_id: str,
    event_type: str,
    decision_id: str,
    transition_as_of: str,
    rollback_of: str | None = None,
) -> str:
    row = repository.connection.execute(
        "SELECT event_hash FROM candidate_events WHERE candidate_id=? ORDER BY sequence DESC LIMIT 1",
        (candidate_id,),
    ).fetchone()
    match row:  # noqa: MATCH_OK - SQLite candidate event head is runtime-shaped.
        case None:
            previous = GENESIS_HASH
        case (str(digest),):
            previous = digest
        case _:
            raise V18Error("DATABASE_ROW_INVALID", "candidate event head")
    payload: JsonValue = {
        "candidate_id": candidate_id,
        "decision_id": decision_id,
        "event_type": event_type,
        "rollback_of_candidate_id": rollback_of,
        "transition_as_of": transition_as_of,
    }
    event_id = canonical_hash({"candidate_event": payload, "previous": previous})
    event_hash = canonical_hash({"event_id": event_id, "payload": payload, "previous": previous})
    _ = repository.connection.execute(
        "INSERT INTO candidate_events(event_schema_version,event_id,candidate_id,event_type,decision_id,"
        + "previous_event_hash,event_hash,transition_as_of,rollback_of_candidate_id,payload_json) "
        + "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "v18.policy-candidate-event.1", event_id, candidate_id, event_type, decision_id, previous, event_hash,
            transition_as_of, rollback_of, canonical_json(payload).decode("utf-8"),
        ),
    )
    return event_id


def propose_candidate(
    repository: MeasurementRepository,
    candidate: PolicyCandidate,
    *,
    fault: str | None = None,
) -> PolicyCandidate:
    validate_candidate(candidate, WEIGHT_POLICY)
    body = model_json(candidate)
    body_hash = canonical_hash(body)
    semantic = canonical_hash(
        {"candidate_version": candidate.candidate_version, "kind": "candidate.proposed"}
    )
    repository.begin()
    try:
        manifest = load_manifest(repository, candidate.cohort_id)
        if candidate.namespace != manifest.specification.namespace:
            raise V18Error("NAMESPACE_MISMATCH", candidate.candidate_id)
        contributions = perspective_contributions(repository, manifest, WEIGHT_POLICY)
        fixture = load_fixture(candidate.namespace.account_id, candidate.namespace.arm_id)
        expected = build_candidate(
            manifest,
            manifest.specification.namespace,
            contributions,
            tuple(item for item in fixture.sessions if item.market is candidate.namespace.market),
            candidate.created_as_of,
            WEIGHT_POLICY,
        )
        if candidate != expected:
            raise V18Error("CANDIDATE_IDENTITY_CONFLICT", candidate.candidate_id)
        duplicate = repository.stored_result("propose_candidate", semantic, body_hash)
        if duplicate is not None:
            repository.connection.commit()
            return _candidate(repository, candidate.candidate_id)
        decision_id = canonical_hash(
            {"as_of": candidate.created_as_of, "candidate_id": candidate.candidate_id,
             "transition": "propose"}
        )
        event_id = _append_candidate_event(
            repository, candidate.candidate_id, "candidate.proposed",
            decision_id, candidate.created_as_of,
        )
        hit(fault, "after_event_append")
        namespace = candidate.namespace
        _ = repository.connection.execute(
            "INSERT INTO policy_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                candidate.candidate_id, candidate.candidate_version,
                candidate.base_policy_version, namespace.market.value,
                namespace.currency.value, namespace.account_id, namespace.arm_id,
                candidate.cohort_id, candidate.objective_version,
                canonical_json({key: value for key, value in candidate.weights.items()}).decode("utf-8"),
                candidate.effective_session, candidate.created_as_of, candidate.evidence_hash,
                canonical_json(body).decode("utf-8"), body_hash,
                CandidateStatus.PROPOSED.value, event_id,
            ),
        )
        hit(fault, "after_immutable_row_insert")
        repository.store_result(
            "propose_candidate", semantic, body_hash,
            {"candidate_id": candidate.candidate_id}, event_id,
        )
        hit(fault, "after_idempotency_insert")
        hit(fault, "after_final_invariant")
        repository.reconcile()
        repository.connection.commit()
        return candidate
    except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then re-raise.
        repository.connection.rollback()
        raise


def _next_status(
    current: CandidateStatus, transition: CandidateTransition
) -> CandidateStatus:
    match (current, transition):  # noqa: MATCH_OK - invalid state pairs raise typed failures.
        case (CandidateStatus.PROPOSED, CandidateTransition.APPROVE):
            return CandidateStatus.APPROVED
        case (CandidateStatus.PROPOSED | CandidateStatus.APPROVED, CandidateTransition.REJECT):
            return CandidateStatus.REJECTED
        case (CandidateStatus.APPROVED, CandidateTransition.SCHEDULE):
            return CandidateStatus.SCHEDULED
        case (CandidateStatus.SCHEDULED, CandidateTransition.ROLLBACK):
            return CandidateStatus.ROLLED_BACK
        case (CandidateStatus.REJECTED | CandidateStatus.ROLLED_BACK, _):
            raise V18Error("CANDIDATE_TRANSITION_INVALID", current.value)
        case _:
            raise V18Error("CANDIDATE_TRANSITION_INVALID", transition.value)


def transition_candidate(
    repository: MeasurementRepository,
    candidate_id: str,
    transition: CandidateTransition,
    as_of: str,
    *,
    fault: str | None = None,
) -> PolicyCandidate:
    _ = canonical_utc(as_of)
    repository.begin()
    try:
        candidate = _candidate(repository, candidate_id)
        next_status = _next_status(candidate.status, transition)
        latest = repository.connection.execute(
            "SELECT transition_as_of FROM candidate_events WHERE candidate_id=? "
            + "ORDER BY sequence DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
        match latest:  # noqa: MATCH_OK - SQLite candidate event rows are runtime-shaped.
            case (str(previous_as_of),) if as_of > previous_as_of:
                pass
            case _:
                raise V18Error("CANDIDATE_TRANSITION_INVALID", "non-monotonic as_of")
        decision_id = canonical_hash(
            {"as_of": as_of, "candidate_id": candidate_id, "transition": transition.value}
        )
        _ = _append_candidate_event(
            repository, candidate_id, f"candidate.{next_status.value.lower()}",
            decision_id, as_of,
            candidate_id if next_status is CandidateStatus.ROLLED_BACK else None,
        )
        hit(fault, "after_event_append")
        _ = repository.connection.execute(
            "UPDATE policy_candidates SET current_status=? WHERE candidate_id=?",
            (next_status.value, candidate_id),
        )
        hit(fault, "after_projection_update")
        updated = _candidate(repository, candidate_id)
        if updated.status is not next_status:
            raise V18Error("CANDIDATE_TRANSITION_INVALID", transition.value)
        hit(fault, "after_final_invariant")
        repository.reconcile()
        repository.connection.commit()
        return updated
    except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then re-raise.
        repository.connection.rollback()
        raise


def reject_candidate_history_mutation() -> Never:
    raise V18Error("CANDIDATE_HISTORY_IMMUTABLE", "candidate history is append-only")
