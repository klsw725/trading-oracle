from __future__ import annotations

from pathlib import Path
from typing import Final

from src.v4.models import JsonValue
from src.v9.contract import V9ContractError
from src.v9.spec import parse_json_bytes


FIXTURE_PATH: Final = Path(
    "docs/specs/v9/fixtures/v9-dashboard-read-contract.json"
)


def load_fixture(path: Path = FIXTURE_PATH) -> JsonValue:
    try:
        return parse_json_bytes(path.read_bytes())
    except OSError as error:
        raise V9ContractError("malformed_fixture", str(error)) from error
