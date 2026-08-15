from __future__ import annotations

from functools import cache

from src.v4.models import canonical_json
from src.v10.acceptance import FIXTURES as V10_FIXTURES
from src.v10.acceptance import build_path as build_v10
from src.v10.verifier import verify_bundle as verify_v10
from src.v11.acceptance import FIXTURES as V11_FIXTURES
from src.v11.acceptance import build_path as build_v11
from src.v11.verifier import verify_bundle as verify_v11
from src.v12.acceptance import build_path as build_v12
from src.v12.verifier import verify_bundle as verify_v12
from src.v13.prd04_bundle import build_bundle as build_v13
from src.v13.prd04_models import Prd04SourceFixture
from src.v13.prd04_verifier import verify_bundle as verify_v13
from src.v13.public import replay_bundle, shadow_bundle

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue

from .failure import V14Failure, V14FailureCode
from .prd04_models import CompatibilityEvidence


def build_compatibility(source: Prd04SourceFixture) -> CompatibilityEvidence:
    return _build_compatibility(canonical_json(source.model_dump(mode="json")))


@cache
def _build_compatibility(payload: bytes) -> CompatibilityEvidence:
    v10 = tuple(verify_v10(canonical_json(build_v10(V10_FIXTURES[index])))
        for index in (1, 2, 3, 4))
    v11 = tuple(verify_v11(canonical_json(build_v11(V11_FIXTURES[index])))
        for index in (1, 2, 3, 4))
    v12 = verify_v12(canonical_json(build_v12()))
    source = Prd04SourceFixture.model_validate_json(payload)
    v13 = verify_v13(canonical_json(build_v13(source).model_dump(mode="json")))
    replayed = replay_bundle(v13)
    shadow = shadow_bundle(v13)
    strategy_count = len({item.strategy_id for item in v12.run.evaluations})
    case_count = len({item.case_id for item in v12.run.evaluations})
    if strategy_count != 15 or case_count != 45 or len(v13.probes) != 13:
        raise V14Failure(V14FailureCode.ARTIFACT_MALFORMED, "compatibility counts")
    body: JsonValue = {"v10": [item.bundle_hash for item in v10],
        "v11": [item.bundle_hash for item in v11],
        "v12": v12.bundle_hash, "v13": v13.bundle_hash,
        "v13_replay": replayed.replay_hash, "v13_shadow": shadow.shadow_hash}
    return CompatibilityEvidence(v10_prd_count=4, v11_prd_count=4,
        v12_strategy_count=15, v12_case_count=45,
        v13_probe_count=13,
        v13_replay_provider_call_count=replayed.provider_call_count,
        compatibility_hash=canonical_hash(body))
