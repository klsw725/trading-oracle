from enum import StrEnum, unique
from typing import Annotated, ClassVar, Final, Literal, NewType, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic_core import PydanticCustomError

from src.causal.canonical_rules import canonical_node_id_value
from src.v4.models import JsonValue


MAPPING_SCHEMA_VERSION: Final = "causal-series-mapping.1"
BUILD_SCHEMA_VERSION: Final = "causal-series-mapping-build.1"
SOURCE_NODE_SCHEMA_VERSION: Final = "causal-node-canonicalization.1"
MAPPING_POLICY_VERSION: Final = "series-mapper.1"
HASH_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"

CanonicalNodeId = NewType("CanonicalNodeId", str)
SeriesId = NewType("SeriesId", str)
MappingHash = NewType("MappingHash", str)


class BoundaryModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


@unique
class MappingKind(StrEnum):
    SINGLE = "single_series"
    COMPOSITE = "composite_series"


@unique
class Transform(StrEnum):
    LEVEL = "level"
    DIFF_1D = "diff_1d"
    PCT_CHANGE_1D = "pct_change_1d"
    PCT_CHANGE_5D = "pct_change_5d"
    PCT_CHANGE_20D = "pct_change_20d"
    SPREAD = "spread"
    CUSTOM_FORMULA = "custom_formula"


@unique
class LinkDirection(StrEnum):
    SAME = "same"
    INVERSE = "inverse"
    COMPONENT = "component"
    NOT_DIRECTIONAL = "not_directional"


@unique
class RejectionResult(StrEnum):
    PROXY = "rejected_proxy"
    MISLEADING = "rejected_misleading"
    DIRTY = "rejected_dirty"


@unique
class DirtyConflictKind(StrEnum):
    DUPLICATE_NODE = "duplicate_node_id"
    DUPLICATE_CATALOG = "duplicate_catalog_series_id"
    DUPLICATE_PROPOSAL = "duplicate_terminal_proposal"
    DUPLICATE_LINK = "duplicate_series_link"
    CONFLICTING_LINKS = "conflicting_links"


@unique
class ProposalKind(StrEnum):
    APPROVE = "approve"
    UNMAPPABLE = "unmappable"
    REJECT = "reject"


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
    relation: Literal["increases", "decreases", "causes", "enables", "blocks"]


