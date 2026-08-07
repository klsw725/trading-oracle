from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from pydantic import TypeAdapter

from src.v4.models import JsonValue, canonical_json, write_immutable_json
from src.perspectives.macro import get_macro_verified_prompt_records
from src.perspectives.macro_prompt import build_macro_prompt
from src.perspectives.macro_prompt_models import (
    MACRO_PROMPT_SOURCE_ADAPTER,
    MacroPromptRuntime,
)

from .prompt_injection_gate import build_prompt_package
from .prompt_injection_models import PROMPT_CONFIG_ADAPTER, PROMPT_PACKAGE_ADAPTER
from .statistical_acceptance import load_fixture
from .statistical_fixture import fixture_input
from .statistical_models import VERIFICATION_INPUT_ADAPTER
from .statistical_pipeline import build_verification_artifact


RECORD: Final = TypeAdapter(dict[str, JsonValue])
RECORDS: Final = TypeAdapter(list[dict[str, JsonValue]])
INT_VALUE: Final = TypeAdapter(int)


@dataclass(frozen=True, slots=True)
class Variant:
    suffix: str
    confidence: str
    holdout_p_value: str
    selected_lag: int


@dataclass(frozen=True, slots=True)
class RuntimeProbe:
    immutable_created_unchanged: bool
    verified_records_only: bool
    invalid_package_excluded: bool
    expiry_excluded: bool
    no_match_excluded: bool
    blank_excluded: bool
    missing_excluded: bool
    source_hash_mismatch_excluded: bool
    all_gate_records_rendered: bool
    section_order_separate: bool


def copy_record(value: JsonValue) -> dict[str, JsonValue]:
    return RECORD.validate_json(canonical_json(value))


def source_fixture(kind: str) -> dict[str, JsonValue]:
    fixture = RECORD.validate_python(
        load_fixture(Path("docs/specs/v5/fixtures/prd03-statistical-verification.json"))
    )
    scenarios = RECORDS.validate_python(fixture["scenarios"])
    scenario = next(item for item in scenarios if item.get("name") == kind)
    build = VERIFICATION_INPUT_ADAPTER.validate_python(fixture_input(fixture, scenario))
    return RECORD.validate_python(build_verification_artifact(build).artifact)


def first_pair(source: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return RECORDS.validate_python(source["pair_results"])[0]


def prompt_package(
    source: JsonValue, config: JsonValue, prior_hash: str | None = None
) -> dict[str, JsonValue]:
    parsed = PROMPT_CONFIG_ADAPTER.validate_python(config)
    return RECORD.validate_python(
        build_prompt_package(source, parsed, prior_hash).artifact
    )


def eligibilities(package: dict[str, JsonValue]) -> set[str]:
    return {
        str(item["eligibility"])
        for item in RECORDS.validate_python(package["excluded_prompt_records"])
    }


def mutate_pair_field(
    source: dict[str, JsonValue], field: str, value: JsonValue
) -> dict[str, JsonValue]:
    changed = copy_record(source)
    pair = first_pair(changed)
    pair[field] = value
    changed["pair_results"] = [pair]
    return changed


def package_rejected(source: JsonValue, config: JsonValue) -> bool:
    try:
        _ = prompt_package(source, config)
    except ValueError:
        return True
    return False


def variant_pair(
    pair: dict[str, JsonValue], variant: Variant
) -> dict[str, JsonValue]:
    changed = copy_record(pair)
    changed["subject_node_id"] = f"subject_{variant.suffix}"
    changed["confidence"] = variant.confidence
    changed["selected_lag"] = variant.selected_lag
    holdout = RECORD.validate_python(changed["holdout"])
    holdout["p_value"] = variant.holdout_p_value
    changed["holdout"] = holdout
    seed: JsonValue = {
        "schema_version": "causal-statistical-verification.1",
        "subject_node_id": changed["subject_node_id"],
        "object_node_id": changed["object_node_id"],
        "relation": changed["relation"],
        "subject_mapping_hash": changed["subject_mapping_hash"],
        "object_mapping_hash": changed["object_mapping_hash"],
        "verification_cutoff": changed["verification_cutoff"],
        "lag_grid": changed["declared_lag_grid"],
    }
    pair_id = f"statpair_{sha256(canonical_json(seed)).hexdigest()[:20]}"
    changed["pair_id"] = pair_id
    split = RECORD.validate_python(changed["split"])
    split["pair_id"] = pair_id
    changed["split"] = split
    return changed


def runtime_probe(
    stable_source: dict[str, JsonValue],
    ordering_source: dict[str, JsonValue],
    stable: dict[str, JsonValue],
    ordered: dict[str, JsonValue],
    stable_pair: dict[str, JsonValue],
) -> RuntimeProbe:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        package_path = root / "package.json"
        invalid_path = root / "invalid.json"
        expired_path = root / "expired.json"
        full_path = root / "full.json"
        source_path = root / "source.json"
        full_source_path = root / "full-source.json"
        wrong_source_path = root / "wrong-source.json"
        _ = write_immutable_json(source_path, stable_source)
        _ = write_immutable_json(full_source_path, ordering_source)
        _ = write_immutable_json(wrong_source_path, source_fixture("inconclusive"))
        first_write = write_immutable_json(package_path, stable)
        second_write = write_immutable_json(package_path, stable)
        keyword = str(stable_pair["subject_label"])
        cutoff = "2026-08-06T12:30:00+09:00"
        routed = get_macro_verified_prompt_records([keyword], package_path, cutoff, source_path)
        invalid = copy_record(stable)
        invalid["package_hash"] = "sha256:" + "0" * 64
        _ = write_immutable_json(invalid_path, invalid)
        invalid_routed = get_macro_verified_prompt_records([keyword], invalid_path, cutoff, source_path)
        _ = write_immutable_json(expired_path, stable)
        _ = write_immutable_json(full_path, ordered)
        expired_routed = get_macro_verified_prompt_records([keyword], expired_path, str(stable["expires_at"]), source_path)
        no_match = get_macro_verified_prompt_records(["no_matching_node_label"], package_path, cutoff, source_path)
        blank = get_macro_verified_prompt_records(["", "   "], package_path, cutoff, source_path)
        missing = get_macro_verified_prompt_records([keyword], root / "missing.json", cutoff, source_path)
        wrong_source = get_macro_verified_prompt_records([keyword], package_path, cutoff, wrong_source_path)
        macro_source = MACRO_PROMPT_SOURCE_ADAPTER.validate_python(
            {"ticker": "005930", "name": keyword, "signals": {"current_price": 1, "change_20d": 1, "change_5d": 1, "high_52w": 1, "low_52w": 1}}
        )
        full_macro = build_macro_prompt(
            macro_source,
            MacroPromptRuntime(package_path=full_path, source_path=full_source_path, as_of=cutoff, causal_context="unverified_fixture", quantitative_context=""),
        )
        parsed = PROMPT_PACKAGE_ADAPTER.validate_python(ordered)
        return RuntimeProbe(
            first_write.value == "created" and second_write.value == "unchanged",
            len(routed) == 1 and routed[0].prompt_record_id == PROMPT_PACKAGE_ADAPTER.validate_python(stable).verified_prompt_records[0].prompt_record_id,
            not invalid_routed,
            not expired_routed,
            not no_match,
            not blank,
            not missing,
            not wrong_source,
            full_macro.verified_record_ids == tuple(item.prompt_record_id for item in parsed.verified_prompt_records),
            full_macro.section_order == ("verified", "unverified"),
        )
