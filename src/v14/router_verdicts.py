from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from .contract import V14ContractError
from .router_metric_models import RouterComparisonArtifact
from .series_models import DailySeriesArtifact, ResearchSegment
from .verdict_models import (
    HoldoutVerdict,
    HoldoutVerdictArtifact,
    ValidationVerdict,
    ValidationVerdictArtifact,
)
from .verdicts import evidence_from_metrics, holdout_verdict, validation_verdict


type RawRouterVerdict = ValidationVerdictArtifact | HoldoutVerdictArtifact


@dataclass(frozen=True, slots=True)
class RouterRawVerdicts:
    mixed: RawRouterVerdict
    paired: RawRouterVerdict


def _integrity(series: DailySeriesArtifact) -> bool:
    return all(item.integrity_valid for item in series.points)


def build_router_raw_verdicts(
    comparison: RouterComparisonArtifact,
) -> RouterRawVerdicts:
    mixed = evidence_from_metrics(
        comparison.mixed_metrics, _integrity(comparison.mixed_series))
    paired = evidence_from_metrics(
        comparison.paired_metrics, _integrity(comparison.paired_series))
    match comparison.segment:  # noqa: MATCH_OK - enum cases end in assert_never
        case ResearchSegment.VALIDATION:
            return RouterRawVerdicts(
                mixed=validation_verdict(mixed), paired=validation_verdict(paired))
        case ResearchSegment.HOLDOUT:
            return RouterRawVerdicts(mixed=holdout_verdict(mixed, True),
                paired=holdout_verdict(paired, True))
    assert_never(comparison.segment)


def validation_router_verdict(
    raw: RouterRawVerdicts, hierarchy_passed: bool
) -> ValidationVerdict:
    if not isinstance(raw.mixed, ValidationVerdictArtifact) \
            or not isinstance(raw.paired, ValidationVerdictArtifact):
        raise V14ContractError("V14_ROUTER_VERDICT_TYPE", "validation")
    match raw.mixed.verdict, raw.paired.verdict:  # noqa: MATCH_OK - all pairs covered
        case ValidationVerdict.REJECT, _:
            return ValidationVerdict.REJECT
        case _, ValidationVerdict.REJECT:
            return ValidationVerdict.REJECT
        case ValidationVerdict.INCONCLUSIVE, _:
            return ValidationVerdict.INCONCLUSIVE
        case _, ValidationVerdict.INCONCLUSIVE:
            return ValidationVerdict.INCONCLUSIVE
        case ValidationVerdict.PASS, ValidationVerdict.PASS:
            return ValidationVerdict.PASS if hierarchy_passed \
                else ValidationVerdict.REJECT
    assert_never(raw.mixed.verdict)


def holdout_router_verdict(
    raw: RouterRawVerdicts, hierarchy_passed: bool
) -> HoldoutVerdict:
    if not isinstance(raw.mixed, HoldoutVerdictArtifact) \
            or not isinstance(raw.paired, HoldoutVerdictArtifact):
        raise V14ContractError("V14_ROUTER_VERDICT_TYPE", "holdout")
    priority = {HoldoutVerdict.INVALID_EXPERIMENT: 0,
        HoldoutVerdict.INSUFFICIENT_SAMPLE: 1, HoldoutVerdict.NO_EDGE: 2,
        HoldoutVerdict.COST_FRAGILE: 3, HoldoutVerdict.INCONCLUSIVE: 4,
        HoldoutVerdict.MULTIPLE_TESTING: 5, HoldoutVerdict.PASS: 6}
    raw_verdict = min((raw.mixed.verdict, raw.paired.verdict),
        key=priority.__getitem__)
    match raw_verdict:  # noqa: MATCH_OK - enum cases end in assert_never
        case HoldoutVerdict.PASS:
            return HoldoutVerdict.PASS if hierarchy_passed \
                else HoldoutVerdict.MULTIPLE_TESTING
        case (HoldoutVerdict.INVALID_EXPERIMENT
                | HoldoutVerdict.INSUFFICIENT_SAMPLE
                | HoldoutVerdict.NO_EDGE
                | HoldoutVerdict.COST_FRAGILE
                | HoldoutVerdict.INCONCLUSIVE
                | HoldoutVerdict.MULTIPLE_TESTING):
            return raw_verdict
    assert_never(raw_verdict)
