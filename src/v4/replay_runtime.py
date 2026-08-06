# pyright: reportUnnecessaryComparison=false

from dataclasses import dataclass
from typing import assert_never

from src.v4.models import Action, ContentHash, JsonValue, MeasurementState, canonical_hash
from src.v4.replay import (
    FailureProbe,
    IneligibilityReason,
    OutcomeReplayRecord,
    RecomputeReplayRecord,
    ReplayEligibility,
    ReplayParseError,
    ReplayRecord,
    VerbatimReplayRecord,
    PERSPECTIVE_ORDER,
    replay_mode,
    replay_record,
)


@dataclass(frozen=True, slots=True)
class ReplayArtifact:
    record_id: str
    eligible: bool
    reasons: tuple[IneligibilityReason, ...]
    result: JsonValue | None
    failure_probes: tuple[FailureProbe, ...]
    artifact_hash: ContentHash


def _missing(
    reasons: list[IneligibilityReason],
    condition: bool,
    reason: IneligibilityReason,
) -> None:
    if not condition:
        reasons.append(reason)


def evaluate_eligibility(record: ReplayRecord) -> ReplayEligibility:
    reasons: list[IneligibilityReason] = []
    match record:
        case VerbatimReplayRecord() as item:
            _missing(reasons, item.native_v4, IneligibilityReason.LEGACY_SNAPSHOT)
            _missing(reasons, item.data_cutoff_at is not None, IneligibilityReason.MISSING_DATA_CUTOFF)
            _missing(reasons, item.prompt_json is not None, IneligibilityReason.MISSING_PROMPT)
            _missing(reasons, bool(item.raw_results), IneligibilityReason.MISSING_RAW_RESULT)
            _missing(reasons, item.parser_version is not None, IneligibilityReason.MISSING_PARSER_VERSION)
            order = tuple(raw.perspective for raw in item.raw_results)
            valid_order = item.fixed_perspective_order and order == PERSPECTIVE_ORDER
            _missing(reasons, valid_order, IneligibilityReason.INVALID_PERSPECTIVE_ORDER)
        case OutcomeReplayRecord() as item:
            measured = item.measurement
            _missing(reasons, measured.state is MeasurementState.MATURED, IneligibilityReason.OUTCOME_NOT_MATURED)
            _missing(reasons, measured.horizon > 0, IneligibilityReason.MALFORMED_MEASUREMENT)
            sessions_valid = measured.entry_session < measured.target_exit_session
            _missing(reasons, sessions_valid, IneligibilityReason.MALFORMED_MEASUREMENT)
            offset = measured.actual_exit_session_offset
            date_relation = measured.actual_exit_session >= measured.target_exit_session
            offset_relation = (offset == 0) == (measured.actual_exit_session == measured.target_exit_session)
            _missing(reasons, offset >= 0 and date_relation and offset_relation, IneligibilityReason.SESSION_MISMATCH)
            _missing(reasons, offset <= 5, IneligibilityReason.EXIT_GRACE_EXCEEDED)
            closes = (
                measured.instrument_entry_close,
                measured.instrument_actual_exit_close,
                measured.benchmark_entry_close,
                measured.benchmark_target_exit_close,
            )
            prices_valid = min(closes) > 0 and measured.execution_cost_return >= 0
            _missing(reasons, prices_valid, IneligibilityReason.MALFORMED_MEASUREMENT)
            provenance = (
                measured.calendar_provenance,
                measured.price_provenance,
                measured.benchmark_provenance,
                measured.corporate_action_provenance,
            )
            _missing(reasons, all(provenance), IneligibilityReason.MISSING_OUTCOME_PROVENANCE)
            _missing(reasons, item.denominator_eligible, IneligibilityReason.MISSING_DENOMINATOR)
            match measured.action:
                case Action.BUY | Action.SELL | Action.HOLD:
                    pass
                case Action.BLOCKED | Action.CANDIDATE_REJECTED:
                    reasons.append(IneligibilityReason.UNSUPPORTED_OUTCOME_ACTION)
                case unreachable:
                    assert_never(unreachable)
        case RecomputeReplayRecord() as item:
            _missing(reasons, item.native_v4, IneligibilityReason.LEGACY_SNAPSHOT)
            _missing(reasons, item.data_cutoff_at is not None, IneligibilityReason.MISSING_DATA_CUTOFF)
            _missing(reasons, item.retained_input_hash is not None, IneligibilityReason.MISSING_INPUT_BUNDLE)
            _missing(reasons, item.prompt_bundle_hash is not None, IneligibilityReason.MISSING_PROMPT_BUNDLE)
            _missing(reasons, item.max_cost_usd > 0, IneligibilityReason.MISSING_BUDGET)
            _missing(reasons, item.clean_worktree, IneligibilityReason.DIRTY_WORKTREE)
            _missing(reasons, item.provider_allowed, IneligibilityReason.PROVIDER_DISALLOWED)
            _missing(reasons, item.model_allowed, IneligibilityReason.MODEL_DISALLOWED)
            _missing(reasons, item.nondeterminism_note is not None, IneligibilityReason.MISSING_NONDETERMINISM_POLICY)
            captured = item.captured_input_hash is not None and item.captured_output_json is not None
            _missing(reasons, captured, IneligibilityReason.LIVE_EXECUTION_UNAVAILABLE)
            if item.retained_input_hash is not None and item.captured_input_hash is not None:
                same_input = item.retained_input_hash == item.captured_input_hash
                _missing(reasons, same_input, IneligibilityReason.CAPTURED_INPUT_MISMATCH)
        case unreachable:
            assert_never(unreachable)
    return ReplayEligibility(replay_mode(record), not reasons, tuple(reasons))


