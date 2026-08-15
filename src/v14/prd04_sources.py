from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError
from src.v11.canonical import canonical_hash, model_json
from src.v13.adapter import compile_source
from src.v13.prd04_models import Prd04InputDescriptor

from .failure import V14Failure, V14FailureCode
from .fixture import Prd01Fixture
from .prd04_source_models import (
    LoadedSources,
    Prd04Source,
    SourceEvidence,
    SourceEvidenceBody,
    SourceFileEvidence,
)
from .series_models import CostFixture
from .verdict_models import Prd03Fixture


def _bytes(root: Path, relative: str) -> bytes:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise V14Failure(V14FailureCode.INPUT_READ, relative)
    try:
        return path.read_bytes()
    except OSError as error:
        raise V14Failure(V14FailureCode.INPUT_READ, relative) from error


def _content_hash(payload: bytes) -> str:
    return f"sha256:{sha256(payload).hexdigest()}"


def load_sources(source: Prd04Source, root: Path) -> LoadedSources:
    paths = source.sources
    prd01_bytes = _bytes(root, paths.prd01_input)
    prd02_bytes = _bytes(root, paths.prd02_input)
    prd03_bytes = _bytes(root, paths.prd03_input)
    v13_bytes = _bytes(root, paths.v13_source)
    try:
        prd01 = Prd01Fixture.model_validate_json(prd01_bytes)
        prd02 = CostFixture.model_validate_json(prd02_bytes)
        prd03 = Prd03Fixture.model_validate_json(prd03_bytes)
        descriptor = Prd04InputDescriptor.model_validate_json(v13_bytes)
        v13 = compile_source(descriptor, root)
    except ValidationError as error:
        raise V14Failure(V14FailureCode.ARTIFACT_MALFORMED, str(error)) from error
    files = (
        SourceFileEvidence(source_id="prd01_input", path=paths.prd01_input,
            schema_version=prd01.schema_version,
            content_hash=_content_hash(prd01_bytes),
            artifact_hash=canonical_hash(model_json(prd01))),
        SourceFileEvidence(source_id="prd02_input", path=paths.prd02_input,
            schema_version=prd02.schema_version,
            content_hash=_content_hash(prd02_bytes),
            artifact_hash=canonical_hash(model_json(prd02))),
        SourceFileEvidence(source_id="prd03_input", path=paths.prd03_input,
            schema_version=prd03.schema_version,
            content_hash=_content_hash(prd03_bytes),
            artifact_hash=canonical_hash(model_json(prd03))),
        SourceFileEvidence(source_id="v13_source", path=paths.v13_source,
            schema_version=descriptor.schema_version,
            content_hash=_content_hash(v13_bytes),
            artifact_hash=canonical_hash(model_json(descriptor))),
    )
    body = SourceEvidenceBody(schema_version="v14.source_evidence.1", files=files)
    evidence = SourceEvidence(schema_version=body.schema_version, files=body.files,
        evidence_hash=canonical_hash(model_json(body)))
    return LoadedSources(evidence=evidence, prd01=prd01, prd02=prd02,
        prd03=prd03, v13=v13)


def verify_source_evidence(evidence: SourceEvidence) -> None:
    body = SourceEvidenceBody(
        schema_version=evidence.schema_version, files=evidence.files)
    if canonical_hash(model_json(body)) != evidence.evidence_hash:
        raise V14Failure(V14FailureCode.HASH_MISMATCH, evidence.evidence_hash)
