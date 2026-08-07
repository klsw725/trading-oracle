from typing import Literal

from src.v6.models import BoundaryModel

from .models import HashText
from .source_models import SourcePolicyError


class TransitionCheckpoint(BoundaryModel):
    schema_version: Literal["v7.source-policy.checkpoint.1"]
    operation_id: str
    expected_prior_policy_hash: HashText
    intended_policy_hash: HashText
    safe_policy_hash: HashText
    interrupted: bool
    observed_traffic_share: str


def verify_checkpoint(checkpoint: TransitionCheckpoint) -> None:
    if checkpoint.interrupted and checkpoint.observed_traffic_share not in ("0.00", "0"):
        raise SourcePolicyError("INTERRUPTED_TRANSITION_UNSAFE", checkpoint.operation_id)
