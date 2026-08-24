from typing import Final

from pydantic import TypeAdapter

from src.v17.database import Connection

from .canonical import JsonValue, canonical_hash, canonical_json, model_json, parse_json
from .errors import V18Error
from .models import CohortManifest, OutcomeEvaluation, PolicyCandidate, PredictionRecord
from .predictions import validate_prediction_record
from .reconcile_cohorts import validate_cohorts
from .schema import GENESIS_HASH, MEASUREMENT_EVENT_SCHEMA_VERSION

_PREDICTION: Final = TypeAdapter(PredictionRecord)
_OUTCOME: Final = TypeAdapter(OutcomeEvaluation)
_COHORT: Final = TypeAdapter(CohortManifest)
_CANDIDATE: Final = TypeAdapter(PolicyCandidate)

_EVENT_TYPES: Final = {
    "prediction.registered",
    "legacy.quarantined",
    "prediction.matured",
    "outcome.evaluated",
    "cohort.frozen",
}


def _measurement_events(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT sequence,event_id,event_schema_version,event_type,aggregate_id,semantic_key,"
        + "payload_json,previous_event_hash,event_hash,created_as_of "
        + "FROM measurement_events ORDER BY sequence"
    ).fetchall()
    previous = GENESIS_HASH
    for expected_sequence, row in enumerate(rows, start=1):
        match row:  # noqa: MATCH_OK - SQLite event rows are runtime-shaped.
            case (
                int(sequence), str(event_id), str(schema), str(event_type),
                str(aggregate_id), str(semantic), str(payload_json),
                str(stored_previous), str(event_hash), str(created_as_of),
            ):
                pass
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "measurement event")
        if sequence != expected_sequence or schema != MEASUREMENT_EVENT_SCHEMA_VERSION:
            raise V18Error("MEASUREMENT_EVENT_SEQUENCE_INVALID", str(sequence))
        if event_type not in _EVENT_TYPES or stored_previous != previous:
            raise V18Error("MEASUREMENT_EVENT_CHAIN_INVALID", event_id)
        payload = parse_json(payload_json)
        body: JsonValue = {
            "aggregate_id": aggregate_id,
            "created_as_of": created_as_of,
            "event_schema_version": schema,
            "event_type": event_type,
            "payload": payload,
            "previous_event_hash": stored_previous,
            "semantic_key": semantic,
        }
        expected_id = canonical_hash({"event": body, "kind": "event-id"})
        expected_hash = canonical_hash({"event": body, "event_id": expected_id})
        if (event_id, event_hash) != (expected_id, expected_hash):
            raise V18Error("MEASUREMENT_EVENT_HASH_INVALID", event_id)
        previous = event_hash


def _predictions(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT prediction_id,body_json,body_hash,current_state,target_session,"
        + "target_price_minor,outcome_id FROM predictions ORDER BY prediction_id"
    ).fetchall()
    for row in rows:
        match row:  # noqa: MATCH_OK - SQLite prediction rows are runtime-shaped.
            case (str(prediction_id), str(body), str(body_hash), str(state), target, price, outcome_id):
                pass
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "prediction reconciliation")
        record = _PREDICTION.validate_json(body)
        validate_prediction_record(record)
        if record.prediction_id != prediction_id or canonical_hash(model_json(record)) != body_hash:
            raise V18Error("PREDICTION_HASH_MISMATCH", prediction_id)
        outcome = connection.execute(
            "SELECT target_session,target_adjusted_price_minor,outcome_id "
            + "FROM outcome_evaluations WHERE prediction_id=?",
            (prediction_id,),
        ).fetchone()
        matured = connection.execute(
            "SELECT payload_json FROM measurement_events "
            + "WHERE aggregate_id=? AND event_type='prediction.matured'",
            (prediction_id,),
        ).fetchone()
        if (
            state == "REGISTERED"
            and (target, price, outcome_id, outcome, matured)
            == (None, None, None, None, None)
        ):
            continue
        expected_matured: JsonValue | None = None
        if isinstance(target, str) and isinstance(price, int):
            expected_matured = {
                "target_price_minor": price,
                "target_session": target,
            }
        if (
            state == "MATURE"
            and isinstance(target, str)
            and isinstance(price, int)
            and outcome_id is None
            and expected_matured is not None
            and matured == (canonical_json_text(expected_matured),)
        ):
            continue
        evaluated = connection.execute(
            "SELECT 1 FROM measurement_events "
            + "WHERE aggregate_id=? AND event_type='outcome.evaluated'",
            (outcome_id,),
        ).fetchone()
        if (
            state == "EVALUATED"
            and outcome == (target, price, outcome_id)
            and expected_matured is not None
            and matured == (canonical_json_text(expected_matured),)
            and evaluated == (1,)
        ):
            continue
        raise V18Error("PREDICTION_PROJECTION_DRIFT", prediction_id)


