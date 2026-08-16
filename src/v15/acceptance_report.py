from __future__ import annotations

from typing import Literal

from src.v11.canonical import canonical_hash
from src.v4.models import JsonValue


type MutationState = Literal["killed", "survived"]
type JsonRecord = dict[str, JsonValue]


def report(
    schema_version: str,
    checks: dict[str, bool],
    mutations: dict[str, MutationState],
    hashes: dict[str, str],
) -> JsonRecord:
    state: Literal["pass", "fail"] = "pass" if all(checks.values()) \
        and all(value == "killed" for value in mutations.values()) else "fail"
    body: JsonRecord = {"schema_version": schema_version, "state": state,
        "check_count": len(checks), "mutation_count": len(mutations),
        "checks": {key: value for key, value in checks.items()},
        "mutations": {key: value for key, value in mutations.items()},
        "hashes": {key: value for key, value in hashes.items()}}
    return {**body, "report_hash": canonical_hash(body)}
