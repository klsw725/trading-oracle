from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Callable, final

from .candidates import build_candidate
from .cohorts import build_manifest, freeze_cohort
from .errors import V18Error
from .fixtures import MeasurementFixture, load_fixture
from .models import (
    Action,
    CohortManifest,
    CohortSpecification,
    Currency,
    Lineage,
    Market,
    MeasurementNamespace,
    Namespace,
    PERSPECTIVE_IDS,
    PolicyCandidate,
    PredictionInput,
    PredictionRecord,
)
from .objective import perspective_contributions
from .outcomes import store_evaluation
from .policies import ELIGIBILITY_POLICY, EVALUATOR_POLICY, WEIGHT_POLICY
from .policy_repository import propose_candidate
from .predictions import build_prediction
from .repository import MeasurementRepository

SYMBOLS = ("005930", "000660", "005380", "035420", "051910", "006400")


@final
class Scenario:
    def __init__(
        self,
        temporary: TemporaryDirectory[str],
        repository: MeasurementRepository,
        fixture: MeasurementFixture,
    ) -> None:
        self.temporary = temporary
        self.repository = repository
        self.fixture = fixture

    @classmethod
    def open(cls) -> Scenario:
        temporary = TemporaryDirectory()
        path = Path(temporary.name) / "measurement.sqlite3"
        repository = MeasurementRepository.open(path, migrate=True)
        return cls(temporary, repository, load_fixture())

    def __enter__(self) -> Scenario:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.repository.close()
        self.temporary.cleanup()


def prediction(
    index: int,
    *,
    market: Market = Market.KR,
    horizon: int = 1,
    action: Action = Action.BUY,
    recommendation_id: str | None = None,
    perspective_scores_as_of: str = "2026-01-02T06:30:00Z",
    recorded_as_of: str = "2026-01-02T06:30:00Z",
) -> PredictionRecord:
    fixture = load_fixture()
    symbol = SYMBOLS[index] if market is Market.KR else "AAPL"
    namespace = Namespace(
        market=market,
        currency=Currency.KRW if market is Market.KR else Currency.USD,
        account_id="fixture-paper",
        arm_id="fixture-arm",
        symbol=symbol,
    )
    scores = {
        perspective: f"0.{max(100000, 900000 - position * 150000):06d}"
        for position, perspective in enumerate(PERSPECTIVE_IDS)
    }
    input_value = PredictionInput(
        schema_version="v18.normalized-recommendation.1",
        recommendation_id=recommendation_id or f"fixture-{market.value}-{index}",
        namespace=namespace,
        lineage=Lineage(
            runtime_identity="v18.runtime.fixture.1",
            config_version="v18.config.fixture.1",
            source_policy_version=WEIGHT_POLICY.base_version,
            calendar_version=fixture.calendar_version,
            calendar_hash=fixture.calendar_hash,
            price_adjustment_version=fixture.price_adjustment_version,
        ),
        prediction_session="2026-01-02",
        horizon_sessions=horizon,
        action=action,
        reference_price_minor=10_000,
        perspective_scores=scores,
        perspective_scores_as_of=perspective_scores_as_of,
        recorded_as_of=recorded_as_of,
    )
    return build_prediction(input_value)


def evaluated_predictions(
    scenario: Scenario, count: int = 5
) -> tuple[PredictionRecord, ...]:
    result: list[PredictionRecord] = []
    for index in range(count):
        record = prediction(index)
        _ = scenario.repository.register_prediction(record)
        _ = store_evaluation(
            scenario.repository, record.prediction_id, scenario.fixture.sessions,
            scenario.fixture.prices, "2026-01-05T06:30:00Z", EVALUATOR_POLICY,
        )
        result.append(record)
    return tuple(result)


def cohort_specification(
    records: tuple[PredictionRecord, ...],
    *,
    cutoff: str = "2026-01-05T06:30:00Z",
) -> CohortSpecification:
    return CohortSpecification(
        namespace=MeasurementNamespace(
            market=Market.KR,
            currency=Currency.KRW,
            account_id="fixture-paper",
            arm_id="fixture-arm",
        ),
        horizon_sessions=1,
        source_policy_version=WEIGHT_POLICY.base_version,
        evaluator_policy_version=EVALUATOR_POLICY.version,
        calendar_version=load_fixture().calendar_version,
        price_adjustment_version=load_fixture().price_adjustment_version,
        eligibility_policy_version=ELIGIBILITY_POLICY.version,
        cutoff_as_of=cutoff,
        prediction_ids=tuple(record.prediction_id for record in records),
    )


def prepared_manifest(scenario: Scenario) -> CohortManifest:
    records = evaluated_predictions(scenario)
    manifest = build_manifest(
        scenario.repository, cohort_specification(records), ELIGIBILITY_POLICY
    )
    _ = freeze_cohort(scenario.repository, manifest)
    return manifest


def prepared_candidate(scenario: Scenario) -> PolicyCandidate:
    candidate = candidate_value(scenario)
    return propose_candidate(scenario.repository, candidate)


def candidate_value(scenario: Scenario) -> PolicyCandidate:
    manifest = prepared_manifest(scenario)
    contributions = perspective_contributions(
        scenario.repository, manifest, WEIGHT_POLICY
    )
    return build_candidate(
        manifest, manifest.specification.namespace, contributions,
        tuple(item for item in scenario.fixture.sessions if item.market is Market.KR),
        "2026-01-05T07:00:00Z", WEIGHT_POLICY,
    )


def expect_code[T](operation: Callable[[], T], code: str) -> None:
    try:
        _ = operation()
    except V18Error as error:
        if error.code == code:
            return
        raise V18Error("ACCEPTANCE_CODE_MISMATCH", f"{code}/{error.code}") from error
    raise V18Error("ACCEPTANCE_MUTATION_SURVIVED", code)


def row_count(repository: MeasurementRepository, table: str) -> int:
    match repository.connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone():  # noqa: MATCH_OK - SQLite boundary.
        case (int(value),):
            return value
        case _:
            raise V18Error("DATABASE_ROW_INVALID", table)
