from .acceptance_models import ProbeResult, passed
from .acceptance_support import Scenario, expect_code, prediction, row_count
from .models import Action, Market
from .sessions import target_session


def prediction_duplicate_retry() -> ProbeResult:
    with Scenario.open() as scenario:
        record = prediction(0)
        first = scenario.repository.register_prediction(record)
        counts = (row_count(scenario.repository, "predictions"), row_count(scenario.repository, "measurement_events"))
        for _ in range(10):
            duplicate = scenario.repository.register_prediction(record)
            if not duplicate.duplicate or duplicate.event_id != first.event_id:
                raise AssertionError("duplicate registration changed result")
        if counts != (
            row_count(scenario.repository, "predictions"),
            row_count(scenario.repository, "measurement_events"),
        ):
            raise AssertionError("duplicate registration changed state")
    return passed("prediction_duplicate_retry", "stored result")


def prediction_identity_conflict() -> ProbeResult:
    with Scenario.open() as scenario:
        first = prediction(0, recommendation_id="shared-recommendation")
        second = prediction(
            0, action=Action.SELL, recommendation_id="shared-recommendation"
        )
        _ = scenario.repository.register_prediction(first)
        expect_code(
            lambda: scenario.repository.register_prediction(second),
            "PREDICTION_IDENTITY_CONFLICT",
        )
    return passed("prediction_identity_conflict", "PREDICTION_IDENTITY_CONFLICT")


def legacy_missing_identity() -> ProbeResult:
    with Scenario.open() as scenario:
        stored = scenario.repository.quarantine_legacy(
            b'{"symbol":"005930"}',
            "data/snapshots/legacy.json",
            "legacy.snapshot.unknown",
            ("MISSING_RUNTIME_IDENTITY", "MISSING_HORIZON"),
            "2026-01-05T21:00:00Z",
        )
        if stored.record.schema_version != "v18.legacy-quarantine.1":
            raise AssertionError("legacy input was not quarantined")
        if row_count(scenario.repository, "predictions") != 0:
            raise AssertionError("legacy input became a prediction")
    return passed("legacy_missing_identity", "LEGACY_SNAPSHOT_QUARANTINED")


def quarantine_promotion() -> ProbeResult:
    with Scenario.open() as scenario:
        stored = scenario.repository.quarantine_legacy(
            b"legacy", "data/snapshots/legacy.json", "legacy.snapshot.unknown",
            ("MISSING_IDENTITY",), "2026-01-05T21:00:00Z",
        )
        expect_code(
            lambda: scenario.repository.get_prediction(stored.record.quarantine_id),
            "INELIGIBLE_QUARANTINE_RECORD",
        )
    return passed("quarantine_promotion", "INELIGIBLE_QUARANTINE_RECORD")


def weekend_horizon() -> ProbeResult:
    with Scenario.open() as scenario:
        target = target_session(prediction(0), scenario.fixture.sessions)
        if target.session != "2026-01-05":
            raise AssertionError("closed weekend counted as a session")
    return passed("weekend_horizon", "exact target maintained")


def early_close_horizon() -> ProbeResult:
    with Scenario.open() as scenario:
        target = target_session(
            prediction(0, market=Market.US, horizon=3), scenario.fixture.sessions
        )
        if target.session != "2026-01-07":
            raise AssertionError("early close was not counted")
    return passed("early_close_horizon", "exact target maintained")


PREDICTION_MUTATIONS = (
    prediction_duplicate_retry,
    prediction_identity_conflict,
    legacy_missing_identity,
    quarantine_promotion,
    weekend_horizon,
    early_close_horizon,
)
