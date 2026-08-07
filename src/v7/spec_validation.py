from collections.abc import Callable, Mapping
from typing import Final

from src.v4.models import JsonValue

from .spec_json import parse_json_fences
from .spec_models import PrdDocument, SpecContract, SpecErrorCode, SpecVerificationError


_PRDS: Final = ("PRD 01", "PRD 02", "PRD 03", "PRD 04")
_LINKS: Final = (
    "prds/prd01-source-adapter-provenance.md",
    "prds/prd02-quality-freshness-dedup.md",
    "prds/prd03-incremental-value-evaluation.md",
    "prds/prd04-promotion-retirement.md",
)
_STATES: Final = ("candidate", "shadow", "canary", "limited", "primary", "disabled", "retiring", "retired", "expired")
_MUTATIONS: Final = (
    "prd_row_missing", "prd_link_duplicate", "bidirectional_gap", "state_jump",
    "quality_count_misuse", "source_addition_success", "latency_only_success",
    "harmful_source_current", "stale_cache_current", "policy_hash_mismatch",
)
_SCHEMAS: Final = (
    "v7.source_adapter_provenance.prd01.1",
    "v7.quality_freshness_dedup.prd02.1",
    "v7.incremental_value_evaluation.prd03.1",
    "v7.promotion_retirement.prd04.1",
)
_PRD_FIELDS: Final = (
    frozenset(("contract_id", "required_fields", "hash_rules", "happy_trace_fixture", "failure_fixtures", "required_probes")),
    frozenset(("contract_id", "score_components", "freshness_sla_hours", "audit_ttl_hours", "happy_duplicate_cluster_fixture", "failure_fixtures", "required_mutations")),
    frozenset(("contract_id", "thresholds", "happy_filing_lift_fixture", "failure_fixtures", "required_mutations")),
    frozenset(("contract_id", "state_order", "traffic_steps", "happy_gradual_promotion_fixture", "failure_immediate_disable_fixture", "failure_fixtures", "required_mutations")),
)
_PRD01_REQUIRED: Final = (
    "adapter_id", "adapter_version", "source_identity", "auth_boundary", "market_coverage",
    "fetch_started_at", "fetched_at", "as_of", "freshness_status", "license", "retention",
    "normalized_record", "raw_payload_hash", "normalized_record_hash", "provenance_hash",
    "capabilities", "redaction_report", "error_envelope",
)


def _record(value: JsonValue) -> Mapping[str, JsonValue] | None:
    return value if isinstance(value, dict) else None


def _prd01_values(record: Mapping[str, JsonValue]) -> None:
    if record.get("required_fields") != list(_PRD01_REQUIRED):
        raise SpecVerificationError("V7_SPEC_MALFORMED", "PRD 01 required fields")


def _prd02_values(record: Mapping[str, JsonValue]) -> None:
    if record.get("score_components") != {
        "freshness_fit": 20, "source_reliability": 20, "factuality_support": 25,
        "contradiction_risk": 20, "dedup_integrity": 10, "prompt_safety": 5,
    }:
        raise SpecVerificationError("V7_SPEC_MALFORMED", "PRD 02 score components")
    if record.get("freshness_sla_hours") != {
        "market_price": 0.5, "fundamental_equity": 168, "news_search": 168,
        "web_context": 168, "macro_timeseries_daily": 24, "macro_timeseries_monthly": 720,
    }:
        raise SpecVerificationError("V7_SPEC_MALFORMED", "PRD 02 freshness defaults")


def _prd03_values(record: Mapping[str, JsonValue]) -> None:
    if record.get("thresholds") != {
        "success_threshold_5": "0.01", "verdict_lift_lower_90_min": "0.003",
        "correction_precision_min": "0.80", "correction_recall_min": "0.25",
        "coverage_rate_min": "0.75", "p95_added_wall_ms_max": 2500,
        "harm_rate_max": "0.20", "severe_harm_rate_max": "0.05",
    }:
        raise SpecVerificationError("V7_SPEC_MALFORMED", "PRD 03 thresholds")


def _prd04_values(record: Mapping[str, JsonValue]) -> None:
    if record.get("state_order") != list(_STATES):
        raise SpecVerificationError("V7_SPEC_MALFORMED", "PRD 04 state order")
    if record.get("traffic_steps") != {
        "shadow_check": "0.00", "canary_5": "0.05", "limited_25": "0.25",
        "limited_50": "0.50", "primary_100": "1.00",
    }:
        raise SpecVerificationError("ILLEGAL_PROMOTION_JUMP", "PRD 04 traffic shares")


_PRD_VALUE_VALIDATORS: Final[tuple[Callable[[Mapping[str, JsonValue]], None], ...]] = (
    _prd01_values, _prd02_values, _prd03_values, _prd04_values,
)


def validate_prd_contracts(prds: tuple[PrdDocument, ...]) -> int:
    total = 0
    for index, document in enumerate(prds):
        if document.text.count("](../SPEC.md)") != 1:
            raise SpecVerificationError("V7_PRD_LINK_BROKEN", f"{document.prd_id} parent SPEC backlink")
        blocks = parse_json_fences(document.text)
        total += len(blocks)
        matches = tuple(
            record for value in blocks
            if (record := _record(value)) is not None and record.get("schema_version") == _SCHEMAS[index]
        )
        if len(matches) != 1 or not _PRD_FIELDS[index].issubset(matches[0]):
            raise SpecVerificationError("V7_SPEC_MALFORMED", f"{document.prd_id} contract fields")
        _PRD_VALUE_VALIDATORS[index](matches[0])
    return total


