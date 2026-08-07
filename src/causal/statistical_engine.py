from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash, canonical_json

from .statistical_hashes import mapping_hash_matches, source_node_artifact_hash
from .statistical_lineage import resolve_node
from .statistical_math import (
    PairFrame,
    SplitFrame,
    SplitProblem,
    WindowEvidence,
    align_and_split,
    difference,
    granger,
    mapped_series,
    signed,
    stationary,
    structural_window,
)
from .statistical_models import (
    CanonicalTriple,
    MAPPING_ENVELOPE_ADAPTER,
    MAPPING_RECORD_ADAPTER,
    MappingRecord,
    VerificationInput,
    latest_expiry,
)
from .statistical_types import PairContext, PairId, Status, TestedPair


@dataclass(frozen=True, slots=True)
class PreparedPair:
    context: PairContext
    subject_mapping: MappingRecord
    object_mapping: MappingRecord
    split: SplitFrame
    subject_order: int
    object_order: int
    subject_adf_p: float
    object_adf_p: float
    eligible_lags: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PairProblem:
    context: PairContext
    status: Status
    reason: str


@dataclass(frozen=True, slots=True)
class MappingResolution:
    record: MappingRecord | None
    evidence_hash: str
    reason: str | None


def _mapping(build: VerificationInput, node_id: str) -> MappingResolution:
    candidates: list[JsonValue] = []
    for raw in build.source_mapping_artifact.mappings:
        try:
            envelope = MAPPING_ENVELOPE_ADAPTER.validate_python(raw)
        except ValidationError:
            continue
        if envelope.canonical_node_id == node_id:
            candidates.append(raw)
    if not candidates:
        return MappingResolution(None, str(canonical_hash({"missing_mapping": node_id})), "approved_mapping_missing")
    if len(candidates) != 1:
        return MappingResolution(None, str(canonical_hash(candidates)), "duplicate_mapping_records")
    raw = candidates[0]
    evidence_hash = str(canonical_hash(raw))
    try:
        mapping = MAPPING_RECORD_ADAPTER.validate_python(raw)
    except ValidationError:
        return MappingResolution(None, evidence_hash, "approved_mapping_malformed")
    if mapping.mapping_result != "approved_manual":
        return MappingResolution(None, evidence_hash, f"mapping_not_approved:{mapping.mapping_result}")
    if not mapping_hash_matches(mapping):
        return MappingResolution(None, evidence_hash, "mapping_hash_mismatch")
    expiry = latest_expiry(mapping)
    if expiry is None or not mapping.series_links:
        return MappingResolution(None, evidence_hash, "approved_mapping_malformed")
    if expiry <= build.verification_cutoff:
        return MappingResolution(None, evidence_hash, "approved_mapping_expired")
    if any(link.direction == "not_directional" for link in mapping.series_links):
        return MappingResolution(None, evidence_hash, "mapping_direction_not_reviewable")
    return MappingResolution(mapping, mapping.mapping_hash or evidence_hash, None)


def _pair_id(build: VerificationInput, triple: CanonicalTriple, subject_hash: str, object_hash: str) -> PairId:
    seed: JsonValue = {
        "schema_version": "causal-statistical-verification.1",
        "subject_node_id": triple.subject_node_id,
        "object_node_id": triple.object_node_id,
        "relation": triple.relation,
        "subject_mapping_hash": subject_hash,
        "object_mapping_hash": object_hash,
        "verification_cutoff": build.verification_cutoff.isoformat(),
        "lag_grid": list(build.config.lag_grid),
    }
    return PairId(f"statpair_{sha256(canonical_json(seed)).hexdigest()[:20]}")


def _context(build: VerificationInput, triple: CanonicalTriple, subject: MappingResolution, object_: MappingResolution, fingerprint: str) -> PairContext:
    subject_node = resolve_node(build, triple.subject_node_id).node
    object_node = resolve_node(build, triple.object_node_id).node
    records = tuple(item.record for item in (subject, object_) if item.record is not None)
    expiries = tuple(expiry for mapping in records if (expiry := latest_expiry(mapping)) is not None)
    mapping_expiry = min(expiries) if len(expiries) == 2 else build.verification_cutoff
    verification_expiry = min(build.generated_at + timedelta(days=build.config.verification_ttl_days), mapping_expiry)
    return PairContext(
        _pair_id(build, triple, subject.evidence_hash, object_.evidence_hash),
        triple.subject_node_id, triple.object_node_id,
        subject_node.canonical_label if subject_node is not None else "unavailable",
        object_node.canonical_label if object_node is not None else "unavailable",
        triple.relation, subject.evidence_hash, object_.evidence_hash,
        "+".join(link.series_id for link in subject.record.series_links) if subject.record is not None else "unavailable",
        "+".join(link.series_id for link in object_.record.series_links) if object_.record is not None else "unavailable",
        mapping_expiry.isoformat(), verification_expiry.isoformat(), build.verification_cutoff.isoformat(),
        build.config.lag_grid, fingerprint,
    )