def _immutable_artifacts(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT prediction_id,body_json,body_hash,outcome_id FROM outcome_evaluations "
        + "ORDER BY prediction_id"
    ).fetchall()
    for row in rows:
        match row:  # noqa: MATCH_OK - SQLite outcome rows are runtime-shaped.
            case (str(prediction_id), str(body), str(body_hash), str(outcome_id)):
                pass
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "outcome reconciliation")
        outcome = _OUTCOME.validate_json(body)
        identity = model_json(outcome, exclude={"outcome_id"})
        if (
            outcome.prediction_id != prediction_id
            or outcome.outcome_id != outcome_id
            or canonical_hash(model_json(outcome)) != body_hash
            or canonical_hash(identity) != outcome_id
        ):
            raise V18Error("OUTCOME_HASH_MISMATCH", str(prediction_id))
    rows = connection.execute(
        "SELECT cohort_id,body_json,manifest_hash FROM cohort_manifests ORDER BY cohort_id"
    ).fetchall()
    for row in rows:
        match row:  # noqa: MATCH_OK - SQLite cohort rows are runtime-shaped.
            case (str(cohort_id), str(body), str(manifest_hash)):
                pass
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "cohort reconciliation")
        manifest = _COHORT.validate_json(body)
        identity = model_json(manifest, exclude={"cohort_id", "manifest_hash"})
        if cohort_id != manifest_hash or canonical_hash(identity) != manifest_hash:
            raise V18Error("COHORT_HASH_MISMATCH", str(cohort_id))


def _candidates(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT candidate_id,body_json,body_hash,current_status FROM policy_candidates "
        + "ORDER BY candidate_id"
    ).fetchall()
    for row in rows:
        match row:  # noqa: MATCH_OK - SQLite candidate rows are runtime-shaped.
            case (str(candidate_id), str(body), str(body_hash), str(status)):
                pass
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "candidate reconciliation")
        candidate = _CANDIDATE.validate_json(body)
        cohort_row = connection.execute(
            "SELECT body_json FROM cohort_manifests WHERE cohort_id=?",
            (candidate.cohort_id,),
        ).fetchone()
        match cohort_row:  # noqa: MATCH_OK - SQLite cohort reference is runtime-shaped.
            case (str(cohort_body),):
                cohort = _COHORT.validate_json(cohort_body)
            case _:
                raise V18Error("COHORT_MEMBER_INELIGIBLE", candidate.cohort_id)
        if candidate.namespace != cohort.specification.namespace:
            raise V18Error("NAMESPACE_MISMATCH", candidate.candidate_id)
        identity = model_json(candidate, exclude={"candidate_id"})
        if (
            candidate.candidate_id != candidate_id
            or canonical_hash(model_json(candidate)) != body_hash
            or canonical_hash(identity) != candidate_id
        ):
            raise V18Error("CANDIDATE_HASH_MISMATCH", candidate_id)
        last = connection.execute(
            "SELECT event_type FROM candidate_events WHERE candidate_id=? ORDER BY sequence DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
        expected_event = f"candidate.{status.lower()}"
        if last != (expected_event,):
            raise V18Error("CANDIDATE_PROJECTION_DRIFT", candidate_id)


def _candidate_events(connection: Connection) -> None:
    heads: dict[str, str] = {}
    rows = connection.execute(
        "SELECT event_schema_version,event_id,candidate_id,event_type,decision_id,"
        + "previous_event_hash,event_hash,transition_as_of,rollback_of_candidate_id,payload_json "
        + "FROM candidate_events ORDER BY sequence"
    ).fetchall()
    for row in rows:
        match row:  # noqa: MATCH_OK - SQLite candidate event rows are runtime-shaped.
            case (
                "v18.policy-candidate-event.1", str(event_id), str(candidate_id),
                str(), str(), str(previous), str(event_hash),
                str(), rollback_of, str(payload_json),
            ):
                pass
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "candidate event")
        if previous != heads.get(candidate_id, GENESIS_HASH):
            raise V18Error("CANDIDATE_EVENT_CHAIN_INVALID", event_id)
        payload = parse_json(payload_json)
        expected_id = canonical_hash({"candidate_event": payload, "previous": previous})
        expected_hash = canonical_hash({"event_id": expected_id, "payload": payload, "previous": previous})
        if (event_id, event_hash) != (expected_id, expected_hash):
            raise V18Error("CANDIDATE_EVENT_HASH_INVALID", event_id)
        if rollback_of is not None and rollback_of != candidate_id:
            raise V18Error("CANDIDATE_HISTORY_IMMUTABLE", candidate_id)
        heads[candidate_id] = event_hash


def _idempotency(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT result_json,result_hash FROM measurement_idempotency ORDER BY command_type,semantic_key"
    ).fetchall()
    for result_json, result_hash in rows:
        if not isinstance(result_json, str) or not isinstance(result_hash, str):
            raise V18Error("DATABASE_ROW_INVALID", "measurement idempotency")
        if canonical_hash(parse_json(result_json)) != result_hash:
            raise V18Error("MEASUREMENT_IDEMPOTENCY_DRIFT", result_hash)


def reconcile(connection: Connection) -> None:
    _measurement_events(connection)
    _predictions(connection)
    _immutable_artifacts(connection)
    validate_cohorts(connection)
    _candidate_events(connection)
    _candidates(connection)
    _idempotency(connection)


def canonical_json_text(value: JsonValue) -> str:
    return canonical_json(value).decode("utf-8")
