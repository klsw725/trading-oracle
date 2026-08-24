from typing import Final

from pydantic import TypeAdapter

from src.v17.database import Connection

from .errors import V18Error
from .models import CohortManifest, OutcomeEvaluation, PredictionRecord
from .policies import ELIGIBILITY_POLICY

_PREDICTION: Final = TypeAdapter(PredictionRecord)
_OUTCOME: Final = TypeAdapter(OutcomeEvaluation)
_COHORT: Final = TypeAdapter(CohortManifest)


def _member(
    connection: Connection, manifest: CohortManifest, prediction_id: str
) -> tuple[str, str, int]:
    prediction_row = connection.execute(
        "SELECT body_json,current_state FROM predictions WHERE prediction_id=?",
        (prediction_id,),
    ).fetchone()
    outcome_row = connection.execute(
        "SELECT body_json,body_hash FROM outcome_evaluations WHERE prediction_id=?",
        (prediction_id,),
    ).fetchone()
    match prediction_row, outcome_row:  # noqa: MATCH_OK - SQLite member rows are runtime-shaped.
        case (str(prediction_body), "EVALUATED"), (str(outcome_body), str(outcome_hash)):
            prediction = _PREDICTION.validate_json(prediction_body)
            outcome = _OUTCOME.validate_json(outcome_body)
        case _:
            raise V18Error("COHORT_MEMBER_INELIGIBLE", prediction_id)
    specification = manifest.specification
    namespace = specification.namespace
    if (
        prediction.namespace.market is not namespace.market
        or prediction.namespace.currency is not namespace.currency
        or prediction.namespace.account_id != namespace.account_id
        or prediction.namespace.arm_id != namespace.arm_id
        or prediction.horizon_sessions != specification.horizon_sessions
        or prediction.lineage.source_policy_version != specification.source_policy_version
        or prediction.lineage.calendar_version != specification.calendar_version
        or prediction.lineage.price_adjustment_version != specification.price_adjustment_version
        or outcome.evaluator_policy_version != specification.evaluator_policy_version
        or outcome.maturity_as_of > specification.cutoff_as_of
        or prediction.recorded_as_of > specification.cutoff_as_of
        or prediction.perspective_scores_as_of > specification.cutoff_as_of
        or manifest.decisions.get(prediction_id) != "INCLUDED"
        or manifest.outcome_hashes.get(prediction_id) != outcome_hash
    ):
        raise V18Error("COHORT_MEMBER_INELIGIBLE", prediction_id)
    return (
        prediction.namespace.symbol,
        prediction.prediction_session,
        prediction.horizon_sessions,
    )


def validate_cohorts(connection: Connection) -> None:
    rows = connection.execute(
        "SELECT body_json FROM cohort_manifests ORDER BY cohort_id"
    ).fetchall()
    for row in rows:
        match row:  # noqa: MATCH_OK - SQLite cohort rows are runtime-shaped.
            case (str(body),):
                manifest = _COHORT.validate_json(body)
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "cohort membership")
        if len(manifest.member_ids) < ELIGIBILITY_POLICY.minimum_samples:
            raise V18Error("COHORT_TOO_SMALL", str(len(manifest.member_ids)))
        observations: set[tuple[str, str, int]] = set()
        symbol_counts: dict[str, int] = {}
        for prediction_id in manifest.member_ids:
            observation = _member(connection, manifest, prediction_id)
            if observation in observations:
                raise V18Error("COHORT_DUPLICATE_MEMBER", prediction_id)
            observations.add(observation)
            symbol = observation[0]
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
            if symbol_counts[symbol] > ELIGIBILITY_POLICY.per_symbol_cap:
                raise V18Error("COHORT_MEMBER_INELIGIBLE", symbol)
