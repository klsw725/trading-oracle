from __future__ import annotations

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue

from .acceptance_fixture import BUNDLE_PATH
from .operation_verify import verify_operation_bundle
from .operation_models import material_from_bundle
from .operation_replay import replay
from .prd01_acceptance import evaluate as evaluate_prd01
from .prd02_acceptance import evaluate as evaluate_prd02
from .prd03_acceptance import evaluate as evaluate_prd03
from .prd04_acceptance import evaluate as evaluate_prd04


def _field(record: dict[str, JsonValue], key: str) -> JsonValue:
    return record.get(key)


def _hash_field(record: dict[str, JsonValue]) -> str:
    value = record.get("report_hash")
    return value if isinstance(value, str) else "invalid"


def _count_field(record: dict[str, JsonValue]) -> int:
    value = record.get("check_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def run_acceptance() -> JsonValue:
    payload = BUNDLE_PATH.read_bytes()
    first = verify_operation_bundle(payload)
    material = material_from_bundle(first)
    first_replay = replay(material)
    second_replay = replay(material)
    prd01 = evaluate_prd01(first)
    prd02 = evaluate_prd02(first)
    prd03 = evaluate_prd03(first)
    prd04 = evaluate_prd04(first)
    reports = (prd01, prd02, prd03, prd04)
    mutations: dict[str, JsonValue] = {}
    for item in reports:
        value = _field(item, "mutations")
        if isinstance(value, dict):
            mutations.update(value)
    hard_boundaries = _field(prd04, "hard_boundaries")
    inventory = first.replay.side_effect_inventory
    deterministic = first_replay == second_replay == first.replay
    checks: dict[str, bool] = {
        "all_prds_pass": all(_field(item, "state") == "pass"
            for item in reports),
        "exact_15_mutations_killed": len(mutations) == 15
            and all(value == "killed" for value in mutations.values()),
        "three_hard_boundaries_pass": isinstance(hard_boundaries, dict)
            and len(hard_boundaries) == 3
            and all(value == "killed" for value in hard_boundaries.values()),
        "serialized_bundle_deterministic_replay": deterministic,
        "zero_network_calls_from_effect_ledger": inventory.network_calls == 0,
        "zero_provider_calls_from_effect_ledger": inventory.provider_calls == 0,
        "zero_broker_submits_from_effect_ledger": inventory.broker_submits == 0,
        "zero_live_artifacts_from_effect_ledger": inventory.live_artifacts == 0,
        "zero_portfolio_access_from_effect_ledger": inventory.portfolio_reads == 0
            and inventory.portfolio_writes == 0,
    }
    report_hashes: JsonValue = {f"prd{index:02d}": _hash_field(item)
        for index, item in enumerate(reports, start=1)}
    counts: JsonValue = {"prd_count": 4,
        "check_count": sum(_count_field(item) for item in reports),
        "mutation_count": len(mutations), "hard_boundary_count": 3,
        "operation_event_count": len(first.events),
        "official_session_count": sum(len(item.paired_series.points)
            for item in first.markets),
        "market_count": len(first.markets),
        "mirror_count": sum(len(item.mirror_ledgers) for item in first.markets),
        "qualification_ledger_count": len(first.markets),
        "qualification_session_count": sum(
            item.orb_qualification.official_sessions for item in first.markets),
        "qualification_trade_count": sum(
            item.orb_qualification.completed_trades for item in first.markets),
        "session_report_count": len(first.session_reports),
        "effect_record_count": len(first.effects.records),
        "network_call_count": inventory.network_calls,
        "provider_call_count": inventory.provider_calls,
        "broker_submit_count": inventory.broker_submits,
        "live_artifact_count": inventory.live_artifacts,
        "portfolio_access_count": inventory.portfolio_reads
            + inventory.portfolio_writes}
    state = "pass" if all(checks.values()) else "fail"
    body: dict[str, JsonValue] = {"schema_version": "v15.acceptance.2",
        "state": state, "checks": {key: value for key, value in checks.items()},
        "counts": counts, "reports": report_hashes,
        "mutations": {key: value for key, value in mutations.items()},
        "hard_boundaries": hard_boundaries,
        "artifacts": {"operation_bundle_hash": first.bundle_hash,
            "replay_hash": first.replay.replay_hash,
            "v14_bundle_hash": first.upstream.v14_bundle_hash,
            "paired_series_hashes": list(first.replay.paired_series_hashes),
            "qualification_hashes": [item.orb_qualification.evidence_hash
                for item in first.markets],
            "data_exception_hash": first.approvals[0].data_exceptions[0]
                .evidence_hash,
            "retirement_tail_hash": first.retirement_registry.tail_hash,
            "effect_ledger_hash": first.effects.ledger_hash}}
    return {**body, "report_hash": canonical_hash(body)}
