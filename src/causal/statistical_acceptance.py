from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from src.causal.series_mapping import build_mapping_artifact, parse_mapping_input
from src.causal.series_mapping_acceptance import load_json as load_mapping_json
from src.v4.models import JsonValue, canonical_json

from .statistical_fixture import fixture_input
from .statistical_hashes import result_fingerprint
from .statistical_models import MAPPING_RECORD_ADAPTER, VERIFICATION_INPUT_ADAPTER, VerificationInput
from .statistical_output_models import PAIR_RESULT_ADAPTER
from .statistical_pipeline import build_verification_artifact


_JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
_RECORD: Final = TypeAdapter(dict[str, JsonValue])
_RECORDS: Final = TypeAdapter(list[dict[str, JsonValue]])
_VALUES: Final = TypeAdapter(list[JsonValue])


def load_fixture(path: Path) -> JsonValue:
    return _JSON.validate_json(path.read_bytes())


def _record(value: JsonValue, field: str) -> dict[str, JsonValue]:
    try:
        return _RECORD.validate_python(value)
    except ValidationError as error:
        raise AssertionError(field) from error


def _raw(build: VerificationInput) -> dict[str, JsonValue]:
    return _RECORD.validate_json(canonical_json(build.model_dump(mode="json")))


def _artifact(build: VerificationInput) -> dict[str, JsonValue]:
    return _record(build_verification_artifact(build).artifact, "artifact")


