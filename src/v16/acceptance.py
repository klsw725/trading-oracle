from __future__ import annotations

from pathlib import Path

from .acceptance_boundary import (BoundaryBaseline, boundary_results, capture_baseline,
                                  cli_checks)
from .acceptance_config import config_checks, config_mutations
from .acceptance_health import (base_bundle, calendar_checks, hash_binding_checks,
                                health_edge_checks, health_mutations, healthy_checks,
                                isolation_checks, unhealthy_bundle_check)
from .boundaries import BoundaryObserver, observe_boundaries
from .canonical import JsonValue, canonical_hash
from .errors import AcceptanceError
from .fixtures import verify_inventory
from .paths import project_root
from .registries import BOUNDARY_IDS, CHECK_IDS, MUTATION_IDS, PRD_ITEMS
from .reporting import EvidenceItem, acceptance_report, item, line


def _build_report(root: Path, observer: BoundaryObserver, baseline: BoundaryBaseline,
                  deterministic_expected: str, deterministic_actual: str) -> JsonValue:
    bundle = base_bundle(root)
    checks = healthy_checks(bundle)
    checks.extend(unhealthy_bundle_check(root))
    checks.extend(config_checks(root, bundle.identity.config_hash))
    checks.extend(calendar_checks(root))
    checks.extend(isolation_checks(root))
    checks.extend(hash_binding_checks(root))
    checks.extend(health_edge_checks(root))
    checks.extend(cli_checks())
    checks.append(item("fixture_inventory", baseline.inventory_hash, verify_inventory(root)))
    mutations = config_mutations(root, bundle.manifest_hash)
    mutations.extend(health_mutations(root))
    boundaries, boundary_mutations = boundary_results(root, observer, baseline)
    mutations.extend(boundary_mutations)
    mutations.append(item("report_nondeterminism", deterministic_expected,
                          deterministic_actual))
    return acceptance_report(bundle.identity.runtime_identity, checks, mutations, boundaries)


def _run_observed(observer: BoundaryObserver) -> JsonValue:
    root = project_root()
    baseline = capture_baseline(root)
    first = _build_report(root, observer, baseline, "PROBE", "PROBE")
    second = _build_report(root, observer, baseline, "PROBE", "PROBE")
    actual = "BYTE_IDENTICAL" if line(first) == line(second) else "DIFFERENT"
    return _build_report(root, observer, baseline, "BYTE_IDENTICAL", actual)


def _validate_prd_registry() -> None:
    assigned = tuple(item_id for values in PRD_ITEMS.values() for item_id in values)
    required = (*CHECK_IDS, *MUTATION_IDS, *BOUNDARY_IDS)
    if len(set(assigned)) != len(assigned) or set(assigned) != set(required):
        raise AcceptanceError("PRD registry mismatch")


def run_acceptance(observer: BoundaryObserver | None = None) -> JsonValue:
    _validate_prd_registry()
    if observer is not None:
        try:
            return _run_observed(observer)
        finally:
            observer.disable()
    scoped = observe_boundaries(project_root())
    try:
        return _run_observed(scoped)
    finally:
        scoped.disable()


def _evidence(report: JsonValue) -> tuple[EvidenceItem, ...]:
    if not isinstance(report, dict):
        return ()
    values: list[EvidenceItem] = []
    for section in ("checks", "mutations", "boundaries"):
        found = report.get(section)
        if isinstance(found, list):
            for value in found:
                if isinstance(value, dict):
                    values.append(value)
    return tuple(values)


def prd_acceptance(prd: int, observer: BoundaryObserver | None = None) -> JsonValue:
    report = run_acceptance(observer)
    requested = PRD_ITEMS[prd]
    indexed = {str(value.get("id")): value for value in _evidence(report)}
    selected = [indexed[item_id] for item_id in requested]
    status = "PASS" if all(value.get("status") == "PASS" for value in selected) else "FAIL"
    evidence: list[JsonValue] = [value for value in selected]
    body: dict[str, JsonValue] = {"evidence": evidence, "prd": prd,
                       "schema_version": f"v16.prd0{prd}.acceptance.1", "status": status}
    return {**body, "report_hash": canonical_hash(body)}
