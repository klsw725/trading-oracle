from dataclasses import dataclass
from typing import Final

from pydantic import TypeAdapter

from .canonical import JsonValue, canonical_hash, canonical_json, model_json
from .errors import V18Error
from .models import CohortManifest, CohortSpecification, OutcomeEvaluation, PredictionRecord
from .policies import ELIGIBILITY_POLICY, EligibilityPolicy
from .repository import MeasurementRepository, hit

_OUTCOME: Final = TypeAdapter(OutcomeEvaluation)
_MANIFEST: Final = TypeAdapter(CohortManifest)


@dataclass(frozen=True, slots=True)
class StoredCohort:
    manifest: CohortManifest
    duplicate: bool
    event_id: str


def load_outcome(
    repository: MeasurementRepository, prediction_id: str
) -> tuple[OutcomeEvaluation, str]:
    row = repository.connection.execute(
        "SELECT body_json,body_hash FROM outcome_evaluations WHERE prediction_id=?",
        (prediction_id,),
    ).fetchone()
    match row:  # noqa: MATCH_OK - SQLite outcome rows are runtime-shaped.
        case (str(body), str(body_hash)):
            return _OUTCOME.validate_json(body), body_hash
        case None:
            raise V18Error("COHORT_MEMBER_INELIGIBLE", prediction_id)
        case _:
            raise V18Error("DATABASE_ROW_INVALID", "cohort outcome")


def load_manifest(
    repository: MeasurementRepository, cohort_id: str
) -> CohortManifest:
    row = repository.connection.execute(
        "SELECT body_json FROM cohort_manifests WHERE cohort_id=?", (cohort_id,)
    ).fetchone()
    match row:  # noqa: MATCH_OK - SQLite cohort rows are runtime-shaped.
        case (str(body),):
            return _MANIFEST.validate_json(body)
        case None:
            raise V18Error("COHORT_MEMBER_INELIGIBLE", cohort_id)
        case _:
            raise V18Error("DATABASE_ROW_INVALID", "cohort manifest")


def _eligible(
    prediction: PredictionRecord,
    outcome: OutcomeEvaluation,
    specification: CohortSpecification,
) -> None:
    namespace = specification.namespace
    if prediction.current_state != "EVALUATED":
        raise V18Error("COHORT_MEMBER_INELIGIBLE", prediction.prediction_id)
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
    ):
        raise V18Error("COHORT_MEMBER_INELIGIBLE", prediction.prediction_id)
    if outcome.maturity_as_of > specification.cutoff_as_of:
        raise V18Error("MEASUREMENT_LEAKAGE", prediction.prediction_id)
    if (
        prediction.recorded_as_of > specification.cutoff_as_of
        or prediction.perspective_scores_as_of > specification.cutoff_as_of
    ):
        raise V18Error("MEASUREMENT_LEAKAGE", prediction.prediction_id)


def build_manifest(
    repository: MeasurementRepository,
    specification: CohortSpecification,
    policy: EligibilityPolicy,
) -> CohortManifest:
    if specification.eligibility_policy_version != policy.version:
        raise V18Error("COHORT_MEMBER_INELIGIBLE", policy.version)
    if len(specification.prediction_ids) != len(set(specification.prediction_ids)):
        raise V18Error("COHORT_DUPLICATE_MEMBER", "prediction id")
    members: list[str] = []
    decisions: dict[str, str] = {}
    outcome_hashes: dict[str, str] = {}
    observations: set[tuple[str, str, int]] = set()
    symbol_counts: dict[str, int] = {}
    for prediction_id in sorted(specification.prediction_ids):
        prediction = repository.get_prediction(prediction_id)
        outcome, outcome_hash = load_outcome(repository, prediction_id)
        _eligible(prediction, outcome, specification)
        observation = (
            prediction.namespace.symbol,
            prediction.prediction_session,
            prediction.horizon_sessions,
        )
        if observation in observations:
            raise V18Error("COHORT_DUPLICATE_MEMBER", prediction_id)
        observations.add(observation)
        count = symbol_counts.get(prediction.namespace.symbol, 0)
        if count >= policy.per_symbol_cap:
            decisions[prediction_id] = "EXCLUDED_SYMBOL_CAP"
            continue
        symbol_counts[prediction.namespace.symbol] = count + 1
        members.append(prediction_id)
        decisions[prediction_id] = "INCLUDED"
        outcome_hashes[prediction_id] = outcome_hash
    if len(members) < policy.minimum_samples:
        raise V18Error("COHORT_TOO_SMALL", str(len(members)))
    decision_json: dict[str, JsonValue] = {key: value for key, value in decisions.items()}
    outcome_json: dict[str, JsonValue] = {key: value for key, value in outcome_hashes.items()}
    member_json: list[JsonValue] = list(members)
    body: JsonValue = {
        "decisions": decision_json,
        "member_ids": member_json,
        "outcome_hashes": outcome_json,
        "schema_version": "v18.cohort-manifest.1",
        "specification": model_json(specification),
    }
    manifest_hash = canonical_hash(body)
    return CohortManifest(
        cohort_id=manifest_hash,
        specification=specification,
        member_ids=tuple(members),
        decisions=decisions,
        outcome_hashes=outcome_hashes,
        manifest_hash=manifest_hash,
    )


def freeze_cohort(
    repository: MeasurementRepository,
    manifest: CohortManifest,
    *,
    fault: str | None = None,
) -> StoredCohort:
    body = model_json(manifest)
    body_hash = canonical_hash(body)
    semantic = canonical_hash(
        {"cohort_id": manifest.cohort_id, "kind": "cohort.frozen"}
    )
    repository.begin()
    try:
        expected = build_manifest(
            repository, manifest.specification, ELIGIBILITY_POLICY
        )
        if manifest != expected:
            raise V18Error("COHORT_MEMBER_INELIGIBLE", manifest.cohort_id)
        duplicate = repository.stored_result("freeze_cohort", semantic, body_hash)
        if duplicate is not None:
            repository.connection.commit()
            return StoredCohort(manifest, True, duplicate)
        event_id = repository.append_event(
            "cohort.frozen",
            manifest.cohort_id,
            semantic,
            {"cohort_id": manifest.cohort_id},
            manifest.specification.cutoff_as_of,
        )
        hit(fault, "after_event_append")
        spec = manifest.specification
        namespace = spec.namespace
        _ = repository.connection.execute(
            "INSERT INTO cohort_manifests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                manifest.cohort_id,
                namespace.market.value,
                namespace.currency.value,
                namespace.account_id,
                namespace.arm_id,
                spec.horizon_sessions,
                spec.source_policy_version,
                spec.evaluator_policy_version,
                spec.calendar_version,
                spec.price_adjustment_version,
                spec.eligibility_policy_version,
                spec.cutoff_as_of,
                canonical_json(list(manifest.member_ids)).decode("utf-8"),
                canonical_json({key: value for key, value in manifest.decisions.items()}).decode("utf-8"),
                canonical_json({key: value for key, value in manifest.outcome_hashes.items()}).decode("utf-8"),
                canonical_json(body).decode("utf-8"),
                manifest.manifest_hash,
                event_id,
            ),
        )
        hit(fault, "after_immutable_row_insert")
        repository.store_result(
            "freeze_cohort", semantic, body_hash,
            {"cohort_id": manifest.cohort_id}, event_id,
        )
        hit(fault, "after_idempotency_insert")
        hit(fault, "after_final_invariant")
        repository.reconcile()
        repository.connection.commit()
        return StoredCohort(manifest, False, event_id)
    except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then re-raise.
        repository.connection.rollback()
        raise