def validate_contract(contract: SpecContract) -> None:
    if contract.schema_version != "v7.information_source_expansion.spec.1" or contract.contract_id != "information_source_expansion_spec_v7":
        raise SpecVerificationError("V7_SPEC_MALFORMED", "SPEC identity")
    if contract.flow != ("onboarding", "quality", "evaluation", "lifecycle"):
        raise SpecVerificationError("V7_SPEC_MALFORMED", "end-to-end flow")
    if contract.required_prds != _PRDS:
        raise SpecVerificationError("V7_PRD_ROW_MISSING", "required PRD inventory")
    if contract.local_prd_links != _LINKS:
        raise SpecVerificationError("V7_PRD_LINK_MISSING", "local PRD link inventory")
    if contract.states != _STATES:
        raise SpecVerificationError("V7_SPEC_MALFORMED", "state inventory")
    if contract.required_mutations != _MUTATIONS:
        raise SpecVerificationError("V7_SPEC_MALFORMED", "required mutation inventory")
    happy = contract.happy_promotion_fixture
    happy_values = (happy.source_bundle_id, happy.provenance_gate, happy.quality_gate, happy.value_gate, happy.traffic_path, happy.final_state, happy.expected_code)
    if happy_values != ("filing_source_bundle_v1", "pass", "fresh_high", "PASS_INCREMENTAL_VALUE_EVALUATION", ("0.00", "0.05", "0.25", "0.50", "1.00"), "primary", "PROMOTION_ACCEPTED_GRADUAL"):
        raise SpecVerificationError("ILLEGAL_PROMOTION_JUMP", "happy promotion fixture")
    harmful = contract.harmful_retirement_fixture
    harmful_values = (harmful.source_bundle_id, harmful.incident_code, harmful.previous_state, harmful.previous_traffic_share, harmful.disable_state, harmful.disable_traffic_share, harmful.retirement_reason, harmful.final_state, harmful.fallback_removed, harmful.current_cache_allowed, harmful.expected_code)
    if harmful_values != ("web_context_bundle_v1", "severe_harm_breach", "limited", "0.25", "disabled", "0.00", "harmful", "retired", True, False, "SOURCE_RETIRED_HARMFUL"):
        raise SpecVerificationError("FALLBACK_USES_INELIGIBLE_SOURCE", "harmful retirement fixture")
    thresholds = contract.success_thresholds
    observed = (thresholds.quality_min_label, thresholds.coverage_rate_min, thresholds.target_coverage_rate_min, thresholds.p95_added_wall_ms_max, thresholds.mean_added_wall_ms_max, thresholds.added_prompt_tokens_per_ticker_max, thresholds.timeout_rate_max, thresholds.harm_rate_max, thresholds.severe_harm_rate_max)
    if observed != ("usable", "0.75", "0.80", 2500, 900, 1500, "0.02", "0.20", "0.05"):
        raise SpecVerificationError("V7_SPEC_MALFORMED", "success thresholds")


def validate_narrative(text: str) -> None:
    state_diagram = """```text
candidate -> shadow -> canary -> limited -> primary
candidate -> expired
shadow -> disabled
canary -> disabled
limited -> disabled
primary -> disabled
primary -> expired
primary -> retiring -> retired
disabled -> retiring -> retired
expired -> retired
```"""
    if state_diagram not in text:
        raise SpecVerificationError("ILLEGAL_PROMOTION_JUMP", "state diagram")
    checks: tuple[tuple[str, SpecErrorCode], ...] = (
        ("Count is not quality.", "COUNT_USED_AS_QUALITY"),
        ("Source addition, high result count, low latency alone, or manual preference is not success.", "REJECT_NO_INCREMENTAL_VALUE"),
        ("A cheaper or faster source still fails when factual correction and verdict lift do not pass.", "REJECT_LATENCY_ONLY"),
        ("keeps disabled fallback", "FALLBACK_USES_INELIGIBLE_SOURCE"),
        ("counts stale cache as fresh", "STALE_CACHE_POLICY_MISMATCH"),
        ("matching policy hash", "POLICY_HASH_MISMATCH"),
    )
    for marker, code in checks:
        if marker not in text:
            raise SpecVerificationError(code, f"missing normative marker: {marker}")
    defaults = (
        "PRD 02 freshness SLA is the single source of truth for PRD 01 stale validation.",
        "One added fetch per ticker is the maximum default PRD 03 fetch budget.",
        "Canary prompt traffic is exactly `0.05`.",
        "Every promotion observation window contains at least 100 attempts.",
        "Fallback ties are resolved by ascending `source_bundle_id` after all documented ranking keys.",
        "Contract expiry takes precedence over voluntary retirement when both apply.",
        "A missing outcome adapter produces `INCONCLUSIVE_MISSING_OUTCOME_ADAPTER` and cannot pass the PRD 04 value gate.",
        "each promotion step requires at least 100 observed attempts",
        "`canary` at exactly `0.05`",
    )
    if any(marker not in text for marker in defaults):
        raise SpecVerificationError("V7_SPEC_MALFORMED", "implementation defaults")
