from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from .cohort_models import MarketDescriptor
from .contract import StrictModel
from .manifest_models import PlanInputs
from .selection_models import SelectionInputs


FIXTURE_PATH = Path(__file__).parents[2] / "docs" / "specs" / "v14" / \
    "fixtures" / "prd01-input.json"


class Prd01Fixture(StrictModel):
    schema_version: Literal["v14.prd01.input.1"]
    cohorts: Annotated[tuple[MarketDescriptor, ...], Field(strict=False)]
    selection: SelectionInputs
    plan: PlanInputs


def load_fixture() -> Prd01Fixture:
    return Prd01Fixture.model_validate_json(FIXTURE_PATH.read_bytes())
