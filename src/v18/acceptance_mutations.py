from collections.abc import Callable
from typing import Final

from .acceptance_models import ProbeResult, passed
from .boundaries import BoundaryCounts
from .errors import V18Error
from .mutation_candidate import CANDIDATE_MUTATIONS
from .mutation_evaluation import EVALUATION_MUTATIONS
from .mutation_prediction import PREDICTION_MUTATIONS

type Mutation = Callable[[], ProbeResult]

MUTATION_IDS: Final = (
    "active_weight_overwrite",
    "calendar_version_drift",
    "candidate_bound_escape",
    "candidate_effective_past",
    "cross_market_price",
    "duplicate_cohort_member",
    "duplicate_target_price",
    "early_close_horizon",
    "evaluation_payload_conflict",
    "immature_as_of",
    "immature_cohort_member",
    "later_version_import",
    "leakage_future_input",
    "legacy_missing_identity",
    "missing_target_price",
    "network_attempt",
    "portfolio_mutation",
    "prediction_duplicate_retry",
    "prediction_identity_conflict",
    "quarantine_promotion",
    "raw_price_substitution",
    "rollback_deletes_history",
    "weekend_horizon",
)


def run_mutations(boundaries: BoundaryCounts) -> tuple[ProbeResult, ...]:
    functions: tuple[Mutation, ...] = (
        *PREDICTION_MUTATIONS,
        *EVALUATION_MUTATIONS,
        *CANDIDATE_MUTATIONS,
    )
    results = [function() for function in functions]
    if boundaries.network != 0:
        raise V18Error("BOUNDARY_NETWORK_ATTEMPT", str(boundaries.network))
    if boundaries.later_import != 0:
        raise V18Error("BOUNDARY_LATER_IMPORT", str(boundaries.later_import))
    results.extend(
        (
            passed("network_attempt", "call 0"),
            passed("later_version_import", "import 0"),
        )
    )
    ordered = tuple(sorted(results, key=lambda item: item.id))
    if tuple(item.id for item in ordered) != MUTATION_IDS:
        raise V18Error("MUTATION_INVENTORY_MISMATCH", str(tuple(item.id for item in ordered)))
    return ordered
