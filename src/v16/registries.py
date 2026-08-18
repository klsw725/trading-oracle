from __future__ import annotations

from typing import Final


CONFIG_SCHEMAS: Final = frozenset({"v16.runtime-config.1"})
POLICIES: Final = frozenset({"v16.policy.1"})
DATASET_KINDS: Final = frozenset({"minute-bars"})
SOURCES: Final = frozenset({("fixture", "1")})
FIXTURE_FILES: Final = (
    "calendar-kr.json", "calendar-us.json", "dataset-kr.json", "dataset-us.json",
    "input-manifest.json", "mutation-source.json", "runtime-config.yaml",
)
MUTATION_IDS: Final = (
    "calendar_conflict", "config_escape", "cosmetic_config_change",
    "cwd_independence", "data_hash_forgery", "later_version_import",
    "market_currency_swap", "network_attempt", "portfolio_mutation",
    "report_nondeterminism", "semantic_config_change", "stale_at_replay_cutoff",
    "unknown_config_policy", "unknown_source_kind",
)
CHECK_IDS: Final = (
    "all_market_detail_preserved", "bundle_build", "bundle_unhealthy_rejected",
    "calendar_closed_date_rejected",
    "calendar_closed_session_rejected",
    "calendar_dst_ambiguity_rejected", "config_identity",
    "config_market_identity_rejected", "data_duplicate_rejected",
    "data_future_rejected", "data_kr_symbol_syntax_rejected",
    "data_missing_interval_rejected", "data_per_symbol_grid_rejected",
    "data_observed_after_as_of_rejected", "data_order_rejected",
    "data_outside_session_rejected", "data_required_symbol_rejected",
    "fixture_inventory", "health_input_hash_binding", "kr_health",
    "market_scope_isolation", "prd03_cli_internal",
    "prd03_acceptance_failure", "prd03_all_command_success",
    "prd03_cli_success", "prd03_cli_usage", "prd03_typed_failure", "us_health",
    "yaml_bool_integer_rejected", "yaml_duplicate_rejected",
    "yaml_non_finite_rejected", "yaml_tag_rejected",
)
BOUNDARY_IDS: Final = (
    "fixture_bytes_unchanged", "forbidden_inputs", "network_calls",
    "portfolio_bytes", "tracked_files_unchanged", "v17_plus_imports",
)
PRD_ITEMS: Final = {
    1: ("bundle_build", "bundle_unhealthy_rejected", "config_identity",
        "config_market_identity_rejected", "yaml_bool_integer_rejected",
        "yaml_duplicate_rejected", "yaml_non_finite_rejected", "yaml_tag_rejected",
        "cwd_independence", "config_escape", "cosmetic_config_change",
        "semantic_config_change", "unknown_config_policy"),
    2: ("all_market_detail_preserved", "calendar_closed_date_rejected",
        "calendar_closed_session_rejected", "calendar_dst_ambiguity_rejected",
        "data_duplicate_rejected", "data_future_rejected",
        "data_kr_symbol_syntax_rejected", "data_missing_interval_rejected",
        "data_observed_after_as_of_rejected", "data_order_rejected",
        "data_outside_session_rejected", "data_per_symbol_grid_rejected",
        "data_required_symbol_rejected", "health_input_hash_binding", "kr_health",
        "market_scope_isolation", "us_health", "calendar_conflict",
        "data_hash_forgery", "market_currency_swap", "stale_at_replay_cutoff",
        "unknown_source_kind"),
    3: ("prd03_acceptance_failure", "prd03_all_command_success",
        "prd03_cli_internal", "prd03_cli_success", "prd03_cli_usage",
        "prd03_typed_failure", "report_nondeterminism"),
    4: ("fixture_inventory", "forbidden_inputs", "fixture_bytes_unchanged",
        "network_calls", "portfolio_bytes", "tracked_files_unchanged",
        "v17_plus_imports", "network_attempt", "later_version_import",
        "portfolio_mutation"),
}
FORBIDDEN_INPUT_TOKENS: Final = (
    "access_token", "broker", "client_id", "client_secret", "credential",
    "live_destination", "oauth_token", "order_destination",
)
