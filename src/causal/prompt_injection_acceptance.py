from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from src.v4.models import JsonValue, canonical_hash, canonical_json

from .prompt_injection_gate import rollback_prompt_package
from src.causal.prompt_acceptance_fixtures import (
    INT_VALUE,
    RECORD,
    RECORDS,
    Variant,
    copy_record,
    eligibilities,
    first_pair,
    mutate_pair_field,
    package_rejected,
    prompt_package,
    runtime_probe,
    source_fixture,
    variant_pair,
)
from .prompt_injection_models import PROMPT_CONFIG_ADAPTER, PROMPT_PACKAGE_ADAPTER
from .statistical_acceptance import load_fixture as load_statistical_fixture
from .statistical_fixture import fixture_input
from .statistical_models import VERIFICATION_INPUT_ADAPTER
from .statistical_pipeline import build_verification_artifact


def _lineage_probe(config: dict[str, JsonValue]) -> tuple[bool, bool]:
    root = RECORD.validate_python(
        load_statistical_fixture(
            Path("docs/specs/v5/fixtures/prd03-statistical-verification.json")
        )
    )
    scenarios = RECORDS.validate_python(root["scenarios"])
    scenario = next(item for item in scenarios if item.get("name") == "stable")
    stable = RECORD.validate_python(fixture_input(root, scenario))

    missing = copy_record(stable)
    missing_source = RECORD.validate_python(missing["source_node_artifact"])
    missing_source["nodes"] = []
    missing["source_node_artifact"] = missing_source
    missing_result = prompt_package(
        build_verification_artifact(
            VERIFICATION_INPUT_ADAPTER.validate_python(missing)
        ).artifact,
        config,
    )

    tampered = copy_record(stable)
    tampered_source = RECORD.validate_python(tampered["source_node_artifact"])
    tampered_nodes = RECORDS.validate_python(tampered_source["nodes"])
    tampered_nodes[0]["canonical_label"] = "변조된 선행 지표"
    tampered_source["nodes"] = [item for item in tampered_nodes]
    tampered["source_node_artifact"] = tampered_source
    tampered_result = prompt_package(
        build_verification_artifact(
            VERIFICATION_INPUT_ADAPTER.validate_python(tampered)
        ).artifact,
        config,
    )
    return (
        not RECORDS.validate_python(missing_result["verified_prompt_records"])
        and "excluded_rejected" in eligibilities(missing_result),
        not RECORDS.validate_python(tampered_result["verified_prompt_records"])
        and "excluded_rejected" in eligibilities(tampered_result),
    )


