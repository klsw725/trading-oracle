from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .cohort import expand_descriptor, freeze_cohort
from .cohort_models import FrozenCohort
from .contract import StrictModel
from .fixture import Prd01Fixture
from .folds import AnchoredFold, anchored_folds
from .manifest_models import ExperimentPlanManifest
from .manifest_plan import build_experiment_plan
from .selection import build_development_selection
from .selection_models import DevelopmentSelection


class Prd01Artifacts(StrictModel):
    cohort: FrozenCohort
    folds: Annotated[tuple[AnchoredFold, ...], Field(strict=False)]
    selection: DevelopmentSelection
    plan: ExperimentPlanManifest


def build_prd01(fixture: Prd01Fixture) -> Prd01Artifacts:
    rows = tuple(
        row for descriptor in fixture.cohorts for row in expand_descriptor(descriptor)
    )
    cohort = freeze_cohort(rows)
    folds = tuple(
        fold for market in cohort.markets for fold in anchored_folds(market)
    )
    selection = build_development_selection(cohort.cohort_hash, fixture.selection)
    plan = build_experiment_plan(fixture.plan, cohort, selection)
    return Prd01Artifacts(cohort=cohort, folds=folds,
        selection=selection, plan=plan)
