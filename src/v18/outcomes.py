from dataclasses import dataclass
from typing import Final

from pydantic import TypeAdapter

from .canonical import canonical_hash, canonical_json, model_json
from .errors import V18Error
from .evaluator import evaluate_prediction, price_content_hash
from .models import AdjustedClose, CalendarSession, OutcomeEvaluation
from .policies import EvaluatorPolicy
from .repository import MeasurementRepository, hit
from .sessions import calendar_content_hash
from .validation import canonical_utc

_OUTCOME: Final = TypeAdapter(OutcomeEvaluation)


@dataclass(frozen=True, slots=True)
class StoredOutcome:
    outcome: OutcomeEvaluation
    duplicate: bool
    event_id: str


def _existing(repository: MeasurementRepository, prediction_id: str) -> tuple[OutcomeEvaluation, str] | None:
    row = repository.connection.execute(
        "SELECT body_json,event_id FROM outcome_evaluations WHERE prediction_id=?",
        (prediction_id,),
    ).fetchone()
    match row:  # noqa: MATCH_OK - SQLite outcome rows are runtime-shaped.
        case None:
            return None
        case (str(body), str(event_id)):
            return _OUTCOME.validate_json(body), event_id
        case _:
            raise V18Error("DATABASE_ROW_INVALID", "outcome")


def store_evaluation(
    repository: MeasurementRepository,
    prediction_id: str,
    sessions: tuple[CalendarSession, ...],
    prices: tuple[AdjustedClose, ...],
    as_of: str,
    policy: EvaluatorPolicy,
    *,
    fault: str | None = None,
) -> StoredOutcome:
    _ = canonical_utc(as_of)
    prediction = repository.get_prediction(prediction_id)
    if as_of < prediction.recorded_as_of or as_of < prediction.perspective_scores_as_of:
        raise V18Error("MEASUREMENT_LEAKAGE", prediction_id)
    repository.begin()
    try:
        existing = _existing(repository, prediction_id)
        if existing is not None:
            stored, event_id = existing
            selected = tuple(
                item
                for item in prices
                if item.namespace == prediction.namespace
                and item.session == stored.target_session
            )
            try:
                matches = (
                    len(selected) == 1
                    and selected[0].adjusted_close_minor == stored.target_adjusted_price_minor
                    and price_content_hash(prices) == stored.price_dataset_hash
                    and calendar_content_hash(sessions) == stored.calendar_hash
                    and policy.version == stored.evaluator_policy_version
                    and as_of == stored.maturity_as_of
                )
            except V18Error as error:
                raise V18Error("EVALUATION_IMMUTABLE", prediction_id) from error
            if not matches:
                raise V18Error("EVALUATION_IMMUTABLE", prediction_id)
            repository.connection.commit()
            return StoredOutcome(stored, True, event_id)
        outcome = evaluate_prediction(prediction, sessions, prices, as_of, policy)
        body = model_json(outcome)
        body_hash = canonical_hash(body)
        semantic = canonical_hash(
            {"evaluator_policy_version": policy.version, "prediction_id": prediction_id}
        )
        if prediction.current_state != "REGISTERED":
            raise V18Error("EVALUATION_IMMUTABLE", prediction_id)
        mature_event = repository.append_event(
            "prediction.matured",
            prediction_id,
            canonical_hash({"kind": "mature", "prediction_id": prediction_id}),
            {"target_price_minor": outcome.target_adjusted_price_minor,
             "target_session": outcome.target_session},
            as_of,
        )
        _ = repository.connection.execute(
            "UPDATE predictions SET current_state='MATURE',target_session=?,target_price_minor=? "
            + "WHERE prediction_id=?",
            (outcome.target_session, outcome.target_adjusted_price_minor, prediction_id),
        )
        hit(fault, "after_projection_update")
        event_id = repository.append_event(
            "outcome.evaluated",
            outcome.outcome_id,
            semantic,
            {"mature_event_id": mature_event, "outcome_id": outcome.outcome_id},
            as_of,
        )
        hit(fault, "after_event_append")
        _ = repository.connection.execute(
            "INSERT INTO outcome_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                outcome.outcome_id,
                prediction_id,
                outcome.target_session,
                outcome.target_adjusted_price_minor,
                outcome.return_bps,
                outcome.verdict.value,
                as_of,
                policy.version,
                outcome.calendar_hash,
                outcome.price_dataset_hash,
                canonical_json(body).decode("utf-8"),
                body_hash,
                event_id,
            ),
        )
        hit(fault, "after_immutable_row_insert")
        _ = repository.connection.execute(
            "UPDATE predictions SET current_state='EVALUATED',outcome_id=? WHERE prediction_id=?",
            (outcome.outcome_id, prediction_id),
        )
        repository.store_result(
            "evaluate", semantic, body_hash, {"outcome_id": outcome.outcome_id}, event_id
        )
        hit(fault, "after_idempotency_insert")
        persisted = _existing(repository, prediction_id)
        if persisted is None or canonical_hash(model_json(persisted[0])) != body_hash:
            raise V18Error("OUTCOME_HASH_MISMATCH", prediction_id)
        hit(fault, "after_final_invariant")
        repository.reconcile()
        repository.connection.commit()
        return StoredOutcome(outcome, False, event_id)
    except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then re-raise.
        repository.connection.rollback()
        raise
