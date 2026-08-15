from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field
from src.v13.prd04_models import Prd04SourceFixture

from .contract import StrictModel
from .fixture import Prd01Fixture
from .series_models import CostFixture
from .verdict_models import Prd03Fixture


class SourcePaths(StrictModel):
    prd01_input: str
    prd02_input: str
    prd03_input: str
    v13_source: str


class ApprovalInput(StrictModel):
    operator_id: str
    approved_at: AwareDatetime
    approval_reason: str


class LeaseInput(StrictModel):
    lease_id: str


class Prd04Source(StrictModel):
    schema_version: Literal["v14.prd04.source.2"]
    sources: SourcePaths
    approval: ApprovalInput
    lease: LeaseInput


class SourceFileEvidence(StrictModel):
    source_id: Literal["prd01_input", "prd02_input", "prd03_input", "v13_source"]
    path: str
    schema_version: str
    content_hash: str
    artifact_hash: str


class SourceEvidenceBody(StrictModel):
    schema_version: Literal["v14.source_evidence.1"]
    files: Annotated[tuple[SourceFileEvidence, ...], Field(strict=False)]


class SourceEvidence(SourceEvidenceBody):
    evidence_hash: str


class LoadedSources(StrictModel):
    evidence: SourceEvidence
    prd01: Prd01Fixture
    prd02: CostFixture
    prd03: Prd03Fixture
    v13: Prd04SourceFixture
