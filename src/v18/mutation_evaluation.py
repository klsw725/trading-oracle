from .acceptance_models import ProbeResult, passed
from .acceptance_support import Scenario, expect_code, prediction, row_count
from .models import AdjustedClose, Currency, Market, Namespace, PredictionRecord
from .outcomes import store_evaluation
from .policies import EVALUATOR_POLICY


def _registered(
    scenario: Scenario,
) -> tuple[PredictionRecord, tuple[AdjustedClose, ...]]:
    record = prediction(0)
    _ = scenario.repository.register_prediction(record)
    return record, scenario.fixture.prices


def immature_as_of() -> ProbeResult:
    with Scenario.open() as scenario:
        record, prices = _registered(scenario)
        expect_code(
            lambda: store_evaluation(
                scenario.repository, record.prediction_id, scenario.fixture.sessions,
                prices, "2026-01-05T06:29:59Z", EVALUATOR_POLICY,
            ),
            "OUTCOME_IMMATURE",
        )
        if row_count(scenario.repository, "outcome_evaluations") != 0:
            raise AssertionError("immature evaluation persisted")
    return passed("immature_as_of", "OUTCOME_IMMATURE")


def calendar_version_drift() -> ProbeResult:
    with Scenario.open() as scenario:
        record, prices = _registered(scenario)
        drifted = tuple(
            item.model_copy(update={"calendar_version": "drifted"})
            for item in scenario.fixture.sessions
        )
        expect_code(
            lambda: store_evaluation(
                scenario.repository, record.prediction_id, drifted, prices,
                "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
            ),
            "CALENDAR_IDENTITY_MISMATCH",
        )
    return passed("calendar_version_drift", "CALENDAR_IDENTITY_MISMATCH")


def raw_price_substitution() -> ProbeResult:
    with Scenario.open() as scenario:
        record, prices = _registered(scenario)
        raw = tuple(item.model_copy(update={"adjustment_version": "raw.close.1"}) for item in prices)
        expect_code(
            lambda: store_evaluation(
                scenario.repository, record.prediction_id, scenario.fixture.sessions,
                raw, "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
            ),
            "PRICE_ADJUSTMENT_MISMATCH",
        )
    return passed("raw_price_substitution", "PRICE_ADJUSTMENT_MISMATCH")


def missing_target_price() -> ProbeResult:
    with Scenario.open() as scenario:
        record, prices = _registered(scenario)
        missing = tuple(
            item for item in prices
            if not (item.namespace == record.namespace and item.session == "2026-01-05")
        )
        expect_code(
            lambda: store_evaluation(
                scenario.repository, record.prediction_id, scenario.fixture.sessions,
                missing, "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
            ),
            "TARGET_PRICE_MISSING",
        )
    return passed("missing_target_price", "TARGET_PRICE_MISSING")


def duplicate_target_price() -> ProbeResult:
    with Scenario.open() as scenario:
        record, prices = _registered(scenario)
        expect_code(
            lambda: store_evaluation(
                scenario.repository, record.prediction_id, scenario.fixture.sessions,
                prices + tuple(
                    item for item in prices
                    if item.namespace == record.namespace and item.session == "2026-01-05"
                ), "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
            ),
            "TARGET_PRICE_AMBIGUOUS",
        )
    return passed("duplicate_target_price", "TARGET_PRICE_AMBIGUOUS")


def cross_market_price() -> ProbeResult:
    with Scenario.open() as scenario:
        record, prices = _registered(scenario)
        original = next(item for item in prices if item.namespace == record.namespace)
        wrong = AdjustedClose(
            namespace=Namespace(
                market=Market.US, currency=Currency.USD,
                account_id=record.namespace.account_id, arm_id=record.namespace.arm_id,
                symbol=record.namespace.symbol,
            ),
            session=original.session,
            adjusted_close_minor=original.adjusted_close_minor,
            adjustment_version=original.adjustment_version,
            dataset_hash=original.dataset_hash,
        )
        expect_code(
            lambda: store_evaluation(
                scenario.repository, record.prediction_id, scenario.fixture.sessions,
                tuple(wrong if item is original else item for item in prices),
                "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
            ),
            "NAMESPACE_MISMATCH",
        )
    return passed("cross_market_price", "NAMESPACE_MISMATCH")


def evaluation_payload_conflict() -> ProbeResult:
    with Scenario.open() as scenario:
        record, prices = _registered(scenario)
        _ = store_evaluation(
            scenario.repository, record.prediction_id, scenario.fixture.sessions,
            prices, "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
        )
        changed = tuple(
            item.model_copy(update={"adjusted_close_minor": item.adjusted_close_minor + 100})
            if item.namespace == record.namespace else item
            for item in prices
        )
        expect_code(
            lambda: store_evaluation(
                scenario.repository, record.prediction_id, scenario.fixture.sessions,
                changed, "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
            ),
            "EVALUATION_IMMUTABLE",
        )
    return passed("evaluation_payload_conflict", "EVALUATION_IMMUTABLE")


EVALUATION_MUTATIONS = (
    immature_as_of,
    calendar_version_drift,
    raw_price_substitution,
    missing_target_price,
    duplicate_target_price,
    cross_market_price,
    evaluation_payload_conflict,
)
