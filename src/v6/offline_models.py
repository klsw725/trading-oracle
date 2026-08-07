from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import Field

from .models import BoundaryModel, CandidateId, CandidateVersion, ExistingPerspective, HypothesisId


Decimal6 = Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$")]
Probability6 = Annotated[str, Field(pattern=r"^(?:0\.[0-9]{6}|1\.000000)$")]
ContentHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


@unique
class BaselineKind(StrEnum):
    CONSENSUS = "existing_consensus"
    CLOSEST = "closest_existing_perspective"
    EQUAL_WEIGHT = "equal_weight_existing_five"


@unique
class OfflineCode(StrEnum):
    PASS = "PASS_OFFLINE_EVALUATION"
    CLONE = "REJECT_HIGH_CORRELATION_CLONE"
    QUANT_CLONE = "REJECT_QUANT_REWEIGHT_CLONE"
    NO_LIFT = "REJECT_NO_INCREMENTAL_LIFT"
    HARMFUL = "REJECT_HARMFUL_CANDIDATE"
    MALFORMED = "REJECT_MALFORMED_EVALUATION_INPUT"
    INSUFFICIENT = "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    FLAKY = "INCONCLUSIVE_FLAKY_RESULT"
    MISSING_ADAPTER = "INCONCLUSIVE_MISSING_OUTCOME_ADAPTER"


@unique
class MutationName(StrEnum):
    STALE = "stale_dataset"
    DIRTY = "dirty_manifest"
    LEAKAGE = "leakage_feature"
    MISLEADING = "misleading_report"
    NA_TIMEOUT = "na_timeout_disguised"
    CLONE = "high_correlation_clone"
    HARM = "harmful_candidate"
    NO_LIFT = "no_incremental_lift"
    INSUFFICIENT = "insufficient_sample"
    MISSING_ADAPTER = "missing_outcome_adapter"
    FLAKY = "flaky_threshold"
    ABLATION = "ablation_no_drop"
    MALFORMED_PRECEDENCE = "malformed_precedes_clone"
    CLONE_PRECEDENCE = "clone_precedes_harm"
    HARM_PRECEDENCE = "harm_precedes_no_lift"
    LIFT_PRECEDENCE = "no_lift_precedes_insufficient"
    ALL_TRAIN = "all_train_window"
    OVER_BUDGET = "over_budget_resource"
    ZERO_REPEATS = "zero_threshold_repeats"
    MISSING_OUTCOMES = "missing_all_outcomes"
    MISSING_TARGET = "missing_target_error_cohort"


class BaselineMetric(BoundaryModel):
    kind: BaselineKind
    mean_edge: Decimal6
    incremental_lift: Decimal6


class PerspectiveCorrelation(BoundaryModel):
    perspective: ExistingPerspective
    error_correlation: Decimal6
    verdict_correlation: Decimal6
    shared_samples: int


class OfflineSummary(BoundaryModel):
    schema_version: Literal["v6.offline-evaluation-summary.2"]
    candidate_id: CandidateId
    candidate_version: CandidateVersion
    hypothesis_id: HypothesisId
    input_hash: ContentHash
    manifest_hash: ContentHash
    dataset_manifest_id: str
    baselines: tuple[BaselineMetric, ...]
    holdout_eligible_samples: int
    target_error_samples: int
    kr_samples: int
    us_samples: int
    buy_samples: int
    sell_samples: int
    hold_samples: int
    minimum_pair_correlation_samples: int
    minimum_calibration_bucket_samples: int
    holdout_incremental_lift_5: Decimal6
    holdout_lift_bootstrap_lower_90: Decimal6
    target_error_lift_5: Decimal6
    target_error_lift_bootstrap_lower_90: Decimal6
    harm_rate: Probability6
    non_target_harm_rate: Probability6
    baseline_miss_recovery_rate: Probability6
    correlations: tuple[PerspectiveCorrelation, ...]
    max_error_correlation: Decimal6
    max_verdict_correlation: Decimal6
    candidate_brier: Probability6
    baseline_brier: Probability6
    candidate_ece: Probability6
    baseline_ece: Probability6
    overconfident_error_bucket_count: int
    overall_na_rate: Probability6
    target_error_na_rate: Probability6
    missing_required_input_as_hold_count: int
    timeout_as_verdict_count: int
    p95_wall_ms_per_ticker: int
    mean_wall_ms_per_ticker: int
    llm_calls_per_ticker: int
    prompt_tokens_per_ticker: int
    extra_fetches_per_ticker: int
    timeout_rate: Probability6
    ablation_remove_novel_observations_lift_drop: Decimal6
    existing_signal_only_overlap: Probability6
    shuffle_candidate_outputs_lift: Decimal6
    outcome_adapter_available: bool


class HandExpected(BoundaryModel):
    mean_baseline_edge: Decimal6
    mean_candidate_edge: Decimal6
    incremental_lift: Decimal6
    candidate_hits: int
    candidate_errors: int
    brier: Decimal6
    ece: Decimal6


class ExpectedMutation(BoundaryModel):
    name: MutationName
    code: OfflineCode
