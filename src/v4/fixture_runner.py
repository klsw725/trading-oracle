from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, override

from pydantic import TypeAdapter

from .attribution import AttributionLedger, CandidateInventoryRecorded, CandidateSeen, CorrectedBy, CorrectionRecorded, FillId, FillRecorded, LedgerId, OperatorDecisionRecorded, OrderLinked, OutcomeMatured, PositionClosed, TerminalAttribution
from .attribution_models import IntegrityRule, LifecycleIntegrityError
from .calibration import build_calibration_samples, calculate_calibration, calculate_non_policy_acceptance_arithmetic, group_calibration_samples
from .calibration_models import AttributionSchemaVersion, CalibrationCohortKey, CalibrationConfig, CalibrationObservation, CalibrationContractVersion, Exchange, PromptBundleVersion, Regime, SampleId, ScorerVersion, SnapshotSchemaVersion, WeightsVersion
from .fixture_evidence import evidence_report as run_evidence
from .fixture_support import snapshot_report
from .legacy import EXPECTED_SOURCE_COUNT, LegacyProvenance, build_legacy_derived_audit, inventory_legacy_sources
from .legacy_artifacts import LegacyArtifactWriteRequest, write_legacy_artifacts
from .market_context import MarketContext, parse_market_context
from .measurement import measure, parse_measurement_request
from .models import Action, CandidateId, ContentHash, JsonValue, Market, MeasurementState, OrderId, PortfolioTradeId, RecommendationId, ReplayMode, canonical_hash, canonical_json
from .replay import OutcomeReplayRecord, ParserVersion, RecomputeReplayRecord, ReplayRecord, RetainedMeasurement, RetainedRawResult, VerbatimReplayRecord
from .replay_workflow import ReplayRequest, WorkflowState, execute_replay

_JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@dataclass(frozen=True, slots=True)
class FixtureParseError(Exception):
    field: str
    expected: str

    @override
    def __str__(self) -> str:
        return f"{self.field} must be {self.expected}"


def load_fixture(path: Path) -> Mapping[str, JsonValue]:
    return _record(_JSON.validate_json(path.read_bytes()), "fixture")


def _record(value: JsonValue, field: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict): raise FixtureParseError(field, "an object")
    return value


def _records(value: JsonValue, field: str) -> Sequence[Mapping[str, JsonValue]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value): raise FixtureParseError(field, "an array of objects")
    return tuple(item for item in value if isinstance(item, dict))


def _text(raw: Mapping[str, JsonValue], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str): raise FixtureParseError(field, "a string")
    return value


def _number(raw: Mapping[str, JsonValue], field: str) -> int | float:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int | float): raise FixtureParseError(field, "numeric")
    return value


def _numbers(value: JsonValue, field: str) -> tuple[int | float, ...]:
    if not isinstance(value, list) or not all(not isinstance(item, bool) and isinstance(item, int | float) for item in value): raise FixtureParseError(field, "a numeric array")
    return tuple(item for item in value if not isinstance(item, bool) and isinstance(item, int | float))


def _section(root: Mapping[str, JsonValue], field: str) -> Mapping[str, JsonValue]:
    return _record(root[field], field)


def _contexts(root: Mapping[str, JsonValue]) -> dict[str, MarketContext]:
    return {name: parse_market_context(_record(raw, f"market_contexts.{name}")) for name, raw in _section(root, "market_contexts").items()}


def market_context_report(root: Mapping[str, JsonValue]) -> JsonValue:
    contexts = _contexts(root); mappings: list[JsonValue] = []
    for name, context in contexts.items():
        mappings.append({"ref": name, "market": context.market.value, "exchange": context.exchange.value, "calendar_id": str(context.calendar_id), "timezone": str(context.timezone), "quote_currency": str(context.quote_currency), "benchmark_id": str(context.benchmark_id)})
    exchanges = {str(item["exchange"]) for item in mappings if isinstance(item, dict)}
    return {"state": "pass" if exchanges == {"KOSPI", "KOSDAQ", "NASDAQ", "NYSE"} else "fail", "exchange_mappings": mappings}


