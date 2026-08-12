from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from src.v4.models import JsonValue
from src.v9.contract import V9ContractError


type PathPart = str | int
type ProbeMode = Literal["patch", "version", "acknowledgement"]


@dataclass(frozen=True, slots=True)
class Patch:
    path: tuple[PathPart, ...]
    value: JsonValue = None
    delete: bool = False


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    expected_error_code: str
    patches: tuple[Patch, ...] = ()
    mode: ProbeMode = "patch"


def _apply_patch(root: JsonValue, patch: Patch) -> None:
    current = root
    for part in patch.path[:-1]:
        match current, part:  # noqa: MATCH_OK - invalid probe paths are typed errors
            case dict() as record, str() as key:
                current = record[key]
            case list() as items, int() as index:
                current = items[index]
            case _:
                raise V9ContractError("probe_path_invalid", str(patch.path))
    last = patch.path[-1]
    match current, last:  # noqa: MATCH_OK - invalid probe paths are typed errors
        case dict() as record, str() as key:
            if patch.delete:
                del record[key]
            else:
                record[key] = patch.value
        case list() as items, int() as index:
            if patch.delete:
                del items[index]
            else:
                items[index] = patch.value
        case _:
            raise V9ContractError("probe_path_invalid", str(patch.path))


def mutate_fixture(root: JsonValue, probe: Probe) -> JsonValue:
    mutated = deepcopy(root)
    for patch in probe.patches:
        _apply_patch(mutated, patch)
    return mutated


PROBES = (
    Probe("input.schema", "malformed_envelope", (Patch(("query_result", "items", 0, "event_id"), delete=True),)),
    Probe("input.pagination", "malformed_query", (Patch(("query_result", "pagination", "limit"), 0),)),
    Probe("input.version", "missing_version_accept", mode="version"),
    Probe("input.stale", "stale_mislabeled_fresh", (Patch(("query_result", "items", 0, "freshness", "age_seconds"), 1900),)),
    Probe("input.dirty", "adapter_boundary_violation", (Patch(("query_result", "items", 0, "payload", "raw_config"), "secret"),)),
    Probe("input.misleading", "misleading_summary", (Patch(("query_result", "summary", "fresh_count"), 0),)),
    Probe("input.malformed", "malformed_envelope", (Patch(("query_result", "items", 0, "payload_type"), delete=True),)),
    Probe("replay.stale", "stale_mislabeled_fresh", (Patch(("query_result", "items", 0, "freshness", "age_seconds"), 1900),)),
    Probe("replay.dirty", "adapter_boundary_violation", (Patch(("replay_view_model", "raw_config"), "secret"),)),
    Probe("replay.misleading", "misleading_outcome", (Patch(("replay_view_model", "outcome_summary", "condition"), "missing"),)),
    Probe("replay.malformed", "malformed_replay_view_model", (Patch(("replay_view_model", "selected_recommendation", "subject_id"), delete=True),)),
    Probe("replay.broken_link", "broken_drilldown_link", (Patch(("replay_view_model", "drilldown_links", 0, "target_id"), None),)),
    Probe("risk.stale", "stale_health_falsely_normal", (Patch(("risk_view_model", "source_health", 0, "health_label"), "healthy"),)),
    Probe("risk.dirty", "adapter_boundary_violation", (Patch(("risk_view_model", "account_id"), "forbidden"),)),
    Probe("risk.misleading", "misleading_risk_summary", (Patch(("risk_view_model", "summary", "open_risk_count"), 0),)),
    Probe("risk.malformed", "malformed_risk_health_view_model", (Patch(("risk_view_model", "risk_inbox", 0, "severity"), "unknown"),)),
    Probe("risk.forbidden_mutation", "forbidden_surface_mutation", mode="acknowledgement"),
    Probe("accessibility.keyboard", "keyboard_path_broken", (Patch(("accessibility_view_model", "keyboard", "skip_links"), []),)),
    Probe("accessibility.focus", "focus_return_missing", (Patch(("accessibility_view_model", "keyboard", "escape_returns_to"), "missing_opener"),)),
    Probe("accessibility.contrast", "color_only_state", (Patch(("accessibility_view_model", "color_only_states"), ["stale"]),)),
    Probe("accessibility.screen_reader", "semantic_state_missing", (Patch(("accessibility_view_model", "semantics", "row_accessible_names"), []),)),
    Probe("accessibility.responsive", "responsive_priority_violation", (Patch(("accessibility_view_model", "responsive_visibility", "visible_priorities"), [2]),)),
    Probe("accessibility.localization", "localization_misleading", (Patch(("accessibility_view_model", "localization", "missing_values", 0, "display"), "0원"),)),
    Probe("accessibility.partial", "misleading_partial_data", (Patch(("accessibility_view_model", "semantics", "partial_caveat_announced"), False),)),
    Probe("accessibility.error_recovery", "unsafe_recovery", (Patch(("accessibility_view_model", "conditions", "error"), True), Patch(("accessibility_view_model", "recovery_actions"), []))),
    Probe("accessibility.reduced_motion", "motion_required_for_meaning", (Patch(("accessibility_view_model", "motion_required_for_meaning"), True),)),
    Probe("accessibility.dirty", "adapter_boundary_violation", (Patch(("accessibility_view_model", "raw_config"), "secret"),)),
    Probe("accessibility.malformed", "malformed_accessibility_view_model", (Patch(("accessibility_view_model", "breakpoint"), "unknown"),)),
    Probe("rollout.json", "malformed_rollout_observability_view_model", (Patch(("rollout_view_model", "schema_name"), delete=True),)),
    Probe("rollout.threshold", "error_rate_rollback_required", (Patch(("rollout_view_model", "slo_summary", "typed_error_rate"), "3.20"),)),
    Probe("rollout.stale", "stale_false_normal_blocks_promotion", (Patch(("rollout_view_model", "slo_summary", "stale_false_normal_count"), 1),)),
    Probe("rollout.privacy", "privacy_boundary_violation", (Patch(("rollout_view_model", "raw_ip"), "127.0.0.1"),)),
    Probe("rollout.interruption", "interrupted_journey_counted_success", (Patch(("rollout_view_model", "interrupted_journey_counted_success"), True),)),
    Probe("rollout.fallback", "silent_fallback", (Patch(("rollout_view_model", "fallback", "active"), True),)),
    Probe("rollout.deprecation", "unsafe_deprecation_cutoff", (Patch(("rollout_view_model", "deprecation", "cutoff_active"), True), Patch(("rollout_view_model", "deprecation", "replacement_critical_incident"), True))),
)
