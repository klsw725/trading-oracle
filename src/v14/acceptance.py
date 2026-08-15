from __future__ import annotations

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue

from .prd01_contract import run_acceptance as run_prd01
from .prd02_contract import run_acceptance as run_prd02
from .prd03_contract import run_acceptance as run_prd03
from .prd04_contract import run_acceptance as run_prd04


def run_acceptance() -> JsonValue:
    prd01 = run_prd01()
    prd02 = run_prd02()
    prd03 = run_prd03()
    prd04 = run_prd04()
    checks = {"prd01": prd01["state"] == "pass",
        "prd02": prd02["state"] == "pass",
        "prd03": prd03["state"] == "pass",
        "prd04": prd04["state"] == "pass",
        "immutable_holdout_mutations": prd04["mutation_count"] == 10
            and all(value == "killed" for value in prd04["mutations"].values())}
    state = "pass" if all(checks.values()) else "fail"
    reports: JsonValue = {"prd01": prd01["report_hash"],
        "prd02": prd02["report_hash"], "prd03": prd03["report_hash"],
        "prd04": prd04["report_hash"]}
    counts: JsonValue = {"prd_count": 4,
        "check_count": sum(item["check_count"]
            for item in (prd01, prd02, prd03, prd04)),
        "mutation_count": sum(item["mutation_count"]
            for item in (prd01, prd02, prd03, prd04))}
    body: JsonValue = {"schema_version": "v14.acceptance.1", "state": state,
        "checks": {key: value for key, value in checks.items()},
        "counts": counts, "reports": reports}
    return {**body, "report_hash": canonical_hash(body)}
