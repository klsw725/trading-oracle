from __future__ import annotations

from hmac import compare_digest

from src.v4.models import JsonValue, canonical_hash

from .statistical_models import MappingRecord, VerificationInput


def mapping_body(mapping: MappingRecord) -> JsonValue:
    return {
        "mapping_result": mapping.mapping_result,
        "mapping_kind": mapping.mapping_kind,
        "mapping_expires_at": mapping.mapping_expires_at.isoformat() if mapping.mapping_expires_at is not None else None,
        "formula": mapping.formula,
        "formula_unit": mapping.formula_unit,
        "series_links": [link.model_dump(mode="json") for link in mapping.series_links],
        "proxy_candidates_rejected": list(mapping.proxy_candidates_rejected),
        "unmappable_reason": mapping.unmappable_reason,
    }


def recompute_mapping_hash(mapping: MappingRecord) -> str:
    seed: JsonValue = {
        "schema_version": "causal-series-mapping.1",
        "canonical_node_id": mapping.canonical_node_id,
        "mapping": mapping_body(mapping),
    }
    return str(canonical_hash(seed))


def mapping_hash_matches(mapping: MappingRecord) -> bool:
    return mapping.mapping_hash is not None and compare_digest(mapping.mapping_hash, recompute_mapping_hash(mapping))


def source_node_artifact_hash(build: VerificationInput) -> str:
    return str(canonical_hash(build.source_node_artifact.model_dump(mode="json")))


def run_config_hash(build: VerificationInput) -> str:
    return str(canonical_hash(build.config.model_dump(mode="json")))


def input_fingerprint(build: VerificationInput) -> str:
    seed: JsonValue = {
        "schema_version": build.schema_version,
        "generated_at": build.generated_at.isoformat(),
        "verification_cutoff": build.verification_cutoff.isoformat(),
        "source_node_artifact": build.source_node_artifact.model_dump(mode="json"),
        "source_mapping_artifact": build.source_mapping_artifact.model_dump(mode="json"),
        "series": [frame.model_dump(mode="json") for frame in build.series],
        "config": build.config.model_dump(mode="json"),
    }
    return str(canonical_hash(seed))


def split_policy_hash(build: VerificationInput, split_evidence: list[JsonValue]) -> str:
    seed: JsonValue = {
        "policy": build.config.split_policy,
        "train_fraction": str(build.config.train_fraction),
        "embargo_fraction": str(build.config.embargo_fraction),
        "holdout_fraction": str(build.config.holdout_fraction),
        "embargo_sessions": build.config.embargo_sessions,
        "pairs": split_evidence,
    }
    return str(canonical_hash(seed))


def window_policy_hash(build: VerificationInput, window_evidence: list[JsonValue]) -> str:
    seed: JsonValue = {
        "policy": build.config.window_policy,
        "structural_windows": list(build.config.structural_windows),
        "rolling_windows": build.config.rolling_windows,
        "min_window_rows": build.config.min_window_rows,
        "max_mean_shift": str(build.config.max_mean_shift),
        "max_variance_ratio": str(build.config.max_variance_ratio),
        "pairs": window_evidence,
    }
    return str(canonical_hash(seed))


def result_fingerprint(result: JsonValue) -> str:
    return str(canonical_hash(result))
