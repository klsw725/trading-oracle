from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Literal, Self, override

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from src.v4.models import JsonValue


HashText = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Relation = Literal["increases", "decreases", "causes", "enables", "blocks"]
Transform = Literal[
    "level", "diff_1d", "pct_change_1d", "pct_change_5d", "pct_change_20d",
    "spread", "custom_formula",
]
LinkDirection = Literal["same", "inverse", "component", "not_directional"]
WindowName = Literal["train", "embargo", "holdout"]


@dataclass(frozen=True, slots=True)
class ContractValueError(ValueError):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"{self.field}: {self.reason}"


class BoundaryModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class NodeDirection(BoundaryModel):
    kind: Annotated[str, Field(min_length=1)]
    polarity: Annotated[str, Field(min_length=1)]


class CanonicalNode(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    canonical_node_id: Annotated[str, Field(min_length=1)]
    canonical_label: Annotated[str, Field(min_length=1)]
    normalized_label: Annotated[str, Field(min_length=1)]
    direction: NodeDirection


class CanonicalTriple(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    subject_node_id: Annotated[str, Field(min_length=1)]
    object_node_id: Annotated[str, Field(min_length=1)]
    relation: Relation


class CanonicalArtifact(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    schema_version: Literal["causal-node-canonicalization.1"]
    nodes: tuple[CanonicalNode, ...]
    triples: tuple[CanonicalTriple, ...]


class ManualApproval(BoundaryModel):
    required: Literal[True]
    approved_by: Annotated[str, Field(min_length=1)]
    approved_at: AwareDatetime
    approval_reason: Annotated[str, Field(min_length=1)]
    expires_at: AwareDatetime


class SeriesLink(BoundaryModel):
    series_id: Annotated[str, Field(min_length=1)]
    transform: Transform
    unit: Annotated[str, Field(min_length=1)]
    direction: LinkDirection
    source_id: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    source_expires_at: AwareDatetime
    provenance_hash: HashText
    suitability: Annotated[str, Field(min_length=1)]
    suitability_evidence: Annotated[str, Field(min_length=1)]
    manual_approval: ManualApproval


class MappingEnvelope(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    canonical_node_id: Annotated[str, Field(min_length=1)]


class MappingRecord(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    canonical_node_id: Annotated[str, Field(min_length=1)]
    canonical_label: Annotated[str, Field(min_length=1)]
    mapping_hash: HashText | None = None
    mapping_result: str
    mapping_kind: str
    mapping_expires_at: AwareDatetime | None = None
    formula: str | None = None
    formula_unit: str | None = None
    series_links: tuple[SeriesLink, ...]
    proxy_candidates_rejected: tuple[JsonValue, ...] = ()
    unmappable_reason: str | None = None

    @model_validator(mode="after")
    def approved_shape(self) -> Self:
        if self.mapping_result != "approved_manual":
            return self
        if self.mapping_hash is None or self.mapping_expires_at is None:
            raise ContractValueError("mapping", "approved mapping requires hash and expiry")
        if self.mapping_kind == "single_series" and len(self.series_links) != 1:
            raise ContractValueError("mapping_kind", "single_series requires exactly one link")
        if self.mapping_kind == "composite_series":
            if len(self.series_links) < 2 or self.formula is None or self.formula_unit is None:
                raise ContractValueError("mapping_kind", "composite requires links, formula, and unit")
            try:
                tree = ast.parse(self.formula, mode="eval")
            except SyntaxError as error:
                raise ContractValueError("formula", "invalid composite formula") from error
            allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub, ast.Name, ast.Load)
            if any(not isinstance(node, allowed) for node in ast.walk(tree)):
                raise ContractValueError("formula", "forbidden syntax")
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            if names != {link.series_id for link in self.series_links}:
                raise ContractValueError("formula", "variables differ from links")
        return self


class MappingArtifact(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    schema_version: Literal["causal-series-mapping.1"]
    source_node_schema_version: Literal["causal-node-canonicalization.1"]
    source_node_artifact_hash: HashText
    mappings: tuple[JsonValue, ...]


class Observation(BoundaryModel):
    timestamp: AwareDatetime
    value: StrictFloat | StrictInt


class SeriesFrame(BoundaryModel):
    series_id: Annotated[str, Field(min_length=1)]
    observations: tuple[Observation, ...]


class VerificationConfig(BoundaryModel):
    alpha: Decimal
    stationarity_alpha: Decimal
    split_policy: Literal["chronological_70_10_20"]
    train_fraction: Decimal
    embargo_fraction: Decimal
    holdout_fraction: Decimal
    lag_grid: tuple[Annotated[int, Field(strict=True, ge=1)], ...]
    min_train_rows_after_lag: Annotated[int, Field(strict=True, ge=10)]
    min_holdout_rows_after_lag: Annotated[int, Field(strict=True, ge=10)]
    embargo_sessions: Annotated[int, Field(strict=True, ge=1)]
    window_policy: Literal["split_segments_and_equal_rolling"]
    structural_windows: tuple[WindowName, ...]
    rolling_windows: Annotated[int, Field(strict=True, ge=2)]
    min_window_rows: Annotated[int, Field(strict=True, ge=10)]
    max_inconclusive_windows: Annotated[int, Field(strict=True, ge=0)]
    max_mean_shift: Decimal
    max_variance_ratio: Decimal
    max_diff_order: Literal[0, 1, 2]
    verification_ttl_days: Annotated[int, Field(strict=True, ge=1)]

    @field_validator("alpha", "stationarity_alpha", "train_fraction", "embargo_fraction", "holdout_fraction", "max_mean_shift", "max_variance_ratio", mode="before")
    @classmethod
    def decimal_strings_only(cls, value: JsonValue) -> str:
        if not isinstance(value, str):
            raise ContractValueError("config", "expected decimal string")
        return value

    @model_validator(mode="after")
    def declared_policy(self) -> Self:
        if tuple(sorted(set(self.lag_grid))) != self.lag_grid or not self.lag_grid:
            raise ContractValueError("lag_grid", "must be non-empty, unique, ascending")
        if (self.train_fraction, self.embargo_fraction, self.holdout_fraction) != (Decimal("0.7"), Decimal("0.1"), Decimal("0.2")):
            raise ContractValueError("split_policy", "fractions must be 70/10/20")
        if tuple(dict.fromkeys(self.structural_windows)) != self.structural_windows or "embargo" not in self.structural_windows:
            raise ContractValueError("structural_windows", "must be unique and include embargo")
        if not Decimal("0") < self.alpha <= Decimal("0.05") or self.max_mean_shift <= 0 or self.max_variance_ratio < 1:
            raise ContractValueError("config", "numeric policy range invalid")
        return self


class PriorPairResult(BoundaryModel):
    input_fingerprint: HashText
    pair_id: Annotated[str, Field(pattern=r"^statpair_[0-9a-f]{20}$")]
    result_fingerprint: HashText


class VerificationAudit(BoundaryModel):
    locked_input_fingerprint: HashText | None
    locked_run_config_hash: HashText | None
    locked_correction_scope_hash: HashText | None
    locked_split_policy_hash: HashText | None
    locked_window_policy_hash: HashText | None
    train_decision_timestamps: tuple[AwareDatetime, ...]
    prior_pair_results: tuple[PriorPairResult, ...]


class VerificationInput(BoundaryModel):
    schema_version: Literal["causal-statistical-verification-build.1"]
    generated_at: AwareDatetime
    verification_cutoff: AwareDatetime
    source_node_artifact: CanonicalArtifact
    source_mapping_artifact: MappingArtifact
    series: tuple[SeriesFrame, ...]
    config: VerificationConfig
    audit: VerificationAudit
    fixture_name: str | None = None


VERIFICATION_INPUT_ADAPTER = TypeAdapter(VerificationInput)
MAPPING_ENVELOPE_ADAPTER = TypeAdapter(MappingEnvelope)
MAPPING_RECORD_ADAPTER = TypeAdapter(MappingRecord)


def latest_expiry(mapping: MappingRecord) -> datetime | None:
    if mapping.mapping_expires_at is None or not mapping.series_links:
        return None
    expiries = [mapping.mapping_expires_at]
    for link in mapping.series_links:
        expiries.extend((link.source_expires_at, link.manual_approval.expires_at))
    return min(expiries)
