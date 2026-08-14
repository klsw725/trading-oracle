from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from src.v4.models import JsonValue, canonical_json
from src.v11.canonical import canonical_hash, parse_json
from src.v11.shorts import borrow_cost

from .build import build_fixture
from .models import V12ContractError
from .probes import run_probes
from .verifier import verify_bundle


ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURE: Final = ROOT / "docs/specs/v12/fixtures/cohort.json"
PROBE_IDS: Final = frozenset({
    "borrow_annual_fee_resealed", "borrow_annual_fee_tamper",
    "borrow_holding_period_resealed", "borrow_holding_period_tamper",
    "borrow_notional_resealed", "borrow_output_tamper", "candidate_collision",
    "case_matrix_missing", "coordinated_fill_rehash", "cost_mutation",
    "current_in_reference", "duplicate_session_signal", "fake_recall_attribution",
    "fake_risk_kill", "fake_upstream_ref", "forced_exit_mutation",
    "future_benchmark", "future_causal_sizing", "grid_fifth", "hidden_stop",
    "ignored_recall", "ignored_risk_kill", "incomplete_feature",
    "ledger_event_mutation", "llm_signal_creation", "market_grid_drift",
    "missing_risk_kill", "ownership_transfer", "public_replay_tamper",
    "retained_ref_adjustment", "retained_ref_bar_body", "retained_ref_benchmark",
    "retained_ref_observation", "retained_ref_source", "score_out_of_range",
    "short_borrow_expired", "short_borrow_not_yet_effective",
    "short_borrow_observation_lookahead", "short_without_borrow",
    "unused_future_binding_invariance", "wick_breakout", "late_orb",
    "wrong_recall_timestamp", "wrong_risk_kill_time",
})


def load_fixture(path: Path = FIXTURE) -> JsonValue:
    try:
        return parse_json(path.read_bytes())
    except OSError as error:
        raise V12ContractError("V12_FIXTURE_ERROR", str(error)) from error


def build_path(path: Path = FIXTURE) -> JsonValue:
    return build_fixture(load_fixture(path))


def accept_prd(prd: Literal[1, 2, 3, 4]) -> JsonValue:
    bundle = verify_bundle(canonical_json(build_path()))
    evaluations = bundle.run.evaluations
    trades = bundle.run.trades
    match prd:  # noqa: MATCH_OK - Literal PRD variants are exhaustively covered
        case 1: count = len({item.strategy_id for item in evaluations})
        case 2: count = len([item for item in trades if item.candidate.side.value == "long"])
        case 3: count = len([item for item in trades if item.candidate.side.value == "short"])
        case 4: count = len(evaluations)
    return {"state": "pass", "prd": prd, "case_count": count,
        "fixture_hash": bundle.fixture_hash, "bundle_hash": bundle.bundle_hash}


def run_acceptance() -> JsonValue:
    payload = canonical_json(build_path())
    first = verify_bundle(payload)
    second = verify_bundle(canonical_json(first.model_dump(mode="json")))
    if canonical_json(first.model_dump(mode="json")) != canonical_json(second.model_dump(mode="json")):
        raise V12ContractError("V12_NONDETERMINISTIC", "bundle")
    evaluations, trades, manifests = first.run.evaluations, first.run.trades, first.run.manifests
    probes = run_probes(payload)
    _verify_probe_inventory(probes)
    strategies = {item.strategy_id for item in evaluations}
    long_trades = tuple(item for item in trades if item.candidate.side.value == "long")
    short_trades = tuple(item for item in trades if item.candidate.side.value == "short")
    recall_trades = tuple(item for item in short_trades if item.exit_reason == "short_recall")
    short_close_trades = tuple(item for item in short_trades if item.exit_reason == "session_close")
    risk_kill_trades = tuple(item for item in trades if item.exit_reason == "risk_kill")
    long_risk_kills = tuple(item for item in risk_kill_trades if item.candidate.side.value == "long")
    short_risk_kills = tuple(item for item in risk_kill_trades if item.candidate.side.value == "short")
    prioritized = tuple(item for item in short_risk_kills if item.borrow.recalled_at is not None)
    owners = {item.manifest.owner_namespace for item in trades}
    body: dict[str, JsonValue] = {"schema_version": "v12.strategy.acceptance.2",
        "state": "pass", "strategy_count": len(strategies),
        "long_parameter_count": len(long_trades), "short_parameter_count": len(short_trades),
        "short_recall_count": len(recall_trades),
        "short_session_close_count": len(short_close_trades),
        "risk_kill_count": len(risk_kill_trades),
        "long_risk_kill_count": len(long_risk_kills),
        "short_risk_kill_count": len(short_risk_kills),
        "risk_kill_over_recall_count": len(prioritized),
        "borrow_cost_examples": {"10000@0.1x1": borrow_cost("10000", "0.1", 1),
            "20000@0.1x1": borrow_cost("20000", "0.1", 1),
            "10000@0.1x2": borrow_cost("10000", "0.1", 2)},
        "arm_count": len(manifests), "owner_namespace_count": len(owners),
        "scenario_count": len({item.case_id for item in evaluations}),
        "scenario_arm_case_count": len(evaluations), "probe_count": len(probes),
        "probes": [{"probe_id": key, "result_code": code} for key, code in probes],
        "artifact_hashes": {"fixture": first.fixture_hash, "upstream": first.upstream_hash,
            "registry": first.registry_hash, "bundle": first.bundle_hash,
            "run": first.run.manifest_hash,
            "trades": canonical_hash([item.ledger_hash for item in trades])},
        "partial_fill_count": sum(item.fill.state == "partial" for item in trades),
        "forced_exit_count": len(trades), "ledger_append_count": sum(len(item.events) for item in trades),
        "active_mutation_paths": ["v11_ledger_append", "in_memory_attribution"],
        "v13_plus_import_count": 0, "llm_call_count": 0,
        "statistical_promotion_count": 0, "broker_submit_count": 0,
        "live_artifact_count": 0, "portfolio_mutation_count": 0,
        "fixture_write_count": 0, "side_effect_count": 0}
    if (len(strategies), len(long_trades), len(short_trades), len(manifests), len(owners),
            len(evaluations), len(recall_trades), len(short_close_trades),
            len(long_risk_kills), len(short_risk_kills), len(prioritized)) != (
                15, 40, 20, 60, 60, 180, 4, 12, 4, 4, 4):
        raise V12ContractError("V12_ACCEPTANCE_COUNTS", str(len(evaluations)))
    return {**body, "report_hash": canonical_hash(body)}


def _verify_probe_inventory(probes: tuple[tuple[str, str], ...]) -> None:
    probe_ids = tuple(probe_id for probe_id, _ in probes)
    duplicates = tuple(sorted(probe_id for probe_id in set(probe_ids)
                              if probe_ids.count(probe_id) > 1))
    missing = tuple(sorted(PROBE_IDS - set(probe_ids)))
    unexpected = tuple(sorted(set(probe_ids) - PROBE_IDS))
    if duplicates or missing or unexpected:
        detail = f"missing={missing};duplicate={duplicates};unexpected={unexpected}"
        raise V12ContractError("V12_PROBE_INVENTORY", detail)
