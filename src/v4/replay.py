# pyright: reportUnnecessaryComparison=false

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique
from typing import Final, assert_never, override

from pydantic import TypeAdapter, ValidationError

from src.v4.models import (
    Action,
    ContentHash,
    JsonValue,
    MeasurementState,
    ReplayMode,
    canonical_hash,
)


_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_OBJECT: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])
PERSPECTIVE_ORDER: Final = ("kwangsoo", "ouroboros", "quant", "macro", "value")


@unique
class ParserVersion(StrEnum):
    PERSPECTIVE_V1 = "perspective-json-v1"


@unique
class IneligibilityReason(StrEnum):
    LEGACY_SNAPSHOT = "legacy_snapshot"
    MISSING_DATA_CUTOFF = "missing_data_cutoff"
    MISSING_PROMPT = "missing_prompt"
    MISSING_RAW_RESULT = "missing_raw_result"
    MISSING_PARSER_VERSION = "missing_parser_version"
    INVALID_PERSPECTIVE_ORDER = "invalid_perspective_order"
    OUTCOME_NOT_MATURED = "outcome_not_matured"
    MISSING_OUTCOME_PROVENANCE = "missing_outcome_provenance"
    MISSING_DENOMINATOR = "missing_denominator"
    MALFORMED_MEASUREMENT = "malformed_measurement"
    SESSION_MISMATCH = "session_mismatch"
    EXIT_GRACE_EXCEEDED = "exit_grace_exceeded"
    UNSUPPORTED_OUTCOME_ACTION = "unsupported_outcome_action"
    MISSING_INPUT_BUNDLE = "missing_input_bundle"
    MISSING_PROMPT_BUNDLE = "missing_prompt_bundle"
    MISSING_BUDGET = "missing_budget"
    DIRTY_WORKTREE = "dirty_worktree"
    PROVIDER_DISALLOWED = "provider_disallowed"
    MODEL_DISALLOWED = "model_disallowed"
    CAPTURED_INPUT_MISMATCH = "captured_input_mismatch"
    MISSING_NONDETERMINISM_POLICY = "missing_nondeterminism_policy"
    LIVE_EXECUTION_UNAVAILABLE = "live_execution_unavailable"


@unique
class FailureProbe(StrEnum):
    PARSER_DRIFT = "parser_drift"
    RECOMPUTE_DRIFT = "recompute_drift"
    MALFORMED_INPUT = "malformed_input"
    INELIGIBLE_RECORD = "ineligible_record"


@dataclass(frozen=True, slots=True)
class RetainedRawResult:
    perspective: str
    raw_json: str


@dataclass(frozen=True, slots=True)
class RetainedMeasurement:
    state: MeasurementState
    action: Action
    horizon: int
    entry_session: date
    target_exit_session: date
    actual_exit_session: date
    actual_exit_session_offset: int
    instrument_entry_close: float
    instrument_actual_exit_close: float
    benchmark_entry_close: float
    benchmark_target_exit_close: float
    execution_cost_return: float
    calendar_provenance: ContentHash | None
    price_provenance: ContentHash | None
    benchmark_provenance: ContentHash | None
    corporate_action_provenance: ContentHash | None


@dataclass(frozen=True, slots=True)
class VerbatimReplayRecord:
    record_id: str
    native_v4: bool
    data_cutoff_at: str | None
    prompt_json: str | None
    raw_results: tuple[RetainedRawResult, ...]
    parser_version: ParserVersion | None
    stored_parsed_hash: ContentHash
    fixed_perspective_order: bool


@dataclass(frozen=True, slots=True)
class OutcomeReplayRecord:
    record_id: str
    measurement: RetainedMeasurement
    denominator_eligible: bool


@dataclass(frozen=True, slots=True)
class RecomputeReplayRecord:
    record_id: str
    native_v4: bool
    data_cutoff_at: str | None
    retained_input_hash: ContentHash | None
    prompt_bundle_hash: ContentHash | None
    stored_output_hash: ContentHash
    captured_input_hash: ContentHash | None
    captured_output_json: str | None
    provider: str
    model: str
    max_cost_usd: float
    clean_worktree: bool
    provider_allowed: bool
    model_allowed: bool
    nondeterminism_note: str | None


type ReplayRecord = VerbatimReplayRecord | OutcomeReplayRecord | RecomputeReplayRecord


@dataclass(frozen=True, slots=True)
class ReplayEligibility:
    mode: ReplayMode
    eligible: bool
    reasons: tuple[IneligibilityReason, ...]


@dataclass(frozen=True, slots=True)
class ReplayComputation:
    result: JsonValue | None
    probes: tuple[FailureProbe, ...]


