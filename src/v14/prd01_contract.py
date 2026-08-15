from __future__ import annotations

from typing import Literal, TypedDict

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue

from .prd01_probes import run_probes


class AcceptanceReport(TypedDict):
    state: Literal["pass", "fail"]
    check_count: int
    mutation_count: int
    checks: dict[str, bool]
    mutations: dict[str, str]
    hashes: dict[str, str]
    report_hash: str


def run_acceptance() -> AcceptanceReport:
    checks, mutations, hashes = run_probes()
    state: Literal["pass", "fail"] = (
        "pass" if all(checks.values())
        and all(value == "killed" for value in mutations.values()) else "fail"
    )
    body: JsonValue = {
        "state": state,
        "check_count": len(checks),
        "mutation_count": len(mutations),
        "checks": {key: value for key, value in checks.items()},
        "mutations": {key: value for key, value in mutations.items()},
        "hashes": {key: value for key, value in hashes.items()},
    }
    return AcceptanceReport(state=state, check_count=len(checks),
        mutation_count=len(mutations), checks=checks, mutations=mutations,
        hashes=hashes, report_hash=canonical_hash(body))
