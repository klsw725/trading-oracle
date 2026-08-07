from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal, override

from pydantic import AwareDatetime, Field

from src.v6.models import BoundaryModel

from .models import HashText, PersistedProvenanceBundle
from .quality_models import QualityArtifact

type Action = Literal["BUY", "SELL", "HOLD"]
type Market = Literal["KR", "US"]
type Arm = Literal["off", "on", "masked"]
type FactAuditClass = Literal[
    "known_error_corrected",
    "known_error_uncorrected",
    "unsupported_correction",
    "new_false_fact",
    "clean",
]
type ValueCode = Literal[
    "PASS_INCREMENTAL_VALUE_EVALUATION",
    "REJECT_NO_INCREMENTAL_VALUE",
    "REJECT_HARMFUL_SOURCE",
    "REJECT_LATENCY_ONLY",
    "REJECT_MALFORMED_EVALUATION_INPUT",
    "INCONCLUSIVE_INSUFFICIENT_SAMPLE",
    "INCONCLUSIVE_FLAKY_RESULT",
    "INCONCLUSIVE_MISSING_OUTCOME_ADAPTER",
]
type ValueErrorCode = Literal[
    "MALFORMED_EVALUATION_INPUT",
    "REQUIRED_FIELD_MISSING",
    "TRUSTED_VALUE_CONTEXT_REQUIRED",
    "COHORT_MANIFEST_INVALID",
    "OUTCOME_ADAPTER_INVALID",
    "POLICY_MISMATCH",
    "PRD01_LINEAGE_INVALID",
    "PRD02_LINEAGE_INVALID",
    "SOURCE_LINEAGE_MISMATCH",
    "INVENTORY_MISMATCH",
    "DUPLICATE_SAMPLE_ID",
    "MISSING_SAMPLE_ID",
    "COHORT_MISMATCH",
    "CUTOFF_MISMATCH",
    "IDENTITY_MISMATCH",
    "MISSING_ON_COVERAGE",
    "FUTURE_FEATURE_LEAKAGE",
    "FUTURE_OUTCOME_LEAKAGE",
    "FETCH_BUDGET_EXCEEDED",
    "OBSERVATION_HASH_MISMATCH",
    "OUTCOME_HASH_MISMATCH",
    "REPEAT_HASH_MISMATCH",
    "AGGREGATE_METRIC_MISMATCH",
    "SECRET_LEAKAGE_DETECTED",
    "ARTIFACT_HASH_MISMATCH",
    "OUTPUT_PATH_UNSAFE",
]


@dataclass(frozen=True, slots=True)
class ValueContractError(ValueError):
    code: ValueErrorCode
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class ValueThresholds(BoundaryModel):
    success_threshold_5: Decimal
    verdict_lift_lower_90_min: Decimal
    correction_precision_min: Decimal
    correction_recall_min: Decimal
    unsupported_correction_rate_max: Decimal
    new_false_fact_rate_max: Decimal
    factual_recovery_rate_min: Decimal
    verdict_flip_precision_min: Decimal
    coverage_rate_min: Decimal
    target_coverage_rate_min: Decimal
    p95_added_wall_ms_max: int
    mean_added_wall_ms_max: int
    added_prompt_tokens_per_ticker_max: int
    added_fetches_per_ticker_max: Literal[1]
    timeout_rate_max: Decimal
    harm_rate_max: Decimal
    severe_harm_rate_max: Decimal


def canonical_thresholds() -> ValueThresholds:
    return ValueThresholds(
        success_threshold_5=Decimal("0.01"), verdict_lift_lower_90_min=Decimal("0.003"),
        correction_precision_min=Decimal("0.80"), correction_recall_min=Decimal("0.25"),
        unsupported_correction_rate_max=Decimal("0.05"), new_false_fact_rate_max=Decimal("0.03"),
        factual_recovery_rate_min=Decimal("0.10"), verdict_flip_precision_min=Decimal("0.60"),
        coverage_rate_min=Decimal("0.75"), target_coverage_rate_min=Decimal("0.80"),
        p95_added_wall_ms_max=2500, mean_added_wall_ms_max=900,
        added_prompt_tokens_per_ticker_max=1500, added_fetches_per_ticker_max=1,
        timeout_rate_max=Decimal("0.02"), harm_rate_max=Decimal("0.20"),
        severe_harm_rate_max=Decimal("0.05"),
    )


class CohortSample(BoundaryModel):
    sample_id: Annotated[str, Field(pattern=r"^ive_sample_[0-9]{4}$")]
    market: Market
    ticker: Annotated[str, Field(min_length=1)]
    action: Action
    target_error: bool
    fact_audit_class: FactAuditClass
    fact_audit_hash: HashText
    off_output_hash: HashText
    on_output_hash: HashText
    masked_output_hash: HashText
    outcome_hash: HashText


class CohortManifestBody(BoundaryModel):
    schema_version: Literal["v7.incremental_value_evaluation.cohort-manifest.1"]
    prompt_bundle: Annotated[str, Field(min_length=1)]
    scorer_version: Annotated[str, Field(min_length=1)]
    portfolio_hash: HashText
    horizon: Literal[5]
    quality_contract: Literal["v7.quality_freshness_dedup.prd02.2"]
    decision_cutoff: AwareDatetime
    outcome_cutoff: AwareDatetime
    samples: Annotated[tuple[CohortSample, ...], Field(min_length=360, max_length=360)]


class CohortManifest(CohortManifestBody):
    manifest_root: HashText


class SourceBinding(BoundaryModel):
    adapter_id: Annotated[str, Field(min_length=1)]
    provenance_bundle: PersistedProvenanceBundle
    quality_artifact: QualityArtifact
