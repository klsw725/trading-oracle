from __future__ import annotations

from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field

from .contract import StrictModel
from .hypothesis_models import PValueInput
from .selection_models import JsonDecimal


@unique
class ValidationVerdict(StrEnum):
    PASS = "VALIDATION_PASS"
    REJECT = "VALIDATION_REJECT"
    INCONCLUSIVE = "VALIDATION_INCONCLUSIVE"


@unique
class HoldoutVerdict(StrEnum):
    PASS = "PASS"
    NO_EDGE = "REJECT_NO_EDGE"
    COST_FRAGILE = "REJECT_COST_FRAGILE"
    MULTIPLE_TESTING = "REJECT_MULTIPLE_TESTING"
    INCONCLUSIVE = "INCONCLUSIVE"
    INSUFFICIENT_SAMPLE = "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    INVALID_EXPERIMENT = "INVALID_EXPERIMENT"


class MetricScenario(StrictModel):
    scenario_id: str
    hypothesis_id: str
    integrity_valid: bool
    signal_days: int = Field(ge=0)
    completed_trades: int = Field(ge=0)
    ci_lower: JsonDecimal
    ci_upper: JsonDecimal
    baseline_return: JsonDecimal
    stress_return: JsonDecimal
    secondary_sharpe: JsonDecimal
    bootstrap_non_positive_count: int = Field(ge=0, le=10000)


class VerdictEvidenceBody(StrictModel):
    hypothesis_id: str
    integrity_valid: bool
    signal_days: int
    completed_trades: int
    ci_lower: JsonDecimal
    ci_upper: JsonDecimal
    baseline_return: JsonDecimal
    stress_return: JsonDecimal
    one_sided_p_value: JsonDecimal


class VerdictEvidence(VerdictEvidenceBody):
    evidence_hash: str


class ValidationVerdictBody(StrictModel):
    schema_version: Literal["v14.validation_verdict.1"]
    evidence_hash: str
    verdict: Annotated[ValidationVerdict, Field(strict=False)]


class ValidationVerdictArtifact(ValidationVerdictBody):
    verdict_hash: str


class HoldoutVerdictBody(StrictModel):
    schema_version: Literal["v14.holdout_verdict.1"]
    evidence_hash: str
    correction_passed: bool
    verdict: Annotated[HoldoutVerdict, Field(strict=False)]


class HoldoutVerdictArtifact(HoldoutVerdictBody):
    verdict_hash: str


class ExploratoryInput(StrictModel):
    hypothesis_id: str
    p_value: JsonDecimal


class RouterScenario(StrictModel):
    orb_passed: bool
    enabled_ids: Annotated[tuple[str, ...], Field(strict=False)]
    constituent_passes: Annotated[tuple[bool, ...], Field(strict=False)]
    router_metric_passed: bool
    paired_p_value: JsonDecimal


class Prd03Fixture(StrictModel):
    schema_version: Literal["v14.prd03.input.1"]
    holdout_scenarios: Annotated[tuple[MetricScenario, ...], Field(strict=False)]
    validation_scenarios: Annotated[tuple[MetricScenario, ...], Field(strict=False)]
    holm_inputs: Annotated[tuple[PValueInput, ...], Field(strict=False)]
    exploratory_inputs: Annotated[tuple[ExploratoryInput, ...], Field(strict=False)]
    router_pass: RouterScenario
    router_blocked: RouterScenario
