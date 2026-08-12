from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from src.v4.models import JsonValue
from src.v9.contract import StrictModel, V9ContractError, ViewId


class Keyboard(StrictModel):
    skip_links: tuple[str, ...]
    tab_order: tuple[str, ...]
    escape_returns_to: str


class Focus(StrictModel):
    current_focus_id: str
    visible_indicator_required: bool
    opener_id: str


class Semantics(StrictModel):
    active_landmarks: tuple[str, ...]
    live_region_politeness: tuple[Literal["polite", "assertive"], ...]
    row_accessible_names: tuple[str, ...]
    partial_caveat_announced: bool


class ResponsiveVisibility(StrictModel):
    visible_priorities: tuple[int, ...]
    summarized_priorities: tuple[int, ...]
    collapsed_priorities: tuple[int, ...]
    horizontal_scroll_allowed_for: tuple[str, ...]


class MissingValue(StrictModel):
    field: str
    display: str
    reason: str | None
    must_not_display_as_zero: bool


class CurrencyDisplay(StrictModel):
    field: str
    numeric_value: int | float
    currency: Literal["KRW", "USD"]
    display: str
    approximate_krw: int | None = None
    exchange_rate: float | None = None


class Localization(StrictModel):
    numbering_system: str
    currency_displays: tuple[CurrencyDisplay, ...]
    missing_values: tuple[MissingValue, ...]


class RecoveryAction(StrictModel):
    id: str
    label: str
    safe_effect: Literal[
        "read_detail",
        "navigate_back",
        "reset_filters",
        "open_source_health",
        "show_typed_value",
    ]
    enabled: bool


class AccessibilityConditions(StrictModel):
    loading: bool
    empty: bool
    partial: bool
    error: bool
    reduced_motion: bool


class AccessibilityResponsiveViewModel(StrictModel):
    schema_name: Literal["dashboard.accessibility_responsive_view_model"]
    schema_version: Literal["1.0.0"]
    source_contracts: tuple[str, ...]
    view_id: ViewId
    locale: str
    breakpoint: Literal["compact", "phone", "tablet", "desktop", "wide"]
    wcag_target: Literal["WCAG_2_2_AA"]
    information_priority: tuple[str, ...]
    keyboard: Keyboard
    focus: Focus
    semantics: Semantics
    responsive_visibility: ResponsiveVisibility
    conditions: AccessibilityConditions
    localization: Localization
    recovery_actions: tuple[RecoveryAction, ...]
    motion_required_for_meaning: bool
    color_only_states: tuple[str, ...]


_PRIORITY = (
    "blocking_error",
    "selected_identity",
    "freshness_quality_risk_caveat",
    "decision_summary",
    "source_outcome_recovery",
    "secondary_metrics",
)


def parse_accessibility(value: JsonValue) -> AccessibilityResponsiveViewModel:
    try:
        accessibility = AccessibilityResponsiveViewModel.model_validate(value)
    except ValidationError as error:
        raise V9ContractError("malformed_accessibility_view_model", str(error)) from error
    if accessibility.information_priority != _PRIORITY:
        raise V9ContractError("responsive_priority_violation", "priority order")
    if not {1, 2, 3}.issubset(accessibility.responsive_visibility.visible_priorities):
        raise V9ContractError("responsive_priority_violation", "priority 1 to 3 hidden")
    if not accessibility.keyboard.skip_links:
        raise V9ContractError("keyboard_path_broken", "skip link missing")
    if not accessibility.semantics.row_accessible_names:
        raise V9ContractError("semantic_state_missing", "row accessible name missing")
    if accessibility.keyboard.escape_returns_to != accessibility.focus.opener_id:
        raise V9ContractError("focus_return_missing", "Escape opener mismatch")
    required_tab_targets = {
        "global_status",
        accessibility.focus.opener_id,
        "recommendation_detail_heading",
        "return_to_list",
    }
    if not required_tab_targets.issubset(accessibility.keyboard.tab_order):
        raise V9ContractError("keyboard_path_broken", "required tab target missing")
    if accessibility.conditions.partial and not accessibility.semantics.partial_caveat_announced:
        raise V9ContractError("misleading_partial_data", "partial caveat hidden")
    if accessibility.conditions.error and not accessibility.recovery_actions:
        raise V9ContractError("unsafe_recovery", "error recovery missing")
    for missing in accessibility.localization.missing_values:
        if missing.reason is None or not missing.must_not_display_as_zero or missing.display in {"0", "0원"}:
            raise V9ContractError("localization_misleading", missing.field)
    if accessibility.motion_required_for_meaning:
        raise V9ContractError("motion_required_for_meaning", accessibility.view_id)
    if accessibility.color_only_states:
        raise V9ContractError("color_only_state", accessibility.color_only_states[0])
    return accessibility
