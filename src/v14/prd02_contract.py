from __future__ import annotations

from typing import Literal, TypedDict

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue

from .prd02_probes import run_probes


class Prd02AcceptanceReport(TypedDict):
    state: Literal["pass", "fail"]
    check_count: int
    mutation_count: int
    strategy_metric_count: int
    router_comparison_count: int
    checks: dict[str, bool]
    mutations: dict[str, str]
    hashes: dict[str, str]
    report_hash: str


def run_acceptance() -> Prd02AcceptanceReport:
    checks, mutations, hashes, strategy_count, router_count = run_probes()
    state: Literal["pass", "fail"] = (
        "pass" if all(checks.values())
        and all(value == "killed" for value in mutations.values()) else "fail"
    )
    checks_json: JsonValue = {key: value for key, value in checks.items()}
    mutations_json: JsonValue = {key: value for key, value in mutations.items()}
    hashes_json: JsonValue = {key: value for key, value in hashes.items()}
    body: JsonValue = {"state": state, "check_count": len(checks),
        "mutation_count": len(mutations),
        "strategy_metric_count": strategy_count,
        "router_comparison_count": router_count,
        "checks": checks_json, "mutations": mutations_json, "hashes": hashes_json}
    return Prd02AcceptanceReport(state=state, check_count=len(checks),
        mutation_count=len(mutations), strategy_metric_count=strategy_count,
        router_comparison_count=router_count,
        checks=checks, mutations=mutations, hashes=hashes,
        report_hash=canonical_hash(body))