def measurement_report(root: Mapping[str, JsonValue]) -> JsonValue:
    contexts = _contexts(root); cases: list[JsonValue] = []; passed = True
    for raw in _records(_section(root, "measurement")["cases"], "measurement.cases"):
        context = contexts[_text(raw, "market_context_ref")]; request = parse_measurement_request(raw, context); result = measure(request); expected = _record(raw["expected"], "measurement.expected")
        matches = result.state.value == _text(expected, "state")
        observed: dict[str, JsonValue] = {"fixture_id": _text(raw, "fixture_id"), "state": result.state.value, "entry_session": result.entry_session.session_date.isoformat() if result.entry_session else None, "target_exit_session": result.target_exit_session.session_date.isoformat() if result.target_exit_session else None, "actual_exit_session": result.actual_exit_session.session_date.isoformat() if result.actual_exit_session else None, "price_lag_sessions": result.price_lag_sessions, "closed_sessions_after_entry": result.closed_sessions_after_entry, "remaining_sessions": result.remaining_sessions, "reason": result.reason}
        for field in ("entry_session", "target_exit_session", "actual_exit_session", "price_lag_sessions", "closed_sessions_after_entry", "remaining_sessions"):
            if field in expected: matches = matches and observed[field] == expected[field]
        metrics = (("gross_absolute_return", result.gross_absolute_return.value), ("gross_benchmark_excess_return", result.gross_benchmark_excess_return.value), ("net_execution_return", result.net_execution_return.value), ("net_execution_benchmark_excess_return", result.net_execution_benchmark_excess_return.value))
        for field, value in metrics:
            observed[field] = value
            if field in expected: matches = matches and value is not None and abs(value - float(_number(expected, field))) < 1e-12
        probes: list[JsonValue] = []
        if request.instrument_prices is not None:
            stale = measure(replace(request, instrument_prices=replace(request.instrument_prices, as_of=request.emitted_at)))
            probes = [stale.reason]; matches = matches and probes == ["price_or_corporate_action_provenance_stale"]
            if request.instrument_prices.actual_exit_session is not None:
                benchmark_actual = measure(replace(request, benchmark_prices=replace(request.benchmark_prices, actual_exit_session=request.instrument_prices.actual_exit_session) if request.benchmark_prices else None))
                probes.append(benchmark_actual.reason); matches = matches and probes[-1] == "benchmark_must_remain_bound_to_target_session"
        observed["negative_probes"] = probes; observed["passed"] = matches; cases.append(observed); passed = passed and matches
    return {"state": "pass" if passed else "fail", "cases": cases}


def legacy_report(source_root: Path) -> JsonValue:
    inventory = inventory_legacy_sources(source_root.glob("*.json")); audits = tuple(build_legacy_derived_audit(item) for item in inventory.records)
    deterministic = all(audit == build_legacy_derived_audit(item) for audit, item in zip(audits, inventory.records, strict=True)); generated = datetime.now().astimezone()
    with TemporaryDirectory(prefix="trading-oracle-v4-legacy-") as directory:
        first = write_legacy_artifacts(LegacyArtifactWriteRequest(inventory, Path(directory), generated.isoformat()))
        second = write_legacy_artifacts(LegacyArtifactWriteRequest(inventory, Path(directory), (generated + timedelta(seconds=1)).isoformat()))
        rerun_ok = first.artifact_set_id == second.artifact_set_id and first.run_id != second.run_id and first.manifest_path != second.manifest_path
        content_addressed = all(str(first.artifact_set_id) in item.path.name or ".legacy_snap_" in item.path.name or item.path == first.manifest_path for item in first.writes)
    empty = inventory_legacy_sources(()); market_covered = all(item.source_market.provenance is LegacyProvenance.DIRECT for item in inventory.records)
    passed = len(inventory.records) == EXPECTED_SOURCE_COUNT and inventory.coverage_complete and deterministic and rerun_ok and content_addressed and market_covered and not empty.coverage_complete
    return {"state": "pass" if passed else "fail", "source_count": len(inventory.records), "source_hashes": [item.source_hash for item in inventory.records], "artifact_set_id": first.artifact_set_id, "rerun_conflict_free": rerun_ok, "content_addressed": content_addressed, "market_coverage_complete": market_covered, "empty_root_state": "fail" if not empty.coverage_complete else "pass"}


