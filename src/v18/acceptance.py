from .acceptance_checks import run_checks
from .acceptance_models import ProbeResult
from .acceptance_mutations import run_mutations
from .acceptance_support import Scenario, prepared_candidate
from .boundaries import (
    counts,
    fresh_boundary_counts,
    install_observer,
    later_source_imports,
    observe_boundaries,
    snapshot,
    tracked_snapshot,
)
from .canonical import JsonValue, canonical_hash, canonical_json
from .errors import V18Error
from .fixtures import ROOT, fixture_inventory
from .migrations import SCHEMA_HASH


def _probe_json(result: ProbeResult) -> JsonValue:
    return {"expected": result.expected, "id": result.id, "status": result.status}


def _table_hashes() -> dict[str, str]:
    with Scenario.open() as scenario:
        _ = prepared_candidate(scenario)
        return scenario.repository.table_hashes()


def _material() -> JsonValue:
    install_observer()
    portfolio_path = ROOT / "data/portfolio.json"
    portfolio_before = snapshot(portfolio_path)
    fixtures_before = fixture_inventory()
    worktree_before = tracked_snapshot(ROOT)
    if later_source_imports(ROOT):
        raise V18Error("BOUNDARY_LATER_IMPORT", str(later_source_imports(ROOT)))
    fresh = fresh_boundary_counts(ROOT)
    if fresh.network or fresh.later_import or fresh.broker or fresh.live or fresh.credential:
        raise V18Error("BOUNDARY_VIOLATION", str(fresh))
    with observe_boundaries():
        checks = run_checks()
        mutations = run_mutations(counts())
        observed = counts()
    if observed.network or observed.later_import or observed.broker or observed.live or observed.credential:
        raise V18Error("BOUNDARY_VIOLATION", str(observed))
    portfolio_after = snapshot(portfolio_path)
    if portfolio_before != portfolio_after:
        raise V18Error("PORTFOLIO_MUTATED", str(portfolio_path))
    if fixtures_before != fixture_inventory():
        raise V18Error("FIXTURE_MUTATED", "v18 fixture inventory")
    if worktree_before != tracked_snapshot(ROOT):
        raise V18Error("TRACKED_WORKTREE_MUTATED", str(ROOT))
    boundaries: list[JsonValue] = [
        {"count": 0, "id": "broker", "status": "PASS"},
        {"count": 0, "id": "credential", "status": "PASS"},
        {"count": 0, "id": "later_import", "status": "PASS"},
        {"count": 0, "id": "live_destination", "status": "PASS"},
        {"count": 0, "id": "network", "status": "PASS"},
        {"count": 0, "id": "portfolio_mutation", "status": "PASS"},
    ]
    fixture_json: dict[str, JsonValue] = {
        key: value for key, value in sorted(fixtures_before.items())
    }
    table_json: dict[str, JsonValue] = {
        key: value for key, value in sorted(_table_hashes().items())
    }
    return {
        "boundaries": boundaries,
        "candidate_schema_version": "v18.policy-candidate.1",
        "checks": [_probe_json(item) for item in checks],
        "fixture_inventory": fixture_json,
        "mutations": [_probe_json(item) for item in mutations],
        "outcome_schema_version": "v18.outcome.1",
        "prediction_schema_version": "v18.prediction.1",
        "schema_hash": SCHEMA_HASH,
        "schema_version": "v18.acceptance.1",
        "status": "PASS",
        "table_hashes": table_json,
        "version": "v18",
    }


def run_acceptance() -> JsonValue:
    first = _material()
    second = _material()
    if canonical_json(first) != canonical_json(second):
        raise V18Error("ACCEPTANCE_NONDETERMINISTIC", "material differs")
    if not isinstance(first, dict):
        raise AssertionError("acceptance material must be an object")
    report: dict[str, JsonValue] = dict(first)
    report["report_hash"] = canonical_hash(first)
    return report
