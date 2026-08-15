from __future__ import annotations

from typing import Literal, TypedDict

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue
from src.v13.prd03_reliability_probes import run_reliability_probes
from src.v13.prd03_switch_probes import run_switch_probes


class Prd03AcceptanceReport(TypedDict):
    state: Literal["pass", "fail"]
    scenario_count: int
    mutation_count: int
    checks: dict[str, bool]
    mutations: dict[str, str]
    counts: dict[str, int]
    hashes: dict[str, str]
    report_hash: str


def run_acceptance() -> Prd03AcceptanceReport:
    switch_checks, switch_mutations, switch_hashes = run_switch_probes()
    reliability_checks, reliability_mutations, reliability_hashes = run_reliability_probes()
    checks = {**switch_checks, **reliability_checks}
    mutations = {**switch_mutations, **reliability_mutations}
    hashes = {**switch_hashes, **reliability_hashes}
    state: Literal["pass", "fail"] = "pass" if all(checks.values()) and all(
        result == "killed" for result in mutations.values()) else "fail"
    counts = {"switch_timeline_events": 5, "switch_ledger_events": 15,
        "circuit_recent_window": 20, "fallback_reasons": 12}
    body: JsonValue = {"state": state, "scenario_count": len(checks),
        "mutation_count": len(mutations),
        "checks": {key: value for key, value in checks.items()},
        "mutations": {key: value for key, value in mutations.items()},
        "counts": {key: value for key, value in counts.items()},
        "hashes": {key: value for key, value in hashes.items()}}
    return Prd03AcceptanceReport(state=state, scenario_count=len(checks),
        mutation_count=len(mutations), checks=checks, mutations=mutations,
        counts=counts, hashes=hashes, report_hash=canonical_hash(body))