@dataclass(frozen=True, slots=True)
class ReplayContractError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return f"replay contract violation: {self.detail}"


@dataclass(frozen=True, slots=True)
class ReplayParseError(Exception):
    record_id: str

    @override
    def __str__(self) -> str:
        return f"retained raw result is malformed: {self.record_id}"


def replay_mode(record: ReplayRecord) -> ReplayMode:
    match record:
        case VerbatimReplayRecord():
            return ReplayMode.VERBATIM
        case OutcomeReplayRecord():
            return ReplayMode.OUTCOME
        case RecomputeReplayRecord():
            return ReplayMode.RECOMPUTE
        case unreachable:
            assert_never(unreachable)


def _parse_verbatim(record: VerbatimReplayRecord) -> ReplayComputation:
    match record.parser_version:
        case ParserVersion.PERSPECTIVE_V1:
            pass
        case None:
            raise ReplayParseError(record.record_id)
        case unreachable:
            assert_never(unreachable)
    try:
        parsed: list[JsonValue] = [
            {"perspective": raw.perspective, **_OBJECT.validate_json(raw.raw_json)}
            for raw in record.raw_results
        ]
    except ValidationError as error:
        raise ReplayParseError(record.record_id) from error
    output_hash = canonical_hash(parsed)
    drift = output_hash != record.stored_parsed_hash
    result: JsonValue = {
        "parsed_equal": not drift,
        "stored_parsed_hash": record.stored_parsed_hash,
        "replayed_parsed_hash": output_hash,
        "parser_version": record.parser_version.value if record.parser_version is not None else None,
    }
    return ReplayComputation(result, (FailureProbe.PARSER_DRIFT,) if drift else ())


def replay_record(record: ReplayRecord) -> ReplayComputation:
    match record:
        case VerbatimReplayRecord() as item:
            return _parse_verbatim(item)
        case OutcomeReplayRecord() as item:
            measured = item.measurement
            instrument = measured.instrument_actual_exit_close / measured.instrument_entry_close - 1
            benchmark = measured.benchmark_target_exit_close / measured.benchmark_entry_close - 1
            match measured.action:
                case Action.BUY:
                    direction = 1.0
                case Action.SELL:
                    direction = -1.0
                case Action.HOLD:
                    observed_excess = instrument - benchmark
                    return ReplayComputation({"action": measured.action.value, "horizon": measured.horizon, "entry_session": measured.entry_session.isoformat(), "target_exit_session": measured.target_exit_session.isoformat(), "actual_exit_session": measured.actual_exit_session.isoformat(), "actual_exit_session_offset": measured.actual_exit_session_offset, "gross_absolute_return": instrument, "gross_benchmark_excess_return": 0.0, "net_execution_return": None, "net_execution_benchmark_excess_return": None, "hold_opportunity_cost": max(observed_excess, 0), "hold_avoided_loss": max(-observed_excess, 0)}, ())
                case Action.BLOCKED | Action.CANDIDATE_REJECTED:
                    raise ReplayContractError("outcome action is not replayable")
                case unreachable:
                    assert_never(unreachable)
            directional_return = direction * instrument
            directional_benchmark = direction * benchmark
            directional_excess = directional_return - directional_benchmark
            net = directional_return - measured.execution_cost_return
            net_excess = net - directional_benchmark
            outcome_result: JsonValue = {"action": measured.action.value, "horizon": measured.horizon, "entry_session": measured.entry_session.isoformat(), "target_exit_session": measured.target_exit_session.isoformat(), "actual_exit_session": measured.actual_exit_session.isoformat(), "actual_exit_session_offset": measured.actual_exit_session_offset, "gross_absolute_return": instrument, "gross_benchmark_excess_return": directional_excess, "net_execution_return": net, "net_execution_benchmark_excess_return": net_excess}
            return ReplayComputation(outcome_result, ())
        case RecomputeReplayRecord() as item:
            try:
                output = _JSON.validate_json(item.captured_output_json or "")
            except ValidationError as error:
                raise ReplayParseError(item.record_id) from error
            drift = canonical_hash(output) != item.stored_output_hash
            recompute_result: JsonValue = {
                "captured_input_equal": item.captured_input_hash == item.retained_input_hash,
                "drift": drift,
                "captured_output_hash": canonical_hash(output),
                "provider": item.provider,
                "model": item.model,
            }
            probes = (FailureProbe.RECOMPUTE_DRIFT,) if drift else ()
            return ReplayComputation(recompute_result, probes)
        case unreachable:
            assert_never(unreachable)