def prepare_pair(build: VerificationInput, triple: CanonicalTriple, fingerprint: str) -> PreparedPair | PairProblem:
    subject_node = resolve_node(build, triple.subject_node_id)
    object_node = resolve_node(build, triple.object_node_id)
    subject = _mapping(build, triple.subject_node_id)
    object_ = _mapping(build, triple.object_node_id)
    context = _context(build, triple, subject, object_, fingerprint)
    lineage_reasons = tuple(
        reason
        for reason in (
            subject_node.reason,
            object_node.reason,
            "source_node_artifact_hash_mismatch"
            if build.source_mapping_artifact.source_node_artifact_hash
            != source_node_artifact_hash(build)
            else None,
            "subject_mapping_label_mismatch"
            if subject_node.node is not None
            and subject.record is not None
            and subject.record.canonical_label != subject_node.node.canonical_label
            else None,
            "object_mapping_label_mismatch"
            if object_node.node is not None
            and object_.record is not None
            and object_.record.canonical_label != object_node.node.canonical_label
            else None,
        )
        if reason is not None
    )
    if lineage_reasons:
        return PairProblem(context, Status.MALFORMED, lineage_reasons[0])
    reasons = tuple(item.reason for item in (subject, object_) if item.reason is not None)
    if reasons or subject.record is None or object_.record is None:
        reason = reasons[0] if reasons else "approved_mapping_missing"
        malformed = reason in {"approved_mapping_malformed", "mapping_hash_mismatch", "duplicate_mapping_records"}
        return PairProblem(context, Status.MALFORMED if malformed else Status.INCONCLUSIVE, reason)
    frame_ids = [frame.series_id for frame in build.series]
    if len(frame_ids) != len(set(frame_ids)):
        return PairProblem(context, Status.MALFORMED, "duplicate_series_frames")
    frames = {frame.series_id: frame for frame in build.series}
    required = {link.series_id for mapping in (subject.record, object_.record) for link in mapping.series_links}
    if not required.issubset(frames):
        return PairProblem(context, Status.INCONCLUSIVE, "series_observations_missing")
    for series_id in required:
        timestamps = tuple(item.timestamp for item in frames[series_id].observations)
        if len(timestamps) != len(set(timestamps)):
            return PairProblem(context, Status.LEAKAGE, "duplicate_observation_timestamp")
        if any(timestamp > build.verification_cutoff for timestamp in timestamps):
            return PairProblem(context, Status.LEAKAGE, "post_cutoff_observation_present")
    subject_values = mapped_series(subject.record, frames)
    object_values = mapped_series(object_.record, frames)
    split = align_and_split(subject_values, object_values, build.config)
    if isinstance(split, SplitProblem):
        return PairProblem(context, Status.INCONCLUSIVE, split.reason)
    train_subject = stationary(split.train.subject, float(build.config.stationarity_alpha), build.config.max_diff_order)
    train_object = stationary(split.train.object, float(build.config.stationarity_alpha), build.config.max_diff_order)
    if train_subject is None or train_object is None:
        return PairProblem(context, Status.INCONCLUSIVE, "non_stationary_after_max_diff")
    train_rows = min(len(train_subject.values), len(train_object.values))
    eligible = tuple(lag for lag in build.config.lag_grid if train_rows - lag >= build.config.min_train_rows_after_lag)
    if not eligible:
        return PairProblem(context, Status.INCONCLUSIVE, "insufficient_train_rows")
    return PreparedPair(context, subject.record, object_.record, split, train_subject.order, train_object.order, train_subject.p_value, train_object.p_value, eligible)


def expected_sign(relation: str) -> int:
    return -1 if relation in {"decreases", "blocks"} else 1


