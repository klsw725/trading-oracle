from dataclasses import dataclass
from typing import Final

from .errors import V18Error
from .models import Lineage

@dataclass(frozen=True, slots=True)
class EvaluatorPolicy:
    version: str
    neutral_band_bps: int


@dataclass(frozen=True, slots=True)
class EligibilityPolicy:
    version: str
    minimum_samples: int
    per_symbol_cap: int


@dataclass(frozen=True, slots=True)
class WeightPolicy:
    base_version: str
    objective_version: str
    perspectives: tuple[str, ...]
    base_weight_millionths: int
    minimum_weight_millionths: int
    maximum_weight_millionths: int
    quantum_millionths: int
    maximum_per_weight_delta_millionths: int
    maximum_l1_delta_millionths: int


EVALUATOR_POLICY: Final = EvaluatorPolicy("v18.evaluator-policy.fixture.1", 25)
ELIGIBILITY_POLICY: Final = EligibilityPolicy("v18.eligibility-policy.fixture.1", 5, 2)
WEIGHT_POLICY: Final = WeightPolicy(
    "v18.base-policy.fixture.1",
    "v18.perspective-objective.1",
    ("kwangsoo", "ouroboros", "quant", "macro", "value"),
    200_000,
    100_000,
    300_000,
    10_000,
    50_000,
    100_000,
)

RUNTIME_IDENTITY: Final = "v18.runtime.fixture.1"
CONFIG_VERSION: Final = "v18.config.fixture.1"
CALENDAR_VERSION: Final = "v18.calendar.fixture.1"
CALENDAR_HASH: Final = "sha256:013da18c9e3878b90285fca7ed91bce07930b757141c881fdf4fa29fe25f3dcd"
PRICE_ADJUSTMENT_VERSION: Final = "v18.adjustment.fixture.1"


def validate_lineage(lineage: Lineage) -> None:
    observed = (
        lineage.runtime_identity,
        lineage.config_version,
        lineage.source_policy_version,
        lineage.calendar_version,
        lineage.calendar_hash,
        lineage.price_adjustment_version,
    )
    expected = (
        RUNTIME_IDENTITY,
        CONFIG_VERSION,
        WEIGHT_POLICY.base_version,
        CALENDAR_VERSION,
        CALENDAR_HASH,
        PRICE_ADJUSTMENT_VERSION,
    )
    if observed != expected:
        raise V18Error("PREDICTION_LINEAGE_UNKNOWN", str(observed))
