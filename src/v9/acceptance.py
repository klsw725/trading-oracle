from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.v4.models import JsonValue
from .accessibility_contract import (
    AccessibilityResponsiveViewModel,
    parse_accessibility,
)
from .contract import V9ContractError
from .fixture import load_fixture
from .input_contract import (
    DashboardQueryRequest,
    DashboardQueryResult,
    VersionAccept,
    negotiate_version,
    parse_query,
)
from .probes import PROBES, Probe, mutate_fixture
from .replay_contract import ReplayViewModel, parse_replay
from .risk_contract import (
    RiskHealthViewModel,
    parse_risk,
    verify_acknowledgement_projection,
)
from .rollout_contract import RolloutObservabilityViewModel, parse_rollout
from .spec import run_document_probes, verify_documents


@dataclass(frozen=True, slots=True)
class VerifiedFixture:
    query: DashboardQueryResult
    replay: ReplayViewModel
    risk: RiskHealthViewModel
    accessibility: AccessibilityResponsiveViewModel
    rollout: RolloutObservabilityViewModel


def _record(value: JsonValue, field: str) -> Mapping[str, JsonValue]:
    match value:  # noqa: MATCH_OK - fixture boundary requires an object
        case dict() as record:
            return record
        case _:
            raise V9ContractError("malformed_fixture", field)


def _forbidden(value: JsonValue) -> None:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            if "raw_ip" in record:
                raise V9ContractError("privacy_boundary_violation", "raw_ip")
            forbidden = {
                "access_token",
                "account_id",
                "account_number",
                "client_secret",
                "oauth_token",
                "raw_config",
            }.intersection(record)
            if forbidden:
                raise V9ContractError("adapter_boundary_violation", min(forbidden))
            for item in record.values():
                _forbidden(item)
        case list() as items:
            for item in items:
                _forbidden(item)
        case None | bool() | int() | float() | str():
            return


def verify_fixture(value: JsonValue) -> VerifiedFixture:
    root = _record(value, "root")
    if root.get("schema_name") != "v9.dashboard_read_contract.fixture":
        raise V9ContractError("malformed_fixture", "schema_name")
    _forbidden(value)
    query = parse_query(root.get("query_result"))
    replay = parse_replay(root.get("replay_view_model"))
    risk = parse_risk(root.get("risk_view_model"))
    accessibility = parse_accessibility(root.get("accessibility_view_model"))
    rollout = parse_rollout(root.get("rollout_view_model"))
    selected = replay.selected_recommendation.subject_id
    if len(query.items) != 1 or query.items[0].identity.subject_id != selected:
        raise V9ContractError("malformed_replay_view_model", "selected identity mismatch")
    if not any(item.subject_id == selected for item in risk.risk_inbox):
        raise V9ContractError("malformed_risk_health_view_model", "selected risk subject")
    expected_contracts = {
        "dashboard.query_result.1.0.0",
        "dashboard.replay_view_model.1.0.0",
        "dashboard.risk_health_view_model.1.0.0",
        "dashboard.accessibility_responsive_view_model.1.0.0",
    }
    if not set(accessibility.source_contracts).issubset(expected_contracts):
        raise V9ContractError("malformed_accessibility_view_model", "source contract")
    if set(rollout.source_contracts) != expected_contracts:
        raise V9ContractError("malformed_rollout_observability_view_model", "source contract")
    return VerifiedFixture(query, replay, risk, accessibility, rollout)


def _run_special_probe(probe: Probe, fixture: VerifiedFixture) -> None:
    match probe.mode:
        case "version":
            request = DashboardQueryRequest(
                accept=VersionAccept(envelope_versions=(), payload_versions={}),
                payload_type="recommendation.summary.v1",
                limit=10,
            )
            _ = negotiate_version(request)
        case "acknowledgement":
            changed_summary = fixture.risk.summary.model_copy(
                update={"stale_source_count": 0}
            )
            changed = fixture.risk.model_copy(update={"summary": changed_summary})
            verify_acknowledgement_projection(fixture.risk, changed)
        case "patch":
            raise V9ContractError("probe_mode_invalid", probe.name)


def run_acceptance() -> JsonValue:
    try:
        linked_prd_count, json_block_count = verify_documents()
        source = load_fixture()
        fixture = verify_fixture(source)
    except V9ContractError as error:
        return {"state": "fail", "error_code": error.code, "detail": str(error)}
    document_probes = run_document_probes()
    document_results = _record(document_probes, "document_probes")
    probe_results: dict[str, JsonValue] = {}
    accepted: list[bool] = [
        isinstance(result, dict) and result.get("state") == "pass"
        for result in document_results.values()
    ]
    for probe in PROBES:
        observed: str | None = None
        try:
            if probe.mode == "patch":
                _ = verify_fixture(mutate_fixture(source, probe))
            else:
                _run_special_probe(probe, fixture)
        except V9ContractError as error:
            observed = error.code
        passed = observed == probe.expected_error_code
        accepted.append(passed)
        probe_results[probe.name] = {
            "state": "pass" if passed else "fail",
            "expected_error_code": probe.expected_error_code,
            "observed_error_code": observed,
        }
    checks: dict[str, JsonValue] = {
        "document_contract": True,
        "input_contract": True,
        "replay_contract": True,
        "risk_contract": True,
        "accessibility_declarations": True,
        "rollout_observation": True,
        "cross_surface_identity": True,
        "privacy_and_adapter_boundary": True,
    }
    return {
        "state": "pass" if all(accepted) else "fail",
        "schema_version": "v9.dashboard.contract_acceptance.1",
        "check_count": len(checks),
        "checks": checks,
        "json_block_count": json_block_count,
        "linked_prd_count": linked_prd_count,
        "probe_count": len(document_results) + len(PROBES),
        "document_probes": document_probes,
        "probes": probe_results,
    }