def _pair(artifact: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return _RECORDS.validate_python(artifact["pair_results"])[0]


def _status(build: VerificationInput) -> str:
    return TypeAdapter(str).validate_python(_pair(_artifact(build))["verification_status"])


def _with_audit(build: VerificationInput, updates: dict[str, JsonValue]) -> VerificationInput:
    root = _raw(build)
    audit = _record(root["audit"], "audit")
    audit.update(updates)
    root["audit"] = audit
    return VERIFICATION_INPUT_ADAPTER.validate_python(root)


def _wrong_hash() -> str:
    return "sha256:" + "0" * 64


def _json_records(records: list[dict[str, JsonValue]]) -> list[JsonValue]:
    values: list[JsonValue] = []
    for record in records:
        values.append(record)
    return values


def _reader_rejects(pair: dict[str, JsonValue], field: str, value: JsonValue, remove: bool = False) -> bool:
    candidate = _RECORD.validate_json(canonical_json(pair))
    if remove:
        _ = candidate.pop(field)
    else:
        candidate[field] = value
    try:
        _ = PAIR_RESULT_ADAPTER.validate_python(candidate)
    except ValidationError:
        return True
    return False


def _reader_rejects_stability(pair: dict[str, JsonValue], updates: dict[str, JsonValue]) -> bool:
    candidate = _RECORD.validate_json(canonical_json(pair))
    stability = _record(candidate["stability"], "stability")
    stability.update(updates)
    candidate["stability"] = stability
    try:
        _ = PAIR_RESULT_ADAPTER.validate_python(candidate)
    except ValidationError:
        return True
    return False


def _duplicate_timestamp(build: VerificationInput) -> VerificationInput:
    root = _raw(build)
    series = _RECORDS.validate_python(root["series"])
    observations = _VALUES.validate_python(series[0]["observations"])
    observations.append(observations[0])
    series[0]["observations"] = observations
    root["series"] = _json_records(series)
    return VERIFICATION_INPUT_ADAPTER.validate_python(root)


def _malformed_mapping(build: VerificationInput, hash_only: bool) -> VerificationInput:
    root = _raw(build)
    mapping_artifact = _record(root["source_mapping_artifact"], "mapping artifact")
    mappings = _RECORDS.validate_python(mapping_artifact["mappings"])
    if hash_only:
        mappings[0]["mapping_hash"] = _wrong_hash()
    else:
        links = _RECORDS.validate_python(mappings[0]["series_links"])
        links[0]["direction"] = 7
        mappings[0]["series_links"] = _json_records(links)
    mapping_artifact["mappings"] = _json_records(mappings)
    root["source_mapping_artifact"] = mapping_artifact
    return VERIFICATION_INPUT_ADAPTER.validate_python(root)


def _with_canonical_nodes(
    build: VerificationInput, nodes: list[dict[str, JsonValue]]
) -> VerificationInput:
    root = _raw(build)
    artifact = _record(root["source_node_artifact"], "node artifact")
    artifact["nodes"] = _json_records(nodes)
    root["source_node_artifact"] = artifact
    return VERIFICATION_INPUT_ADAPTER.validate_python(root)


def _with_source_artifact_hash(
    build: VerificationInput, artifact_hash: str
) -> VerificationInput:
    root = _raw(build)
    artifact = _record(root["source_mapping_artifact"], "mapping artifact")
    artifact["source_node_artifact_hash"] = artifact_hash
    root["source_mapping_artifact"] = artifact
    return VERIFICATION_INPUT_ADAPTER.validate_python(root)


def _changed_input(build: VerificationInput) -> VerificationInput:
    root = _raw(build)
    series = _RECORDS.validate_python(root["series"])
    observations = _RECORDS.validate_python(series[0]["observations"])
    observations[0]["value"] = 0.123456
    series[0]["observations"] = _json_records(observations)
    root["series"] = _json_records(series)
    return VERIFICATION_INPUT_ADAPTER.validate_python(root)


def _with_config(build: VerificationInput, config_updates: dict[str, JsonValue], audit_updates: dict[str, JsonValue]) -> VerificationInput:
    root = _raw(build)
    config = _record(root["config"], "config")
    config.update(config_updates)
    audit = _record(root["audit"], "audit")
    audit.update(audit_updates)
    root["config"] = config
    root["audit"] = audit
    return VERIFICATION_INPUT_ADAPTER.validate_python(root)


def _real_prd02_compatible() -> bool:
    fixture = _record(load_mapping_json(Path("docs/specs/v5/fixtures/prd02-series-mapping-provenance.json")), "prd02 fixture")
    artifact = _record(build_mapping_artifact(parse_mapping_input(fixture["build_input"])).artifact, "prd02 artifact")
    approved = [item for item in _RECORDS.validate_python(artifact["mappings"]) if item.get("mapping_result") == "approved_manual"]
    try:
        records = [MAPPING_RECORD_ADAPTER.validate_python(item) for item in approved]
    except ValidationError:
        return False
    from .statistical_hashes import mapping_hash_matches
    return len(records) == 2 and all(mapping_hash_matches(item) for item in records)


def verify_fixture(value: JsonValue) -> JsonValue:
    root = _record(value, "root")
    scenarios = _RECORDS.validate_python(root["scenarios"])
    builds = {TypeAdapter(str).validate_python(item["name"]): VERIFICATION_INPUT_ADAPTER.validate_python(fixture_input(root, item)) for item in scenarios}
    stable = builds["stable"]
    stable_nodes = _RECORDS.validate_python(
        _record(_raw(stable)["source_node_artifact"], "node artifact")["nodes"]
    )
    tampered_nodes = _RECORDS.validate_json(canonical_json(_json_records(stable_nodes)))
    tampered_nodes[0]["canonical_label"] = "변조된 선행 지표"
    stable_artifact = _artifact(stable)
    stable_pair = _pair(stable_artifact)
    _ = PAIR_RESULT_ADAPTER.validate_python(stable_pair)
    fingerprint = TypeAdapter(str).validate_python(stable_artifact["input_fingerprint"])
    pair_id = TypeAdapter(str).validate_python(stable_pair["pair_id"])
    current_result_hash = result_fingerprint(stable_pair)
    prior_wrong: JsonValue = {"input_fingerprint": fingerprint, "pair_id": pair_id, "result_fingerprint": _wrong_hash()}
    prior_changed_id: JsonValue = {"input_fingerprint": fingerprint, "pair_id": "statpair_" + "0" * 20, "result_fingerprint": current_result_hash}
    flaky = _with_audit(stable, {"prior_pair_results": [prior_wrong]})
    changed_input = _with_audit(_changed_input(stable), {"prior_pair_results": [prior_wrong]})
    changed_id = _with_audit(stable, {"prior_pair_results": [prior_changed_id]})
    correction_hash = TypeAdapter(str).validate_python(stable_artifact["correction_scope_hash"])
    split_hash = TypeAdapter(str).validate_python(stable_artifact["split_policy_hash"])
    window_hash = TypeAdapter(str).validate_python(stable_artifact["window_policy_hash"])
    input_mutation = _with_audit(_changed_input(stable), {"locked_input_fingerprint": fingerprint})
    correction_mutation = _with_config(stable, {"lag_grid": [1, 2, 3]}, {"locked_correction_scope_hash": correction_hash})
    split_mutation = _with_config(stable, {"embargo_sessions": 29}, {"locked_split_policy_hash": split_hash})
    window_mutation = _with_config(stable, {"rolling_windows": 5}, {"locked_window_policy_hash": window_hash})
    leakage = _with_audit(stable, {"train_decision_timestamps": ["2026-07-15T12:00:00+09:00"]})
    split = _record(stable_pair["split"], "split")
    embargo_pair = _pair(_artifact(builds["embargo_break"]))
    embargo_stability = _record(embargo_pair["stability"], "embargo stability")
    embargo_windows = [item for item in _RECORDS.validate_python(embargo_stability["predeclared_windows"]) if item.get("window_id") == "embargo"]
    stable_stability = _record(stable_pair["stability"], "stable stability")
    stable_windows = _RECORDS.validate_python(stable_stability["predeclared_windows"])
    rolling_windows = [item for item in stable_windows if isinstance(item.get("window_id"), str) and str(item["window_id"]).startswith("rolling_")]
    checks: dict[str, JsonValue] = {
        "verified_stable": _status(stable) == "verified_stable",
        "rejected_in_sample_only": _status(builds["in_sample_only"]) == "rejected_in_sample_only",
        "inconclusive": _status(builds["inconclusive"]) == "inconclusive",
        "direction": _status(builds["direction"]) == "rejected_direction_mismatch",
        "multiple_testing": _status(builds["multiple_testing"]) == "rejected_multiple_testing",
        "structural_break": _status(builds["structural_break"]) == "rejected_structural_break",
        "embargo_structural_mutation": _status(builds["embargo_break"]) == "rejected_structural_break" and any(item.get("status") == "fail" for item in embargo_windows),
        "explicit_split_window_policy": split.get("train_rows") == 210 and split.get("embargo_rows") == 30 and split.get("holdout_rows") == 60,
        "p_hacking": _status(_with_audit(stable, {"locked_run_config_hash": _wrong_hash()})) == "rejected_p_hacking",
        "input_fingerprint_lock": _status(input_mutation) == "rejected_p_hacking",
        "correction_scope_lock": _status(correction_mutation) == "rejected_p_hacking",
        "split_policy_lock": _status(split_mutation) == "rejected_p_hacking",
        "window_policy_lock": _status(window_mutation) == "rejected_p_hacking",
        "leakage": _status(leakage) == "rejected_leakage",
        "duplicate_timestamp_terminal": _status(_duplicate_timestamp(stable)) == "rejected_leakage",
        "malformed_mapping_terminal": _status(_malformed_mapping(stable, False)) == "rejected_malformed",
        "mapping_hash_recomputed": _status(_malformed_mapping(stable, True)) == "rejected_malformed",
        "missing_canonical_node_terminal": _status(_with_canonical_nodes(stable, [])) == "rejected_malformed",
        "tampered_canonical_label_terminal": _status(_with_canonical_nodes(stable, tampered_nodes)) == "rejected_malformed",
        "source_artifact_lineage_terminal": _status(_with_source_artifact_hash(stable, _wrong_hash())) == "rejected_malformed",
        "flaky": _status(flaky) == "rejected_flaky",
        "flaky_same_input_only": _status(changed_input) != "rejected_flaky",
        "flaky_changed_pair_id": _status(changed_id) == "rejected_flaky",
        "prd02_real_artifact_compatible": _real_prd02_compatible(),
        "strict_full_pair_reader": _reader_rejects(stable_pair, "run_config_hash", None, remove=True) and _reader_rejects(stable_pair, "train", {"p_value": "0.1"}),
        "decimal_ranges": _reader_rejects(stable_pair, "confidence", "9.999999"),
        "verified_structural_invariants": _reader_rejects_stability(stable_pair, {"structural_break_check": "fail"}),
        "rolling_window_count_invariants": _reader_rejects_stability(stable_pair, {"rolling_windows_checked": 8}),
        "rolling_only_counts": stable_stability.get("rolling_windows_checked") == 4 and stable_stability.get("rolling_windows_passed") == sum(item.get("status") == "pass" for item in rolling_windows) and len(rolling_windows) == 4,
        "deterministic_pair_ids": stable_artifact == _artifact(stable),
        "typed_decimal_evidence": isinstance(_record(stable_pair["train"], "train").get("p_value"), str),
        "append_only_mutations": bool(_artifact(flaky)["verification_mutations"]),
        "prd04_fields": all(field in stable_pair for field in ("input_fingerprint", "confidence", "verification_expires_at", "mapping_expires_at", "run_config_hash", "correction_scope_hash", "split_policy_hash", "window_policy_hash", "subject_mapping_hash", "object_mapping_hash", "subject_label", "object_label")),
        "mapping_transform": stable_pair.get("subject_series_id") == "SUBJECT",
        "train_only_stationarity": stable_pair.get("stationarity") is not None,
        "bonferroni_pair_lag_scope": _record(stable_pair["multiple_testing"], "multiple testing").get("tested_hypotheses") == 5,
        "malformed_type_drift": _reader_rejects(stable_pair, "selected_lag", "5"),
    }
    return {"state": "pass" if all(item is True for item in checks.values()) else "fail", "checks": checks}
