from __future__ import annotations

from pathlib import Path

from .verdict_models import Prd03Fixture


FIXTURE_PATH = Path(__file__).parents[2] / "docs" / "specs" / "v14" / \
    "fixtures" / "prd03-verdict-scenarios.json"


def load_prd03_fixture() -> Prd03Fixture:
    return Prd03Fixture.model_validate_json(FIXTURE_PATH.read_bytes())
