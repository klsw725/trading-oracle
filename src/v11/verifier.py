from __future__ import annotations

from src.v4.models import canonical_json

from .build import build_fixture
from .bundle import ArtifactBundle, parse_bundle
from .models import V11ContractError


def verify_bundle(payload: bytes) -> ArtifactBundle:
    bundle = parse_bundle(payload)
    rebuilt = parse_bundle(canonical_json(build_fixture(bundle.source_fixture)))
    if rebuilt != bundle:
        raise V11ContractError("V11_DERIVED_FIELD_MISMATCH", "bundle")
    return bundle