def record_seed(record: ReplayRecord) -> JsonValue:
    match record:
        case VerbatimReplayRecord() as item:
            return {"id": item.record_id, "mode": "verbatim", "native": item.native_v4, "cutoff": item.data_cutoff_at, "prompt": item.prompt_json, "raw": [{"perspective": raw.perspective, "json": raw.raw_json} for raw in item.raw_results], "parser": item.parser_version, "stored": item.stored_parsed_hash, "order": item.fixed_perspective_order}
        case OutcomeReplayRecord() as item:
            measured = item.measurement
            return {"id": item.record_id, "mode": "outcome", "state": measured.state, "action": measured.action, "horizon": measured.horizon, "sessions": [measured.entry_session.isoformat(), measured.target_exit_session.isoformat(), measured.actual_exit_session.isoformat(), measured.actual_exit_session_offset], "closes": [measured.instrument_entry_close, measured.instrument_actual_exit_close, measured.benchmark_entry_close, measured.benchmark_target_exit_close], "cost": measured.execution_cost_return, "provenance": [measured.calendar_provenance, measured.price_provenance, measured.benchmark_provenance, measured.corporate_action_provenance], "denominator": item.denominator_eligible}
        case RecomputeReplayRecord() as item:
            return {"id": item.record_id, "mode": "recompute", "native": item.native_v4, "cutoff": item.data_cutoff_at, "input": item.retained_input_hash, "prompt": item.prompt_bundle_hash, "stored": item.stored_output_hash, "captured_input": item.captured_input_hash, "captured_output": item.captured_output_json, "provider": item.provider, "model": item.model, "budget": item.max_cost_usd, "clean": item.clean_worktree, "provider_allowed": item.provider_allowed, "model_allowed": item.model_allowed, "nondeterminism": item.nondeterminism_note}
        case unreachable:
            assert_never(unreachable)


def replay_artifact(record: ReplayRecord) -> ReplayArtifact:
    eligibility = evaluate_eligibility(record)
    result: JsonValue | None = None
    probes: tuple[FailureProbe, ...]
    if eligibility.eligible:
        try:
            computation = replay_record(record)
            result, probes = computation.result, computation.probes
        except ReplayParseError:
            probes = (FailureProbe.MALFORMED_INPUT,)
    else:
        probes = (FailureProbe.INELIGIBLE_RECORD,)
    eligible = eligibility.eligible and not probes
    seed: JsonValue = {"record": record_seed(record), "eligible": eligible, "reasons": [reason.value for reason in eligibility.reasons], "result": result, "probes": [probe.value for probe in probes]}
    return ReplayArtifact(record.record_id, eligible, eligibility.reasons, result, probes, canonical_hash(seed))
