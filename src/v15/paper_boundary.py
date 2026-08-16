from __future__ import annotations

from pathlib import Path

from src.v11.models import V11ContractError
from src.v11.paper_boundary import verify_output_path, verify_paper_input
from src.v4.models import JsonValue

from .contract import V15Failure, V15FailureCode


def verify_paper_boundary(value: JsonValue, output_path: Path | None = None) -> None:
    try:
        verify_paper_input(value)
        if not isinstance(value, dict) or value.get("destination") != "paper":
            raise V15Failure(V15FailureCode.PAPER_BOUNDARY, "destination")
        if output_path is not None:
            verify_output_path(output_path)
    except V11ContractError as error:
        raise V15Failure(V15FailureCode.PAPER_BOUNDARY, error.detail) from error
