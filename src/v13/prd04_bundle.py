from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json, normalize_scalar
from src.v11.models import Market
from src.v4.models import JsonValue
from src.v13.adapter import adapt_source
from src.v13.circuit_breaker import initial_state
from src.v13.coverage import coverage_artifact, normative_probes
from src.v13.models import RouterRunManifest
from src.v13.policy import build_policy
from src.v13.prd03_fixture import SwitchScenario, switch_execution
from src.v13.prd03_models import CircuitKey
from src.v13.prd04_models import (
    CandidateInventory,
    Prd04Bundle,
    Prd04SourceFixture,
    VersionPins,
)
from src.v13.prd04_recorded import request_for
from src.v13.replay import NoCallProvider, RecordInput, record_decision, replay_decision
from src.v13.selection import run_router
from src.v13.switch import execute_switch


def build_bundle(source: Prd04SourceFixture) -> Prd04Bundle:
    adapted = adapt_source(source)
    request = request_for(adapted.router_candidates, adapted.context)
    policy = build_policy()
    manifest = RouterRunManifest(schema_version="v13.router_run.1",
        run_id="prd04:recorded", market=Market(request.identity.market.value),
        cutoff=request.identity.cutoff, policy=policy, account=adapted.account,
        candidates=adapted.router_candidates, slot_limit=2)
    key = CircuitKey(market=manifest.market,
        regular_session_id=f"{manifest.market.value}:{manifest.cutoff.date()}:regular")
    record = record_decision(RecordInput(request=request,
        recorded_response=source.recorded_response,
        circuit_state=initial_state(key), circuit_key=key,
        router_manifest=manifest))
    replayed = replay_decision(record, NoCallProvider())
    routed = record.routed
    selection = run_router(manifest.model_copy(
        update={"candidates": routed.artifact.candidates}))
    switch = execute_switch(switch_execution(SwitchScenario(
        score=source.switch_fixture.challengers.exact), source.switch_fixture))
    candidate_ids = tuple(sorted(item.candidate_id for item in adapted.candidates))
    inventory = CandidateInventory(candidate_ids=candidate_ids,
        candidate_inventory_hash=canonical_hash(list(candidate_ids)),
        canonical_symbols=adapted.canonical_symbols,
        symbol_inventory_hash=canonical_hash(list(adapted.canonical_symbols)))
    probes = normative_probes()
    coverage = coverage_artifact(probes)
    versions = VersionPins(policy_version="v13.router_policy.1",
        policy_hash=policy.policy_hash, model_id=request.identity.model_id,
        prompt_version=request.identity.prompt_version,
        schema_version=request.identity.schema_version,
        detector_version=request.identity.detector_version)
    fixture_hash = canonical_hash(model_json(source))
    run_body: JsonValue = {"fixture_hash": fixture_hash,
        "upstream": model_json(adapted.upstream), "versions": model_json(versions),
        "inventory": model_json(inventory), "request": model_json(request),
        "selection": model_json(selection), "scoring": model_json(routed.artifact),
        "switch": model_json(switch), "circuit": model_json(routed),
        "replay": model_json(replayed), "probes": [model_json(item) for item in probes],
        "coverage": model_json(coverage)}
    run_hash = canonical_hash(run_body)
    unsealed = Prd04Bundle(schema_version="v13.router.bundle.1",
        fixture_hash=fixture_hash, source_fixture=source, upstream=adapted.upstream,
        versions=versions, inventory=inventory, request=request,
        router_selection=selection, recorded_scoring=routed.artifact,
        switch=switch, circuit=routed, replay_record=record,
        replay_result=replayed, probes=probes, coverage=coverage,
        run_hash=run_hash, bundle_hash="sha256:pending")
    body = normalize_scalar(unsealed.model_dump(mode="json", exclude={"bundle_hash"}))
    return unsealed.model_copy(update={"bundle_hash": canonical_hash(body)})
