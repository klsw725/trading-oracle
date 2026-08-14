from __future__ import annotations

from src.v4.models import canonical_json

from .build import build_fixture
from .bundle import ArtifactBundle, parse_bundle
from .models import V12ContractError


def verify_bundle(payload: bytes) -> ArtifactBundle:
    bundle = parse_bundle(payload)
    rebuilt = parse_bundle(canonical_json(build_fixture(bundle.source_fixture)))
    if canonical_json(rebuilt.model_dump(mode="json")) != canonical_json(bundle.model_dump(mode="json")):
        raise V12ContractError("V12_DERIVED_FIELD_MISMATCH", "bundle")
    return bundle
