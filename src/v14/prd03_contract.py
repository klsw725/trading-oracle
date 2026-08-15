from __future__ import annotations

from typing import Literal, TypedDict

from src.v11.canonical import canonical_hash
from src.v12.registry import REGISTRY
from src.v4.models import JsonValue

from .hypotheses import PRIMARY_ID
from .prd03_pipeline import build_prd03
from .prd03_probes import run_probes


class Prd03AcceptanceReport(TypedDict):
    state: Literal["pass", "fail"]
    check_count: int
    mutation_count: int
    holm_correction_count: int
    bh_correction_count: int
    observed_strategy_verdict_count: int
    observed_router_verdict_count: int
    primary_id: str
    holm_family_ids: tuple[str, ...]
    verdict_inventory: tuple[str, ...]
    checks: dict[str, bool]
    mutations: dict[str, str]
    hashes: dict[str, str]
    report_hash: str


def run_acceptance() -> Prd03AcceptanceReport:
    checks, mutations, hashes, verdicts = run_probes()
    artifacts = build_prd03()
    state: Literal["pass", "fail"] = (
        "pass" if all(checks.values())
        and all(value == "killed" for value in mutations.values()) else "fail"
    )
    checks_json: JsonValue = {key: value for key, value in checks.items()}
    mutations_json: JsonValue = {key: value for key, value in mutations.items()}
    hashes_json: JsonValue = {key: value for key, value in hashes.items()}
    holm_family_ids = tuple(item.strategy_id for item in REGISTRY
        if item.strategy_id != PRIMARY_ID)
    body: JsonValue = {"state": state, "check_count": len(checks),
        "mutation_count": len(mutations), "primary_id": PRIMARY_ID,
        "holm_correction_count": len(artifacts.holm_corrections),
        "bh_correction_count": len(artifacts.bh_corrections),
        "observed_strategy_verdict_count":
            len(artifacts.observed_strategy_verdicts),
        "observed_router_verdict_count": len(artifacts.observed_router_verdicts),
        "holm_family_ids": list(holm_family_ids),
        "verdict_inventory": list(verdicts),
        "checks": checks_json, "mutations": mutations_json, "hashes": hashes_json}
    return Prd03AcceptanceReport(state=state, check_count=len(checks),
        mutation_count=len(mutations), primary_id=PRIMARY_ID,
        holm_correction_count=len(artifacts.holm_corrections),
        bh_correction_count=len(artifacts.bh_corrections),
        observed_strategy_verdict_count=len(artifacts.observed_strategy_verdicts),
        observed_router_verdict_count=len(artifacts.observed_router_verdicts),
        holm_family_ids=holm_family_ids, verdict_inventory=verdicts,
        checks=checks, mutations=mutations, hashes=hashes,
        report_hash=canonical_hash(body))