def attribution_report(root: Mapping[str, JsonValue]) -> JsonValue:
    raw_records = _records(_section(root, "attribution")["records"], "attribution.records"); recorded = datetime.fromisoformat(_text(_section(root, "clock"), "recommendation_emitted_at")); ids = tuple(CandidateId(_text(item, "candidate_id")) for item in raw_records)
    ledger = AttributionLedger(LedgerId("ledger_v4_offline")).append(CandidateInventoryRecorded.create(ids), recorded, recorded)
    for candidate_id in ids: ledger = ledger.append(CandidateSeen(candidate_id), recorded, recorded)
    first_terminal_event = None
    for raw, candidate_id in zip(raw_records, ids, strict=True):
        recommendation = raw.get("recommendation_id"); confidence = raw.get("confidence_probability"); action = Action(_text(raw, "action"))
        terminal = TerminalAttribution(candidate_id, RecommendationId(recommendation) if isinstance(recommendation, str) else None, _text(raw, "ticker"), action, float(confidence) if isinstance(confidence, int | float) else None, tuple(int(value) for value in _numbers(raw["horizons"], "horizons")))
        ledger = ledger.append(terminal, recorded, recorded); first_terminal_event = first_terminal_event or ledger.events[-1]
        operator = raw.get("operator_decision"); linkage = _record(raw["portfolio_linkage"], "portfolio_linkage")
        if isinstance(operator, dict) and terminal.recommendation_id is not None:
            ledger = ledger.append(OperatorDecisionRecorded(candidate_id, terminal.recommendation_id, _text(operator, "state")), recorded, recorded)
            trade = linkage.get("portfolio_trade_id"); orders = linkage.get("order_ids"); fills = linkage.get("fill_ids")
            if isinstance(trade, str) and isinstance(orders, list) and isinstance(fills, list) and orders and fills and isinstance(orders[0], str) and isinstance(fills[0], str):
                order = OrderId(orders[0]); trade_id = PortfolioTradeId(trade); ledger = ledger.append(OrderLinked(candidate_id, order, trade_id), recorded, recorded); ledger = ledger.append(FillRecorded(candidate_id, order, FillId(fills[0])), recorded, recorded); ledger = ledger.append(PositionClosed(candidate_id, trade_id), recorded, recorded); ledger = ledger.append(OutcomeMatured(candidate_id, terminal.recommendation_id, 5), recorded, recorded)
    if first_terminal_event is None: raise FixtureParseError("attribution.records", "non-empty")
    old_confidence = first_terminal_event.payload.confidence_probability if isinstance(first_terminal_event.payload, TerminalAttribution) else None
    correction = CorrectionRecorded(ids[0], first_terminal_event.event_id, "confidence_probability", canonical_hash(old_confidence), 0.8, "fixture correction", CorrectedBy("independent-fixture-reviewer")); ledger = ledger.append(correction, recorded, recorded)
    ledger.validate_chain(); ledger.reconcile_candidates(); summary = ledger.denominator_summary(); effective = ledger.effective_value(first_terminal_event.event_id, "confidence_probability")
    observed: JsonValue = {"BUY": summary.buy, "SELL": summary.sell, "HOLD": summary.hold, "BLOCKED": summary.blocked, "CANDIDATE_REJECTED": summary.candidate_rejected, "decision_quality_total": summary.decision_quality_total, "execution_quality_total": summary.execution_quality_total, "selection_quality_total": summary.selection_quality_total}
    hold = next(item for item in raw_records if item.get("action") == "HOLD")
    try:
        _ = ledger.append(OperatorDecisionRecorded(CandidateId(_text(hold, "candidate_id")), RecommendationId(_text(hold, "recommendation_id")), "accepted"), recorded, recorded)
        hold_accepted_rejected = False
    except LifecycleIntegrityError as error:
        hold_accepted_rejected = error.rule is IntegrityRule.INVALID_OPERATOR_DECISION
    passed = observed == _section(_section(root, "attribution"), "expected_denominator") and effective == 0.8 and hold_accepted_rejected
    return {"state": "pass" if passed else "fail", "denominator": observed, "event_count": len(ledger.events), "inventory_count": len(ids), "corrected_confidence": effective, "ledger_tail_hash": ledger.events[-1].event_hash, "hold_accepted_rejected": hold_accepted_rejected}


