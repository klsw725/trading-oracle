from __future__ import annotations

from typing import Final

from pydantic import TypeAdapter, ValidationError
from src.v11.canonical import canonical_hash, model_json, parse_json, reject_forbidden
from src.v11.models import V11ContractError
from src.v4.models import canonical_json

from .contract import V15Failure, V15FailureCode
from .effects import verify_paper_effects
from .fixtures import verify_v14_path
from .operation_build import build_operation_bundle
from .operation_models import (
    OperationBundle,
    OperationBundleBody,
    material_from_bundle,
)
from .operation_replay import replay
from .paper_boundary import verify_paper_boundary


_BUNDLE: Final = TypeAdapter(OperationBundle)


def verify_operation_bundle(payload: bytes) -> OperationBundle:
    try:
        raw = parse_json(payload)
        reject_forbidden(raw)
        bundle = _BUNDLE.validate_json(payload)
    except (ValidationError, V11ContractError) as error:
        raise V15Failure(V15FailureCode.ARTIFACT_MALFORMED, str(error)) from error
    verify_paper_boundary({"destination": bundle.source.destination})
    source_hash = canonical_hash(model_json(bundle.source))
    if source_hash != bundle.source_fixture_hash:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "source_fixture")
    body = OperationBundleBody.model_validate(
        bundle.model_dump(exclude={"bundle_hash"}))
    if canonical_hash(model_json(body)) != bundle.bundle_hash:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "bundle_hash")
    upstream = verify_v14_path(bundle.source.v14_artifact)
    if upstream != bundle.upstream:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "upstream")
    _ = verify_paper_effects(bundle.effects)
    material = material_from_bundle(bundle)
    if replay(material) != bundle.replay:
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "replay")
    rebuilt = build_operation_bundle(bundle.source, upstream)
    if canonical_json(model_json(rebuilt)) != canonical_json(model_json(bundle)):
        raise V15Failure(V15FailureCode.BUNDLE_MISMATCH, "derived_bundle")
    return bundle