def verify_fixture(value: JsonValue) -> JsonValue:
    config = RECORD.validate_python(value)
    missing_lineage_excluded, tampered_lineage_excluded = _lineage_probe(config)
    stable_source = source_fixture("stable")
    stable = prompt_package(stable_source, config)
    stable_records = RECORDS.validate_python(stable["verified_prompt_records"])
    stable_pair = first_pair(stable_source)

    stale_source = mutate_pair_field(
        stable_source, "verification_expires_at", "2026-08-06T12:15:00+09:00"
    )
    stale = prompt_package(stale_source, config)
    inconclusive = prompt_package(source_fixture("inconclusive"), config)
    rejected = prompt_package(source_fixture("in_sample_only"), config)
    malformed_type = prompt_package(mutate_pair_field(stable_source, "selected_lag", "3"), config)
    malformed_claim = prompt_package(
        mutate_pair_field(stable_source, "claim_label", "true_causality"), config
    )
    low_confidence = prompt_package(
        mutate_pair_field(stable_source, "confidence", "0.499999"), config
    )
    strict_bool_source = copy_record(stable_source)
    strict_bool_pair = first_pair(strict_bool_source)
    strict_bool_holdout = RECORD.validate_python(strict_bool_pair["holdout"])
    strict_bool_holdout["direction_match"] = "true"
    strict_bool_pair["holdout"] = strict_bool_holdout
    strict_bool_source["pair_results"] = [strict_bool_pair]
    strict_bool = prompt_package(strict_bool_source, config)
    missing_expiry_source = copy_record(stable_source)
    missing_expiry_pair = first_pair(missing_expiry_source)
    _ = missing_expiry_pair.pop("verification_expires_at")
    missing_expiry_source["pair_results"] = [missing_expiry_pair]
    missing_expiry = prompt_package(missing_expiry_source, config)

    future_generated_source = copy_record(stable_source)
    future_generated_source["generated_at"] = "2026-08-06T13:00:00+09:00"
    future_cutoff_source = copy_record(stable_source)
    future_cutoff_source["generated_at"] = "2026-08-06T12:45:00+09:00"
    future_cutoff_source["verification_cutoff"] = "2026-08-06T12:45:00+09:00"
    provenance_fields = (
        "input_fingerprint",
        "run_config_hash",
        "correction_scope_hash",
        "split_policy_hash",
        "window_policy_hash",
        "verification_cutoff",
    )
    provenance_drift_packages: list[dict[str, JsonValue]] = []
    for index, field in enumerate(provenance_fields):
        drift = copy_record(stable_source)
        pair = first_pair(drift)
        pair[field] = (
            "2026-08-06T11:59:00+09:00"
            if field == "verification_cutoff"
            else "sha256:" + str(index) * 64
        )
        drift["pair_results"] = [pair]
        provenance_drift_packages.append(prompt_package(drift, config))

    tight_config = copy_record(config)
    tight_config["max_tokens"] = 121
    overflow = prompt_package(stable_source, tight_config)
    stale_overflow = prompt_package(stale_source, tight_config)
    stable_token_estimate = INT_VALUE.validate_python(stable_records[0]["token_estimate"])
    boundary_config = copy_record(config)
    boundary_config["max_tokens"] = (
        INT_VALUE.validate_python(boundary_config["reserved_tokens"])
        + stable_token_estimate
    )
    boundary = prompt_package(stable_source, boundary_config)

    variants = (
        Variant("confidence", "0.900000", "0.000003", 5),
        Variant("holdout", "0.800000", "0.000001", 5),
        Variant("lag", "0.800000", "0.000002", 2),
        Variant("pair_b", "0.800000", "0.000002", 3),
        Variant("pair_a", "0.800000", "0.000002", 3),
    )
    variant_pairs = [variant_pair(stable_pair, item) for item in variants]
    ordering_source = copy_record(stable_source)
    ordering_source["pair_results"] = [*reversed(variant_pairs), stable_pair]
    ordered = prompt_package(ordering_source, config)
    ordered_ids = [
        str(item["pair_id"])
        for item in RECORDS.validate_python(ordered["verified_prompt_records"])
    ]
    tied_ids = sorted(str(item["pair_id"]) for item in variant_pairs[-2:])
    expected_ids = [
        str(stable_pair["pair_id"]),
        str(variant_pairs[0]["pair_id"]),
        str(variant_pairs[1]["pair_id"]),
        str(variant_pairs[2]["pair_id"]),
        *tied_ids,
    ]
    deterministic_a = prompt_package(stable_source, config)
    deterministic_b = prompt_package(stable_source, config)

    rollback_config = copy_record(config)
    rollback_config["generated_at"] = "2026-08-06T13:00:00+09:00"
    rollback_config["prompt_cutoff"] = "2026-08-06T13:00:00+09:00"
    rolled_back = RECORD.validate_python(
        rollback_prompt_package(stable, PROMPT_CONFIG_ADAPTER.validate_python(rollback_config)).artifact
    )
    expired_config = copy_record(config)
    expired_config["generated_at"] = "2026-08-08T12:30:00+09:00"
    expired_config["prompt_cutoff"] = "2026-08-08T12:30:00+09:00"
    rollback_expired_rejected = False
    try:
        _ = rollback_prompt_package(
            stable, PROMPT_CONFIG_ADAPTER.validate_python(expired_config)
        )
    except ValueError:
        rollback_expired_rejected = True
    rollback_generated_expired = copy_record(config)
    rollback_generated_expired["generated_at"] = "2026-08-08T12:30:00+09:00"
    rollback_generated_expired_rejected = False
    try:
        _ = rollback_prompt_package(
            stable, PROMPT_CONFIG_ADAPTER.validate_python(rollback_generated_expired)
        )
    except ValueError:
        rollback_generated_expired_rejected = True
    rollback_stale_config = copy_record(config)
    rollback_stale_config["generated_at"] = "2026-08-06T13:30:00+09:00"
    rollback_stale_config["prompt_cutoff"] = "2026-08-06T13:30:00+09:00"
    rollback_stale_config["freshness_window_hours"] = 1
    rollback_stale_rejected = False
    try:
        _ = rollback_prompt_package(
            stable, PROMPT_CONFIG_ADAPTER.validate_python(rollback_stale_config)
        )
    except ValueError:
        rollback_stale_rejected = True

    legacy_rejected = False
    try:
        _ = prompt_package({"schema_version": "legacy", "verified_triples": []}, config)
    except ValueError:
        legacy_rejected = True

    runtime = runtime_probe(stable_source, ordering_source, stable, ordered, stable_pair)

    parsed = PROMPT_PACKAGE_ADAPTER.validate_python(stable)
    checks: dict[str, JsonValue] = {
        "stable_inject": len(stable_records) == 1,
        "stale_excluded": "excluded_stale" in eligibilities(stale),
        "inconclusive_excluded": "excluded_inconclusive" in eligibilities(inconclusive),
        "rejected_excluded": "excluded_rejected" in eligibilities(rejected),
        "malformed_type_excluded": "excluded_malformed" in eligibilities(malformed_type),
        "malformed_claim_excluded": "excluded_malformed" in eligibilities(malformed_claim),
        "low_confidence_excluded": "excluded_low_confidence" in eligibilities(low_confidence),
        "budget_overflow_excluded": "excluded_budget_overflow" in eligibilities(overflow),
        "deterministic_hash": deterministic_a == deterministic_b,
        "deterministic_ordering": ordered_ids == expected_ids,
        "record_hash": stable_records[0]["prompt_record_id"] == f"promptrec_{sha256(canonical_json({'schema_version': 'causal-prompt-injection.1', 'pair_id': stable_pair['pair_id'], 'prompt_cutoff': config['prompt_cutoff'], 'source_artifact_hash': stable['source_artifact_hash'], 'render_text': stable_records[0]['render_text']})).hexdigest()[:20]}",
        "package_hash": parsed.package_hash == canonical_hash({key: item for key, item in stable.items() if key != "package_hash"}),
        "provenance": RECORD.validate_python(stable_records[0]["provenance"]) == {"source_artifact_hash": stable["source_artifact_hash"], "run_config_hash": stable_pair["run_config_hash"], "correction_scope_hash": stable_pair["correction_scope_hash"], "subject_mapping_hash": stable_pair["subject_mapping_hash"], "object_mapping_hash": stable_pair["object_mapping_hash"]},
        "rollback_pointer": rolled_back["rollback_to_package_hash"] == stable["package_hash"],
        "rollback_mutation": any(item.get("mutation") == "rollback_package" for item in RECORDS.validate_python(rolled_back["prompt_mutations"])),
        "rollback_does_not_revive_expired": rollback_expired_rejected,
        "rollback_generated_at_revalidated": rollback_generated_expired_rejected,
        "rollback_current_freshness_revalidated": rollback_stale_rejected,
        "rollback_does_not_extend_expiry": rolled_back["expires_at"] == stable["expires_at"],
        "legacy_artifact_rejected": legacy_rejected,
        "immutable_created_unchanged": runtime.immutable_created_unchanged,
        "macro_verified_records_only": runtime.verified_records_only,
        "macro_invalid_package_excluded": runtime.invalid_package_excluded,
        "future_source_rejected": package_rejected(future_generated_source, config),
        "future_verification_cutoff_rejected": package_rejected(future_cutoff_source, config),
        "provenance_drift_excluded": all("excluded_malformed" in eligibilities(item) for item in provenance_drift_packages),
        "strict_bool_excluded": "excluded_malformed" in eligibilities(strict_bool),
        "missing_expiry_excluded": "excluded_malformed" in eligibilities(missing_expiry),
        "stale_before_budget": "excluded_stale" in eligibilities(stale_overflow) and "excluded_budget_overflow" not in eligibilities(stale_overflow) and RECORD.validate_python(stale_overflow["budget"])["used_tokens"] == 0,
        "budget_exact_boundary": len(RECORDS.validate_python(boundary["verified_prompt_records"])) == 1,
        "runtime_expiry_excluded": runtime.expiry_excluded,
        "runtime_no_match_excluded": runtime.no_match_excluded,
        "runtime_blank_excluded": runtime.blank_excluded,
        "runtime_missing_excluded": runtime.missing_excluded,
        "runtime_source_hash_mismatch_excluded": runtime.source_hash_mismatch_excluded,
        "macro_renders_all_gate_records": runtime.all_gate_records_rendered,
        "macro_unverified_separate": runtime.section_order_separate,
        "missing_canonical_node_excluded_end_to_end": missing_lineage_excluded,
        "tampered_canonical_label_excluded_end_to_end": tampered_lineage_excluded,
    }
    return {"state": "pass" if all(item is True for item in checks.values()) else "fail", "checks": checks}
