from .acceptance_models import ProbeResult, passed
from .acceptance_support import (
    Scenario,
    candidate_value,
    cohort_specification,
    evaluated_predictions,
    expect_code,
    prediction,
    prepared_manifest,
)
from .candidates import build_candidate
from .canonical import canonical_hash, model_json
from .cohorts import build_manifest, freeze_cohort
from .outcomes import store_evaluation
from .models import Currency, Market, MeasurementNamespace
from .objective import perspective_contributions
from .policies import ELIGIBILITY_POLICY, EVALUATOR_POLICY, WEIGHT_POLICY
from .policy_repository import propose_candidate
from .sessions import target_session


def forged_prediction_rejected() -> ProbeResult:
    with Scenario.open() as scenario:
        forged = prediction(0).model_copy(
            update={"prediction_id": "forged-id", "source_payload_hash": "forged-source"}
        )
        expect_code(
            lambda: scenario.repository.register_prediction(forged),
            "PREDICTION_IDENTITY_CONFLICT",
        )
    return passed("forged_prediction_rejected", "identity recomputed")


def prediction_projection_drift() -> ProbeResult:
    with Scenario.open() as scenario:
        record = prediction(0)
        _ = scenario.repository.register_prediction(record)
        _ = scenario.repository.connection.execute(
            "UPDATE predictions SET current_state='MATURE',target_session='2099-01-01',"
            + "target_price_minor=1 WHERE prediction_id=?",
            (record.prediction_id,),
        )
        expect_code(scenario.repository.reconcile, "PREDICTION_PROJECTION_DRIFT")
    return passed("prediction_projection_drift", "event projection mismatch rejected")


def forged_candidate_rejected() -> ProbeResult:
    with Scenario.open() as scenario:
        forged = candidate_value(scenario).model_copy(update={"candidate_id": "forged-candidate"})
        expect_code(
            lambda: propose_candidate(scenario.repository, forged),
            "CANDIDATE_IDENTITY_CONFLICT",
        )
    return passed("forged_candidate_rejected", "candidate identity recomputed")


def incomplete_calendar_rejected() -> ProbeResult:
    with Scenario.open() as scenario:
        record = prediction(0)
        partial = tuple(
            item for item in scenario.fixture.sessions if item.session != "2026-01-05"
        )
        expect_code(
            lambda: target_session(record, partial),
            "CALENDAR_IDENTITY_MISMATCH",
        )
    return passed("incomplete_calendar_rejected", "calendar content hash mismatch")


def changed_price_rejected() -> ProbeResult:
    with Scenario.open() as scenario:
        record = prediction(0)
        _ = scenario.repository.register_prediction(record)
        changed = tuple(
            item.model_copy(update={"adjusted_close_minor": item.adjusted_close_minor + 1})
            if item.namespace == record.namespace else item
            for item in scenario.fixture.prices
        )
        expect_code(
            lambda: store_evaluation(
                scenario.repository,
                record.prediction_id,
                scenario.fixture.sessions,
                changed,
                "2026-01-05T06:30:00Z",
                EVALUATOR_POLICY,
            ),
            "PRICE_ADJUSTMENT_MISMATCH",
        )
    return passed("changed_price_rejected", "price content hash mismatch")


def forged_cohort_namespace_rejected() -> ProbeResult:
    with Scenario.open() as scenario:
        records = evaluated_predictions(scenario)
        manifest = build_manifest(
            scenario.repository, cohort_specification(records), ELIGIBILITY_POLICY
        )
        wrong_namespace = MeasurementNamespace(
            market=Market.US,
            currency=Currency.USD,
            account_id="other-account",
            arm_id="other-arm",
        )
        forged = manifest.model_copy(
            update={
                "specification": manifest.specification.model_copy(
                    update={"namespace": wrong_namespace}
                )
            }
        )
        identity = model_json(forged, exclude={"cohort_id", "manifest_hash"})
        digest = canonical_hash(identity)
        forged = forged.model_copy(
            update={"cohort_id": digest, "manifest_hash": digest}
        )
        expect_code(
            lambda: freeze_cohort(scenario.repository, forged),
            "COHORT_MEMBER_INELIGIBLE",
        )
    return passed("forged_cohort_namespace_rejected", "member namespace revalidated")


def cross_namespace_candidate_rejected() -> ProbeResult:
    with Scenario.open() as scenario:
        manifest = prepared_manifest(scenario)
        contributions = perspective_contributions(
            scenario.repository, manifest, WEIGHT_POLICY
        )
        wrong_namespace = MeasurementNamespace(
            market=Market.US,
            currency=Currency.USD,
            account_id="other-account",
            arm_id="other-arm",
        )
        expect_code(
            lambda: build_candidate(
                manifest,
                wrong_namespace,
                contributions,
                scenario.fixture.sessions,
                "2026-01-05T07:00:00Z",
                WEIGHT_POLICY,
            ),
            "NAMESPACE_MISMATCH",
        )
    return passed("cross_namespace_candidate_rejected", "cohort namespace enforced")


SECURITY_CHECKS = (
    forged_prediction_rejected,
    prediction_projection_drift,
    forged_candidate_rejected,
    incomplete_calendar_rejected,
    changed_price_rejected,
    forged_cohort_namespace_rejected,
    cross_namespace_candidate_rejected,
)
