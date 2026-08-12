from __future__ import annotations

from pathlib import Path

from src.v4.models import JsonValue

from .canonical import reject_forbidden
from .models import V11ContractError


def verify_paper_input(value: JsonValue) -> None:
    reject_forbidden(value)
    if isinstance(value, dict) and value.get("destination") not in {None, "paper"}:
        raise V11ContractError("V11_PAPER_BOUNDARY", "destination")


def verify_output_path(path: Path) -> None:
    if "data/portfolio.json" in path.as_posix():
        raise V11ContractError("V11_PAPER_BOUNDARY", path.as_posix())
