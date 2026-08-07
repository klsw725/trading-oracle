from typing import Annotated, Literal

from pydantic import Field

from src.v6.models import BoundaryModel

from .models import HashText, ProvenanceEnvelope
from .quality_registry_models import ReliabilityClass, SourceKind


class NormalizedClaim(BoundaryModel):
    predicate: Annotated[str, Field(min_length=1)]
    object_value: Annotated[str, Field(min_length=1)]
    polarity: Literal["supports", "opposes"]
    numeric_consistency: Literal["match", "range_match", "mismatch", "not_applicable"]
    text: Annotated[str, Field(min_length=1)]


class NormalizedQualityRecord(BoundaryModel):
    record_type: Literal["quality_claim"]
    market: Annotated[str, Field(min_length=1)]
    ticker: Annotated[str, Field(min_length=1)]
    event_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    canonical_url: Annotated[str, Field(min_length=1)]
    canonical_title: Annotated[str, Field(min_length=1)]
    claim: NormalizedClaim
    untrusted_text: tuple[Annotated[str, Field(min_length=1)], ...]
    upstream_provenance_hash: HashText | None = None


class DerivedSourceEvidence(BoundaryModel):
    record_id: str
    source_id: str
    provenance: ProvenanceEnvelope
    manifest_root: HashText
    registry_root: HashText
    source_kind: SourceKind
    upstream_provenance_hash: HashText | None
    subject_id: str
    event_date: str
    source_family: str
    canonical_url: str
    canonical_title: str
    claim_text: str
    predicate: str
    object_value: str
    polarity: Literal["supports", "opposes"]
    numeric_consistency: Literal["match", "range_match", "mismatch", "not_applicable"]
    reliability_class: ReliabilityClass
    untrusted_text: tuple[str, ...]