def _transformed(frame: PairFrame, prepared: PreparedPair) -> PairFrame:
    order = max(prepared.subject_order, prepared.object_order)
    subject = signed(difference(frame.subject, prepared.subject_order), prepared.subject_mapping)
    object_ = signed(difference(frame.object, prepared.object_order), prepared.object_mapping)
    rows = min(len(subject), len(object_))
    return PairFrame(frame.timestamps[order:][-rows:], subject[-rows:], object_[-rows:])


def _windows(prepared: PreparedPair, lag: int, build: VerificationInput) -> tuple[WindowEvidence, ...]:
    sign = expected_sign(prepared.context.relation)
    frames = {"train": prepared.split.train, "embargo": prepared.split.embargo, "holdout": prepared.split.holdout}
    baseline = _transformed(prepared.split.train, prepared)
    windows = [structural_window(name, _transformed(frames[name], prepared), baseline, lag, sign, build.config) for name in build.config.structural_windows]
    full = _transformed(prepared.split.full, prepared)
    rows = len(full.subject)
    for index in range(build.config.rolling_windows):
        start = rows * index // build.config.rolling_windows
        end = rows * (index + 1) // build.config.rolling_windows
        frame = PairFrame(full.timestamps[start:end], full.subject[start:end], full.object[start:end])
        windows.append(structural_window(f"rolling_{index + 1:02d}", frame, baseline, lag, sign, build.config))
    return tuple(windows)


def test_pair(prepared: PreparedPair, build: VerificationInput) -> TestedPair | PairProblem:
    train = _transformed(prepared.split.train, prepared)
    sign = expected_sign(prepared.context.relation)
    table = tuple(result for lag in prepared.eligible_lags if (result := granger(train.subject, train.object, lag, sign)) is not None)
    if not table:
        return PairProblem(prepared.context, Status.INCONCLUSIVE, "granger_train_infeasible")
    selected = min(table, key=lambda item: (item.p_value, item.lag))
    holdout_frame = _transformed(prepared.split.holdout, prepared)
    if min(len(holdout_frame.subject), len(holdout_frame.object)) - selected.lag < build.config.min_holdout_rows_after_lag:
        return PairProblem(prepared.context, Status.INCONCLUSIVE, "insufficient_holdout_rows")
    holdout = granger(holdout_frame.subject, holdout_frame.object, selected.lag, sign)
    if holdout is None:
        return PairProblem(prepared.context, Status.INCONCLUSIVE, "granger_holdout_infeasible")
    windows = _windows(prepared, selected.lag, build)
    reversal = any(item.status == "fail" and not item.direction_match for item in windows)
    structural_break = any(item.status == "fail" for item in windows)
    inconclusive = sum(item.status == "inconclusive" for item in windows)
    return TestedPair(prepared.context, selected, holdout, prepared.subject_order, prepared.object_order, prepared.subject_adf_p, prepared.object_adf_p, table, windows, reversal, structural_break, inconclusive)


def correction(prepared: tuple[PreparedPair, ...], alpha: Decimal) -> tuple[int, Decimal, str]:
    hypotheses = sum(len(item.eligible_lags) for item in prepared)
    scope: JsonValue = [{"pair_id": item.context.pair_id, "lag_grid": list(item.eligible_lags)} for item in sorted(prepared, key=lambda item: item.context.pair_id)]
    corrected = alpha / Decimal(hypotheses) if hypotheses else alpha
    return hypotheses, corrected, str(canonical_hash(scope))


def split_evidence(prepared: PreparedPair) -> JsonValue:
    split = prepared.split
    return {
        "pair_id": prepared.context.pair_id,
        "aligned_rows": len(split.full.timestamps),
        "train_rows": len(split.train.timestamps),
        "embargo_rows": len(split.embargo.timestamps),
        "holdout_rows": len(split.holdout.timestamps),
        "train_start": split.train.timestamps[0].isoformat(), "train_end": split.train.timestamps[-1].isoformat(),
        "embargo_start": split.embargo.timestamps[0].isoformat(), "embargo_end": split.embargo.timestamps[-1].isoformat(),
        "holdout_start": split.holdout.timestamps[0].isoformat(), "holdout_end": split.holdout.timestamps[-1].isoformat(),
    }


def window_policy_evidence(prepared: PreparedPair, build: VerificationInput) -> JsonValue:
    return {
        "pair_id": prepared.context.pair_id,
        "structural_windows": list(build.config.structural_windows),
        "rolling_windows": build.config.rolling_windows,
        "full_start": prepared.split.full.timestamps[0].isoformat(),
        "full_end": prepared.split.full.timestamps[-1].isoformat(),
    }