def _retained(item: Mapping[str, JsonValue]) -> RetainedMeasurement:
    hashes = tuple(canonical_hash({"source": name}) for name in ("calendar", "price", "benchmark", "corporate"))
    return RetainedMeasurement(MeasurementState.MATURED, Action(_text(item, "action")), int(_number(item, "horizon")), date.fromisoformat(_text(item, "entry_session")), date.fromisoformat(_text(item, "target_exit_session")), date.fromisoformat(_text(item, "actual_exit_session")), int(_number(item, "actual_exit_session_offset")), float(_number(item, "instrument_entry_close")), float(_number(item, "instrument_exit_close")), float(_number(item, "benchmark_entry_close")), float(_number(item, "benchmark_exit_close")), float(_number(item, "execution_cost_return")), *hashes)


def replay_report(root: Mapping[str, JsonValue]) -> JsonValue:
    raw = _section(root, "replay"); records: list[ReplayRecord] = []
    verbatim = _record(raw["verbatim"], "replay.verbatim"); retained_raw = tuple(RetainedRawResult(_text(item, "perspective"), _text(item, "raw_json")) for item in _records(verbatim["raw_results"], "raw_results")); records.append(VerbatimReplayRecord("verbatim", True, _text(verbatim, "data_cutoff_at"), _text(verbatim, "prompt_json"), retained_raw, ParserVersion.PERSPECTIVE_V1, ContentHash(_text(verbatim, "stored_parsed_hash")), True))
    outcomes = tuple(OutcomeReplayRecord(f"outcome-{_text(item, 'action').lower()}", _retained(item), True) for item in _records(raw["outcomes"], "replay.outcomes")); records.extend(outcomes)
    recompute_raw = _record(raw["recompute"], "recompute"); input_hash = canonical_hash({"fixture": "recompute"}); output: JsonValue = {"verdict": recompute_raw["captured_verdict"]}; records.append(RecomputeReplayRecord("recompute", True, _text(recompute_raw, "data_cutoff_at"), input_hash, canonical_hash({"prompt": 1}), canonical_hash({"verdict": recompute_raw["stored_verdict"]}), input_hash, canonical_json(output).decode(), "offline", "fixture", 1.25, True, True, True, "offline deterministic"))
    results: list[dict[str, JsonValue]] = []
    for record in records:
        mode = ReplayMode.VERBATIM if isinstance(record, VerbatimReplayRecord) else ReplayMode.RECOMPUTE if isinstance(record, RecomputeReplayRecord) else ReplayMode.OUTCOME
        execution = execute_replay(ReplayRequest(mode, f"idem-{record.record_id}", (record,))); artifact = execution.artifacts[0]
        results.append({"record_id": record.record_id, "eligible": artifact.eligible, "state": execution.workflow_state.value, "transition_count": len(execution.transitions), "result": artifact.result, "failure_probes": [probe.value for probe in artifact.failure_probes]})
    checkpoint_request = ReplayRequest(ReplayMode.OUTCOME, _text(raw, "idempotency_key"), outcomes); partial = execute_replay(checkpoint_request, max_transitions=3); resumed = execute_replay(checkpoint_request, checkpoint=partial.checkpoint); repeated = execute_replay(checkpoint_request, checkpoint=partial.checkpoint)
    successful = tuple(item for item in results if item["record_id"] != "recompute")
    drift = next(item for item in results if item["record_id"] == "recompute")
    outcomes_by_action = {str(_record(item["result"], "result")["action"]): _record(item["result"], "result") for item in results if str(item["record_id"]).startswith("outcome-")}
    sell_absolute = outcomes_by_action["SELL"]["gross_absolute_return"]
    hold_absolute = outcomes_by_action["HOLD"]["gross_absolute_return"]
    action_independent = (
        isinstance(sell_absolute, int | float)
        and isinstance(hold_absolute, int | float)
        and isclose(float(sell_absolute), -0.05, abs_tol=1e-12)
        and isclose(float(hold_absolute), -0.05, abs_tol=1e-12)
    )
    drift_failed = drift["eligible"] is False and drift["state"] == WorkflowState.REPORT_FAILED.value and drift["failure_probes"] == ["recompute_drift"]
    passed = all(item["eligible"] is True and item["state"] == WorkflowState.REPORT_WRITTEN.value for item in successful) and action_independent and drift_failed and partial.workflow_state is WorkflowState.SIGNAL_EVALUATED and partial.checkpoint.cancelled and resumed == repeated and resumed.complete
    result: dict[str, JsonValue] = {"state": "pass" if passed else "fail", "records": list(results), "modes": [mode.value for mode in ReplayMode], "action_independent_absolute_return": action_independent, "drift_failure_rejected": drift_failed, "checkpoint_state": partial.workflow_state.value, "checkpoint_input_hash": partial.input_hash, "transition_count": len(resumed.transitions), "idempotent": resumed == repeated, "output_hash": resumed.output_hash}
    return result


