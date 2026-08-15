from __future__ import annotations

from pathlib import Path
from typing import Final

from .prd04_models import HoldoutHistory
from .prd04_source_models import Prd04Source


FIXTURE_PATH: Final = Path(__file__).parents[2] / "docs/specs/v14/fixtures/prd04-source.json"
HISTORY_PATH: Final = Path(__file__).parents[2] / "docs/specs/v14/fixtures/prd04-history.json"


def load_prd04_fixture(path: Path = FIXTURE_PATH) -> Prd04Source:
    return Prd04Source.model_validate_json(path.read_bytes())


def load_prd04_history(path: Path = HISTORY_PATH) -> HoldoutHistory:
    return HoldoutHistory.model_validate_json(path.read_bytes())
