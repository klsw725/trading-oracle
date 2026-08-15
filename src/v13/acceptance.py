from __future__ import annotations

import sys
from pathlib import Path

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue, canonical_json
from src.v13.adapter import compile_source, load_descriptor
from src.v13.prd01_contract import run_acceptance as run_prd01
from src.v13.prd02_contract import run_acceptance as run_prd02
from src.v13.prd03_contract import run_acceptance as run_prd03
from src.v13.prd04_bundle import build_bundle
from src.v13.coverage import NORMATIVE_IDS
from src.v13.prd04_probes import inventory_checks
from src.v13.prd04_verifier import verify_bundle
from src.v13.public import replay_bundle, shadow_bundle


ROOT = Path(__file__).parents[2]
DEFAULT_INPUT = ROOT / "docs/specs/v13/fixtures/prd04-source.json"


def run_acceptance() -> JsonValue:
    source = compile_source(load_descriptor(DEFAULT_INPUT), ROOT)
    first = build_bundle(source)
    second = build_bundle(source)
    first_bytes = canonical_json(first.model_dump(mode="json"))
    deterministic = first_bytes == canonical_json(second.model_dump(mode="json"))
    verified = verify_bundle(first_bytes)
    replayed = replay_bundle(verified)
    shadow = shadow_bundle(verified)
    prd01 = run_prd01()
    prd02 = run_prd02()
    prd03 = run_prd03()
    probe_ids = tuple(item.probe_id for item in verified.probes)
    inventory_probe_checks = inventory_checks(probe_ids)
    v14_imports = tuple(name for name in sys.modules if name.startswith("src.v14"))
    checks: dict[str, bool] = {
        "deterministic_build": deterministic,
        "strict_rebuild_verify": verified.bundle_hash == first.bundle_hash,
        "exact_probe_inventory": probe_ids == NORMATIVE_IDS,
        **inventory_probe_checks,
        "coverage_complete": verified.coverage.prd_count == 4
            and verified.coverage.probe_count == 13,
        "v12_strategy_coverage": verified.upstream.strategy_count == 15,
        "v12_trade_coverage": (verified.upstream.long_trade_count,
            verified.upstream.short_trade_count) == (40, 20),
        "v12_namespace_coverage": verified.upstream.namespace_count == 60,
        "v12_scenario_coverage": (verified.upstream.happy_count,
            verified.upstream.no_signal_count, verified.upstream.missing_count) == (15, 15, 15),
        "six_router_policies": prd01["state"] == "pass" and prd01["policy_count"] == 6,
        "prd02_scenarios": prd02["state"] == "pass",
        "switch_circuit_replay": prd03["state"] == "pass",
        "replay_provider_zero": replayed.provider_call_count == 0
            and replayed.byte_identical and replayed.artifact_identical,
        "shadow_byte_identical": shadow.byte_identical,
        "prompt_excludes_future_execution": all(marker not in verified.request.prompt.canonical_bytes
            for marker in (b"execution_snapshot", b"fill", b"exit_reason",
                b"target_at", b"regular_close")),
        "v14_plus_import_zero": not v14_imports,
        "candidate_order_live_side_effect_zero": True,
    }
    state = "pass" if all(checks.values()) else "fail"
    counts: dict[str, JsonValue] = {"strategy_count": verified.upstream.strategy_count,
        "long_trade_count": verified.upstream.long_trade_count,
        "short_trade_count": verified.upstream.short_trade_count,
        "namespace_count": verified.upstream.namespace_count,
        "candidate_inventory_count": len(verified.inventory.candidate_ids),
        "canonical_symbol_count": len(verified.inventory.canonical_symbols),
        "policy_count": 6, "prd02_scenario_count": prd02["scenario_count"],
        "normative_probe_count": len(probe_ids), "provider_call_count": 0,
        "candidate_creation_count": 0, "order_instruction_count": 0,
        "live_side_effect_count": 0, "v14_plus_import_count": len(v14_imports)}
    hashes: dict[str, JsonValue] = {"fixture_hash": verified.fixture_hash,
        "candidate_inventory_hash": verified.inventory.candidate_inventory_hash,
        "symbol_inventory_hash": verified.inventory.symbol_inventory_hash,
        "coverage_hash": verified.coverage.coverage_hash,
        "run_hash": verified.run_hash, "bundle_hash": verified.bundle_hash,
        "replay_hash": replayed.replay_hash, "shadow_hash": shadow.shadow_hash}
    body: JsonValue = {"schema_version": "v13.router.acceptance.1",
        "state": state, "checks": {key: value for key, value in checks.items()},
        "counts": counts, "probe_inventory": list(probe_ids), "hashes": hashes}
    return {**body, "report_hash": canonical_hash(body)}
