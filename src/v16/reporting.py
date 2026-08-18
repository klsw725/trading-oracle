from __future__ import annotations

from .canonical import JsonValue, canonical_hash, canonical_json
from .errors import AcceptanceError
from .registries import BOUNDARY_IDS, CHECK_IDS, MUTATION_IDS


type EvidenceItem = dict[str, JsonValue]


def item(item_id: str, expected: str, actual: str) -> EvidenceItem:
    body: JsonValue = {"actual": actual, "expected": expected, "id": item_id,
                       "status": "PASS" if actual == expected else "FAIL"}
    return {**body, "evidence_hash": canonical_hash(body)}


def _ordered(values: list[EvidenceItem], expected: tuple[str, ...], label: str) -> list[EvidenceItem]:
    ids = tuple(str(value.get("id")) for value in values)
    if len(set(ids)) != len(ids) or set(ids) != set(expected):
        raise AcceptanceError(f"{label} registry mismatch")
    if any(value.get("status") == "SKIP" for value in values):
        raise AcceptanceError(f"{label} contains skip")
    return sorted(values, key=lambda value: str(value["id"]))


def acceptance_report(runtime_identity: str, checks: list[EvidenceItem],
                      mutations: list[EvidenceItem], boundaries: list[EvidenceItem]) -> JsonValue:
    ordered_checks = _ordered(checks, CHECK_IDS, "checks")
    ordered_mutations = _ordered(mutations, MUTATION_IDS, "mutations")
    ordered_boundaries = _ordered(boundaries, BOUNDARY_IDS, "boundaries")
    all_items = (*ordered_checks, *ordered_mutations, *ordered_boundaries)
    status = "PASS" if all(value["status"] == "PASS" for value in all_items) else "FAIL"
    body: dict[str, JsonValue] = {
        "boundaries": [value for value in ordered_boundaries],
        "checks": [value for value in ordered_checks],
        "mutations": [value for value in ordered_mutations],
        "runtime_identity": runtime_identity, "schema_version": "v16.acceptance.1",
        "status": status, "version": "v16",
    }
    return {**body, "report_hash": canonical_hash(body)}


def line(value: JsonValue) -> bytes:
    return canonical_json(value) + b"\n"
