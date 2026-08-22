from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .acceptance_boundaries import (
    Baseline,
    capture_baseline,
    observer_self_test,
    verify_baseline,
)
from .acceptance_checks import run_checks
from .acceptance_mutations import run_mutations
from .boundaries import BoundaryCounts, counts, observe_boundaries
from .canonical import JsonValue, canonical_hash, canonical_json
from .fixtures import PRIMARY_RUNTIME_IDENTITY, verify_inventory
from .migrations import SCHEMA_HASH
from .schema import EVENT_SCHEMA_VERSION

MUTATION_IDS: Final = (
    "crash_after_event_insert", "cross_namespace_reference", "database_version_ahead",
    "duplicate_retry", "event_hash_forgery", "event_sequence_gap",
    "idempotency_payload_conflict", "json_recovery_attempt", "later_version_import",
    "market_currency_swap", "migration_hash_drift", "migration_partial_failure",
    "network_attempt", "portfolio_mutation", "projection_cash_drift",
    "projection_position_drift", "stale_runtime_identity", "unknown_event_policy",
)


@dataclass(frozen=True, slots=True)
class Material:
    checks: tuple[tuple[str, str], ...]
    mutations: tuple[tuple[str, str], ...]
    boundaries: tuple[tuple[str, str], ...]
    projection_hash: str


def _results(items: tuple[tuple[str, str], ...]) -> list[JsonValue]:
    return [{"id": identifier, "status": "PASS", "evidence_hash": canonical_hash(
        {"id": identifier, "actual": actual})} for identifier, actual in items]


def _material(baseline: Baseline) -> Material:
    _ = verify_inventory()
    with observe_boundaries():
        checks = run_checks()
        mutations = run_mutations(baseline.portfolio)
        observed = counts()
    if tuple(identifier for identifier, _ in mutations) != MUTATION_IDS:
        raise AssertionError("mutation registry mismatch")
    boundaries = _boundary_results(observed)
    projection = dict(checks)["all_event_types_commit"]
    return Material(checks, mutations, boundaries, projection)


def _boundary_results(observed: BoundaryCounts) -> tuple[tuple[str, str], ...]:
    boundaries = tuple(sorted({
        "broker_objects": str(observed.broker), "credential_objects": str(observed.credential),
        "fixture_bytes": "UNCHANGED", "later_imports": str(observed.later_import),
        "live_objects": str(observed.live), "network_calls": str(observed.network),
        "portfolio_bytes": "UNCHANGED", "tracked_worktree": "UNCHANGED",
    }.items()))
    if any(actual not in {"0", "UNCHANGED"} for _, actual in boundaries):
        raise AssertionError("boundary crossed")
    return boundaries


def _report(material: Material, checks: tuple[tuple[str, str], ...]) -> JsonValue:
    body: dict[str, JsonValue] = {
        "schema_version": "v17.acceptance.1", "version": "v17", "status": "PASS",
        "runtime_identity": PRIMARY_RUNTIME_IDENTITY, "migration_schema_hash": SCHEMA_HASH,
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "projection_hash": material.projection_hash, "checks": _results(checks),
        "mutations": _results(material.mutations), "boundaries": _results(material.boundaries),
    }
    return {**body, "report_hash": canonical_hash(body)}


def run_acceptance() -> JsonValue:
    observer_self_test()
    baseline = capture_baseline()
    first = _material(baseline)
    verify_baseline(baseline)
    second = _material(baseline)
    verify_baseline(baseline)
    if canonical_json(_material_value(first)) != canonical_json(_material_value(second)):
        raise AssertionError("acceptance material differs")
    checks = tuple(sorted((*first.checks, ("internal_byte_identical", "BYTE_IDENTICAL"))))
    return _report(first, checks)


def _material_value(material: Material) -> JsonValue:
    return {"checks": [list(item) for item in material.checks],
            "mutations": [list(item) for item in material.mutations],
            "boundaries": [list(item) for item in material.boundaries],
            "projection_hash": material.projection_hash}
