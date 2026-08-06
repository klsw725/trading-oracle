from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, NewType, override

from src.v4.models import Action, Market, MeasurementState, OrderId, PortfolioTradeId

SampleId = NewType("SampleId", str)
FillId = NewType("FillId", str)
CalibrationContractVersion = NewType("CalibrationContractVersion", str)
SnapshotSchemaVersion = NewType("SnapshotSchemaVersion", str)
AttributionSchemaVersion = NewType("AttributionSchemaVersion", str)
Exchange = NewType("Exchange", str)
PromptBundleVersion = NewType("PromptBundleVersion", str)
ScorerVersion = NewType("ScorerVersion", str)
WeightsVersion = NewType("WeightsVersion", str)
Regime = NewType("Regime", str)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
DEFAULT_BUCKET_EDGES: Final = tuple(
    Decimal(value) for value in ("0", "0.2", "0.4", "0.6", "0.8", "1")
)
type ExclusionReason = Literal[
    "legacy_audit_only",
    "outcome_pending",
    "insufficient_data",
    "insufficient_context",
    "action_not_calibrated",
]
type CalibrationState = Literal[
    "ready", "insufficient_sample_no_op", "inconclusive"
]


@dataclass(frozen=True, slots=True)
class CalibrationCohortKey:
    calibration_contract_version: CalibrationContractVersion
    snapshot_schema_version: SnapshotSchemaVersion
    attribution_schema_version: AttributionSchemaVersion
    market: Market
    exchange: Exchange
    action: Action
    horizon: int
    prompt_bundle_version: PromptBundleVersion
    scorer_version: ScorerVersion
    weights_version: WeightsVersion
    decision_regime: Regime
    analysis_regime: Regime


@dataclass(frozen=True, slots=True)
class TradeLinkage:
    portfolio_trade_id: PortfolioTradeId | None = None
    order_ids: tuple[OrderId, ...] = ()
    fill_ids: tuple[FillId, ...] = ()

    @property
    def is_empty(self) -> bool:
        return (
            self.portfolio_trade_id is None
            and not self.order_ids
            and not self.fill_ids
        )


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    sample_id: SampleId
    cohort: CalibrationCohortKey
    confidence_probability: Decimal | None
    measurement_state: MeasurementState
    instrument_return: Decimal | None
    benchmark_return: Decimal | None
    native_v4: bool = True
    held_position_sell_eligible: bool = False
    sample_weight: Decimal = ONE
    trade_linkage: TradeLinkage = TradeLinkage()


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    buy_success_threshold: Decimal = Decimal("0.01")
    sell_success_threshold: Decimal = Decimal("0.01")
    bucket_edges: tuple[Decimal, ...] = DEFAULT_BUCKET_EDGES
    minimum_total_samples: int = 100
    minimum_bucket_samples: int = 20


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    sample_id: SampleId
    cohort: CalibrationCohortKey
    confidence_probability: Decimal
    correctness_label: str
    correctness_outcome: int
    sample_weight: Decimal
    buy_edge: Decimal
    sell_edge: Decimal
    held_position_sell_eligible: bool = False
    hold_opportunity_cost: Decimal | None = None
    hold_avoided_loss: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ExcludedCalibrationSample:
    sample_id: SampleId
    action: Action
    reason: ExclusionReason


type SampleBuildResult = CalibrationSample | ExcludedCalibrationSample


@dataclass(frozen=True, slots=True)
class ActionDenominator:
    action: Action
    count: int


@dataclass(frozen=True, slots=True)
class SampleConstructionReport:
    denominators: tuple[ActionDenominator, ...]
    samples: tuple[CalibrationSample, ...]
    excluded: tuple[ExcludedCalibrationSample, ...]


@dataclass(frozen=True, slots=True)
class CalibrationCohortSamples:
    cohort: CalibrationCohortKey
    samples: tuple[CalibrationSample, ...]


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    lower_bound: Decimal
    upper_bound: Decimal
    sample_count: int
    weighted_count: Decimal
    average_confidence: Decimal | None
    empirical_accuracy: Decimal | None
    absolute_gap: Decimal | None
    ece_component: Decimal


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    cohort: CalibrationCohortKey | None
    state: CalibrationState
    sample_count: int
    weighted_count: Decimal
    brier_score: Decimal | None
    ece: Decimal | None
    buckets: tuple[CalibrationBucket, ...]


@dataclass(frozen=True, slots=True)
class NonPolicyAcceptanceArithmetic:
    cohorts: tuple[CalibrationCohortKey, ...]
    sample_count: int
    weighted_count: Decimal
    brier_score: Decimal
    ece: Decimal
    buckets: tuple[CalibrationBucket, ...]
    purpose: Literal["acceptance_fixture_arithmetic_only"] = "acceptance_fixture_arithmetic_only"


@dataclass(frozen=True, slots=True)
class MalformedCalibrationInputError(Exception):
    field: str
    detail: str
    sample_id: SampleId | None = None

    @override
    def __str__(self) -> str:
        location = f" for sample {self.sample_id}" if self.sample_id else ""
        return f"malformed calibration {self.field}{location}: {self.detail}"


