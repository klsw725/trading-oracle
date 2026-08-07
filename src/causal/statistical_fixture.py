from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import math
from typing import Final, Literal

from pydantic import ConfigDict, TypeAdapter

from src.causal.canonical_rules import canonical_node_id_value
from src.v4.models import JsonValue, canonical_hash


type FixtureKind = Literal[
    "stable", "short", "in_sample_only", "direction", "independent",
    "structural_break", "embargo_break",
]
_KIND: Final[TypeAdapter[FixtureKind]] = TypeAdapter(FixtureKind)
_STRICT_INT: Final = TypeAdapter(int, config=ConfigDict(strict=True))


def _coefficient(kind: FixtureKind, index: int, rows: int) -> float:
    if kind in {"stable", "short", "independent"}:
        return 0.0 if kind == "independent" else 1.4
    if kind == "in_sample_only":
        return 0.0 if index >= int(rows * 0.8) else 1.4
    if kind == "direction":
        return -1.4
    if kind == "structural_break":
        return -1.4 if int(rows * 0.25) <= index < int(rows * 0.45) else 1.4
    return -1.4 if int(rows * 0.7) <= index < int(rows * 0.8) else 1.4


def _series(kind: FixtureKind, rows: int, lag: int) -> tuple[list[JsonValue], list[JsonValue]]:
    start = datetime.fromisoformat("2025-10-11T12:00:00+09:00")
    subject: list[float] = []
    target: list[float] = []
    for index in range(rows):
        innovation = math.sin(index * 0.73) + 0.4 * math.cos(index * 1.91)
        subject.append((0.35 * subject[-1] if subject else 0.0) + innovation)
        source = subject[index - lag] if index >= lag else 0.0
        noise = 0.08 * math.sin(index * 2.17)
        independent = math.sin(index * 0.31) + 0.5 * math.cos(index * 1.37)
        previous = 0.2 * target[-1] if target else 0.0
        independent_holdout = kind == "in_sample_only" and index >= int(rows * 0.8)
        target.append(previous + _coefficient(kind, index, rows) * source + noise + (independent if kind == "independent" or independent_holdout else 0.0))
    left: list[JsonValue] = []
    right: list[JsonValue] = []
    for index, value in enumerate(subject):
        left.append({"timestamp": (start + timedelta(days=index)).isoformat(), "value": value})
    for index, value in enumerate(target):
        right.append({"timestamp": (start + timedelta(days=index)).isoformat(), "value": value})
    return left, right


def _mapping(node_id: str, label: str, series_id: str, cutoff: JsonValue) -> JsonValue:
    expiry = "2026-09-05T12:00:00+09:00"
    link: JsonValue = {
        "series_id": series_id, "transform": "level", "unit": "index", "direction": "same",
        "source_id": "fixture", "as_of": cutoff, "source_expires_at": expiry,
        "provenance_hash": "sha256:" + sha256(series_id.encode()).hexdigest(),
        "suitability": "direct_fixture_series", "suitability_evidence": "Deterministic direct observation fixture.",
        "manual_approval": {"required": True, "approved_by": "fixture-owner", "approved_at": "2026-08-01T12:00:00+09:00", "approval_reason": "Direct fixture series.", "expires_at": expiry},
    }
    body: JsonValue = {
        "mapping_result": "approved_manual", "mapping_kind": "single_series",
        "mapping_expires_at": expiry, "formula": None, "formula_unit": None,
        "series_links": [link], "proxy_candidates_rejected": [], "unmappable_reason": None,
    }
    mapping_hash = canonical_hash({"schema_version": "causal-series-mapping.1", "canonical_node_id": node_id, "mapping": body})
    return {"canonical_node_id": node_id, "canonical_label": label, "mapping_hash": mapping_hash, **body}


def fixture_input(root: dict[str, JsonValue], scenario: dict[str, JsonValue]) -> JsonValue:
    name = TypeAdapter(str).validate_python(scenario["name"])
    kind = _KIND.validate_python(scenario["kind"])
    rows = _STRICT_INT.validate_python(scenario["rows"])
    lag = _STRICT_INT.validate_python(scenario["lag"])
    subject, target = _series(kind, rows, lag)
    subject_label = "선행 지표 상승"
    object_label = "후행 지표 상승"
    direction = ("level_change", "up")
    subject_id = canonical_node_id_value(subject_label, subject_label, direction)
    object_id = canonical_node_id_value(object_label, object_label, direction)
    source_node_artifact: JsonValue = {
        "schema_version": "causal-node-canonicalization.1",
        "nodes": [
            {
                "canonical_node_id": subject_id,
                "canonical_label": subject_label,
                "normalized_label": subject_label,
                "direction": {"kind": direction[0], "polarity": direction[1]},
            },
            {
                "canonical_node_id": object_id,
                "canonical_label": object_label,
                "normalized_label": object_label,
                "direction": {"kind": direction[0], "polarity": direction[1]},
            },
        ],
        "triples": [
            {
                "subject_node_id": subject_id,
                "object_node_id": object_id,
                "relation": "increases",
            }
        ],
    }
    mappings = [
        _mapping(subject_id, subject_label, "SUBJECT", root["verification_cutoff"]),
        _mapping(object_id, object_label, "OBJECT", root["verification_cutoff"]),
    ]
    return {
        "schema_version": "causal-statistical-verification-build.1",
        "generated_at": root["generated_at"], "verification_cutoff": root["verification_cutoff"],
        "source_node_artifact": source_node_artifact,
        "source_mapping_artifact": {
            "schema_version": "causal-series-mapping.1",
            "source_node_schema_version": "causal-node-canonicalization.1",
            "source_node_artifact_hash": canonical_hash(source_node_artifact),
            "mappings": mappings,
        },
        "series": [{"series_id": "SUBJECT", "observations": subject}, {"series_id": "OBJECT", "observations": target}],
        "config": root["config"],
        "audit": {
            "locked_input_fingerprint": None, "locked_run_config_hash": None,
            "locked_correction_scope_hash": None, "locked_split_policy_hash": None,
            "locked_window_policy_hash": None, "train_decision_timestamps": [], "prior_pair_results": [],
        },
        "fixture_name": name,
    }
