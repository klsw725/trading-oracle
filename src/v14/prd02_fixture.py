from __future__ import annotations

from pathlib import Path

from .series_models import CostFixture


FIXTURE_PATH = Path(__file__).parents[2] / "docs" / "specs" / "v14" / \
    "fixtures" / "prd02-run-input.json"


def load_prd02_fixture() -> CostFixture:
    return CostFixture.model_validate_json(FIXTURE_PATH.read_bytes())