@dataclass(frozen=True, slots=True)
class MixedCalibrationCohortError(Exception):
    expected: CalibrationCohortKey
    actual: CalibrationCohortKey
    sample_id: SampleId

    @override
    def __str__(self) -> str:
        return f"sample {self.sample_id} belongs to a different calibration cohort"


@dataclass(frozen=True, slots=True)
class HoldTradeLinkageError(Exception):
    sample_id: SampleId

    @override
    def __str__(self) -> str:
        return f"HOLD sample {self.sample_id} must not have trade linkage"


def validate_calibration_config(config: CalibrationConfig) -> None:
    edges = config.bucket_edges
    if len(edges) < 2 or edges[0] != ZERO or edges[-1] != ONE:
        raise MalformedCalibrationInputError("bucket_edges", "must span 0 to 1")
    if any(not edge.is_finite() for edge in edges) or any(
        left >= right for left, right in zip(edges, edges[1:])
    ):
        raise MalformedCalibrationInputError(
            "bucket_edges", "must be finite and strictly increasing"
        )
    thresholds = (config.buy_success_threshold, config.sell_success_threshold)
    if any(not value.is_finite() or value < ZERO for value in thresholds):
        raise MalformedCalibrationInputError(
            "success_threshold", "must be finite and non-negative"
        )
    if config.minimum_total_samples <= 0 or config.minimum_bucket_samples <= 0:
        raise MalformedCalibrationInputError("minimum_samples", "must be positive")


def validate_calibration_cohort(cohort: CalibrationCohortKey) -> None:
    if cohort.horizon <= 0:
        raise MalformedCalibrationInputError("cohort.horizon", "must be positive")
    identities = (
        cohort.calibration_contract_version,
        cohort.snapshot_schema_version,
        cohort.attribution_schema_version,
        cohort.exchange,
        cohort.prompt_bundle_version,
        cohort.scorer_version,
        cohort.weights_version,
        cohort.decision_regime,
        cohort.analysis_regime,
    )
    if any(not value for value in identities):
        raise MalformedCalibrationInputError(
            "cohort.identity", "version, exchange, and regime fields must be non-empty"
        )


def validate_calibration_sample(
    sample: CalibrationSample, config: CalibrationConfig
) -> None:
    validate_calibration_cohort(sample.cohort)
    if not sample.sample_id:
        raise MalformedCalibrationInputError("sample_id", "must be non-empty")
    if not sample.confidence_probability.is_finite() or not ZERO <= sample.confidence_probability <= ONE:
        raise MalformedCalibrationInputError(
            "confidence_probability", "must be finite and in [0, 1]", sample.sample_id
        )
    if not sample.sample_weight.is_finite() or sample.sample_weight <= ZERO:
        raise MalformedCalibrationInputError(
            "sample_weight", "must be positive and finite", sample.sample_id
        )
    if type(sample.correctness_outcome) is not int or sample.correctness_outcome not in (0, 1):
        raise MalformedCalibrationInputError(
            "correctness_outcome", "must be integer 0 or 1", sample.sample_id
        )
    if not sample.buy_edge.is_finite() or sample.sell_edge != -sample.buy_edge:
        raise MalformedCalibrationInputError(
            "action_edge", "buy and sell edges must be finite opposites", sample.sample_id
        )
    expected_label = f"Y_{sample.cohort.action}_{sample.cohort.horizon}"
    if sample.correctness_label != expected_label:
        raise MalformedCalibrationInputError(
            "correctness_label", f"must equal {expected_label}", sample.sample_id
        )
    match sample.cohort.action:  # noqa: MATCH_OK
        case Action.BUY:
            expected = int(sample.buy_edge >= config.buy_success_threshold)
            hold_values_valid = sample.hold_opportunity_cost is None and sample.hold_avoided_loss is None
        case Action.SELL:
            expected = int(sample.sell_edge >= config.sell_success_threshold)
            hold_values_valid = sample.hold_opportunity_cost is None and sample.hold_avoided_loss is None
        case Action.HOLD:
            buy_cost = max(ZERO, sample.buy_edge - config.buy_success_threshold)
            sell_cost = max(ZERO, sample.sell_edge - config.sell_success_threshold) if sample.held_position_sell_eligible else ZERO
            opportunity_cost = buy_cost + sell_cost
            expected = int(opportunity_cost == ZERO)
            hold_values_valid = sample.hold_opportunity_cost == opportunity_cost and sample.hold_avoided_loss == max(ZERO, sample.sell_edge)
        case Action.BLOCKED | Action.CANDIDATE_REJECTED:
            raise MalformedCalibrationInputError(
                "cohort.action", "action has no calibration target", sample.sample_id
            )
    if sample.correctness_outcome != expected or not hold_values_valid:
        raise MalformedCalibrationInputError(
            "correctness_semantics", "outcome or HOLD fields do not match action edge", sample.sample_id
        )
