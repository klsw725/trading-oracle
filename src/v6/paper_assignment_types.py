from typing import Annotated, Literal

from pydantic import Field

from .models import BoundaryModel
from .offline_models import ContentHash


class AssignmentInput(BoundaryModel):
    production_decision_id: str
    emitted_at: str
    ticker: str
    market: Literal["KR", "US"]
    production_action: Literal["BUY", "SELL", "HOLD", "N/A"]


class AssignmentResult(BoundaryModel):
    assignment_hash: ContentHash
    assignment_bucket: Annotated[int, Field(strict=True, ge=0, lt=10_000)]
    assigned_to_paper: bool
