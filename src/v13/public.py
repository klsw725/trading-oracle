from __future__ import annotations

from typing import Literal

from src.v11.canonical import canonical_hash, model_json
from src.v13.models import StrictModel
from src.v13.prd04_models import Prd04Bundle
from src.v13.replay import NoCallProvider, ReplayResult, replay_decision
from src.v13.selection import run_router


class ShadowResult(StrictModel):
    state: Literal["pass"]
    selection_hash: str
    byte_identical: bool
    shadow_hash: str


def replay_bundle(bundle: Prd04Bundle) -> ReplayResult:
    return replay_decision(bundle.replay_record, NoCallProvider())


def shadow_bundle(bundle: Prd04Bundle) -> ShadowResult:
    manifest = bundle.replay_record.router_manifest.model_copy(
        update={"candidates": bundle.recorded_scoring.candidates})
    selection = run_router(manifest)
    identical = model_json(selection) == model_json(bundle.router_selection)
    return ShadowResult(state="pass", selection_hash=selection.selection_hash,
        byte_identical=identical,
        shadow_hash=canonical_hash({"selection_hash": selection.selection_hash,
            "byte_identical": identical}))