def calibration_report(root: Mapping[str, JsonValue]) -> JsonValue:
    raw = _section(root, "calibration"); horizon = int(_number(raw, "horizon")); config = CalibrationConfig(bucket_edges=tuple(Decimal(str(value)) for value in _numbers(raw["bucket_edges"], "bucket_edges"))); observations: list[CalibrationObservation] = []
    for item in _records(raw["observations"], "calibration.observations"):
        action = Action(_text(item, "action")); cohort = CalibrationCohortKey(CalibrationContractVersion("v4.phase28.1"), SnapshotSchemaVersion("v4.snapshot.phase23.1"), AttributionSchemaVersion("v4.phase26.1"), Market(_text(item, "market")), Exchange(_text(item, "exchange")), action, horizon, PromptBundleVersion("fixture-prompt-1"), ScorerVersion("maxs-lite.v1"), WeightsVersion("equal.v1"), Regime("fixture"), Regime("fixture"))
        observations.append(CalibrationObservation(SampleId(_text(item, "sample_id")), cohort, Decimal(str(_number(item, "confidence_probability"))), MeasurementState.MATURED, Decimal(str(_number(item, "instrument_return"))), Decimal(str(_number(item, "benchmark_return"))), held_position_sell_eligible=bool(item.get("held_position_sell_eligible")), sample_weight=Decimal(str(_number(item, "sample_weight")))))
    construction = build_calibration_samples(tuple(observations), config); cohort_reports = tuple(calculate_calibration(group.samples, config) for group in group_calibration_samples(construction.samples)); arithmetic = calculate_non_policy_acceptance_arithmetic(cohort_reports, config); expected = _record(raw["expected"], "calibration.expected")
    states = [report.state for report in cohort_reports]; passed = states == ["insufficient_sample_no_op"] * 3 and arithmetic.brier_score == Decimal(str(_number(expected, "brier_score"))) and arithmetic.ece == Decimal(str(_number(expected, "ece")))
    result: dict[str, JsonValue] = {"state": "pass" if passed else "fail", "cohort_states": list(states), "sample_count": arithmetic.sample_count, "weighted_count": float(arithmetic.weighted_count), "brier_score": float(arithmetic.brier_score), "ece": float(arithmetic.ece), "purpose": arithmetic.purpose, "derived_labels": [item.correctness_label for item in construction.samples], "derived_outcomes": [item.correctness_outcome for item in construction.samples]}
    return result


def _domain_reports(root: Mapping[str, JsonValue], source_root: Path) -> dict[str, JsonValue]:
    return {"phase22": measurement_report(root), "phase23": snapshot_report(root), "phase24": legacy_report(source_root), "phase25": market_context_report(root), "phase26": attribution_report(root), "phase27": replay_report(root), "phase28": calibration_report(root)}


def evidence_report(root: Mapping[str, JsonValue], provenance: str) -> JsonValue:
    return run_evidence(root, _domain_reports(root, Path("data/snapshots")), provenance)


def verify_fixture(root: Mapping[str, JsonValue], source_root: Path) -> JsonValue:
    reports = _domain_reports(root, source_root); reports["phase29"] = run_evidence(root, reports, "complete"); passed = all(_record(value, name)["state"] == "pass" for name, value in reports.items())
    return {"state": "pass" if passed else "fail", "schema_version": root.get("schema_version"), "checks": reports}