class SourceNodeArtifact(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    schema_version: Literal["causal-node-canonicalization.1"]
    nodes: tuple[CanonicalNode, ...]
    triples: tuple[CanonicalTriple, ...] = ()

    @model_validator(mode="after")
    def canonical_integrity(self) -> Self:
        node_ids = tuple(node.canonical_node_id for node in self.nodes)
        duplicate_ids = {
            node_id for node_id in node_ids if node_ids.count(node_id) > 1
        }
        for node in self.nodes:
            if node.canonical_node_id in duplicate_ids:
                continue
            expected = canonical_node_id_value(
                node.canonical_label,
                node.normalized_label,
                (node.direction.kind, node.direction.polarity),
            )
            if node.canonical_node_id != expected:
                raise PydanticCustomError(
                    "canonical_identity", "canonical node ID does not match node identity"
                )
        endpoints = {
            endpoint
            for triple in self.triples
            for endpoint in (triple.subject_node_id, triple.object_node_id)
        }
        if not endpoints.issubset(node_ids):
            raise PydanticCustomError(
                "canonical_endpoint", "canonical triple endpoint does not exist"
            )
        return self


class CatalogEntry(BoundaryModel):
    series_id: Annotated[str, Field(min_length=1)]
    raw_symbol: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    adapter_version: Annotated[str, Field(min_length=1)]
    native_unit: Annotated[str, Field(min_length=1)]
    native_frequency: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    expires_at: AwareDatetime
    provenance_hash: Annotated[str, Field(pattern=HASH_PATTERN)]


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
    provenance_hash: Annotated[str, Field(pattern=HASH_PATTERN)]
    suitability: Annotated[str, Field(min_length=1)]
    suitability_evidence: Annotated[str, Field(min_length=1)]
    manual_approval: ManualApproval


class ApprovalProposal(BoundaryModel):
    proposal_kind: Literal["approve"]
    canonical_node_id: Annotated[str, Field(min_length=1)]
    mapping_kind: MappingKind
    mapping_expires_at: AwareDatetime
    series_links: tuple[SeriesLink, ...]
    formula: str | None = None
    formula_unit: str | None = None


class RejectedProxy(BoundaryModel):
    series_id: Annotated[str, Field(min_length=1)]
    reason: Annotated[str, Field(min_length=1)]


class DirtyEvidence(BoundaryModel):
    conflict_kind: DirtyConflictKind
    original_records: Annotated[tuple[JsonValue, ...], Field(min_length=1)]
    conflict_reason: Annotated[str, Field(min_length=1)]


class ProxyEvidence(BoundaryModel):
    candidate_series_id: Annotated[str, Field(min_length=1)]
    proxy_reason: Annotated[str, Field(min_length=1)]
    missing_direct_source_explanation: Annotated[str, Field(min_length=1)]


class MisleadingEvidence(BoundaryModel):
    candidate_series_id: Annotated[str, Field(min_length=1)]
    expected_direction: LinkDirection
    observed_conflict: Annotated[str, Field(min_length=1)]


class MalformedEvidence(BoundaryModel):
    json_pointer: Annotated[str, Field(min_length=1)]
    parse_error: Annotated[str, Field(min_length=1)]


class StaleEvidence(BoundaryModel):
    expired_field: tuple[str, ...]
    run_cutoff: AwareDatetime
    affected_series_id: tuple[str, ...]
    mapping_expires_at: AwareDatetime
    source_expiries: dict[str, AwareDatetime]
    approval_expiries: dict[str, AwareDatetime]


type RejectionEvidence = (
    DirtyEvidence | ProxyEvidence | MisleadingEvidence | MalformedEvidence | StaleEvidence
)


class UnmappableProposal(BoundaryModel):
    proposal_kind: Literal["unmappable"]
    canonical_node_id: Annotated[str, Field(min_length=1)]
    reason: Annotated[str, Field(min_length=1)]
    proxy_candidates_rejected: tuple[RejectedProxy, ...]


class DirtyRejectionProposal(BoundaryModel):
    proposal_kind: Literal["reject"]
    canonical_node_id: Annotated[str, Field(min_length=1)]
    candidate_series_id: Annotated[str, Field(min_length=1)]
    reason: Literal[RejectionResult.DIRTY]
    evidence: DirtyEvidence


class ProxyRejectionProposal(BoundaryModel):
    proposal_kind: Literal["reject"]
    canonical_node_id: Annotated[str, Field(min_length=1)]
    candidate_series_id: Annotated[str, Field(min_length=1)]
    reason: Literal[RejectionResult.PROXY]
    evidence: ProxyEvidence


class MisleadingRejectionProposal(BoundaryModel):
    proposal_kind: Literal["reject"]
    canonical_node_id: Annotated[str, Field(min_length=1)]
    candidate_series_id: Annotated[str, Field(min_length=1)]
    reason: Literal[RejectionResult.MISLEADING]
    evidence: MisleadingEvidence


type RejectionProposal = (
    DirtyRejectionProposal | ProxyRejectionProposal | MisleadingRejectionProposal
)


class ProposalEnvelope(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    proposal_kind: ProposalKind
    canonical_node_id: str


class ProposalNodeReference(BoundaryModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    canonical_node_id: Annotated[str, Field(min_length=1)]


class MappingBuildInput(BoundaryModel):
    schema_version: Literal["causal-series-mapping-build.1"]
    generated_at: AwareDatetime
    run_cutoff: AwareDatetime
    source_node_artifact: SourceNodeArtifact
    series_catalog: tuple[CatalogEntry, ...]
    proposals: tuple[JsonValue, ...]
    legacy_flat_map: dict[str, str]


BUILD_INPUT_ADAPTER: Final = TypeAdapter(MappingBuildInput)
ENVELOPE_ADAPTER: Final = TypeAdapter(ProposalEnvelope)
PROPOSAL_NODE_ADAPTER: Final = TypeAdapter(ProposalNodeReference)
APPROVAL_ADAPTER: Final = TypeAdapter(ApprovalProposal)
UNMAPPABLE_ADAPTER: Final = TypeAdapter(UnmappableProposal)
REJECTION_ADAPTER: Final[TypeAdapter[RejectionProposal]] = TypeAdapter(RejectionProposal)
