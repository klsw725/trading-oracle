from datetime import timedelta
from decimal import Decimal
from typing import Literal

from src.v4.models import canonical_hash

from .models import ExistingPerspective
from .offline_evidence import FrozenEvaluationInput, RepeatRun, SampleBatchBody, SampleBatchRecord, boundary_json, expected_input_hash
from .offline_models import BaselineKind, MutationName, OfflineCode


def _record(body: SampleBatchBody) -> SampleBatchRecord:
    shell = SampleBatchRecord(body=body, record_hash=f"sha256:{'0' * 64}")
    return shell.model_copy(update={"record_hash": canonical_hash(boundary_json(body))})


def seal_input(value: FrozenEvaluationInput, records: tuple[SampleBatchRecord, ...], reported: OfflineCode, repeat_codes: tuple[OfflineCode, ...] | None = None) -> FrozenEvaluationInput:
    manifest_body = value.manifest.body.model_copy(update={"record_hashes": tuple(record.record_hash for record in records)})
    manifest = value.manifest.model_copy(update={"body": manifest_body, "manifest_hash": canonical_hash(boundary_json(manifest_body))})
    shell = value.model_copy(update={"manifest": manifest, "records": records, "input_hash": f"sha256:{'0' * 64}", "reported_terminal_code": reported, "repeated_runs": ()})
    input_hash = expected_input_hash(shell)
    codes = repeat_codes if repeat_codes is not None else tuple(run.terminal_code for run in value.repeated_runs)
    repeats = tuple(RepeatRun(run_index=index, input_hash=input_hash, config_hash=value.config.config_hash, terminal_code=code) for index, code in enumerate(codes, 1))
    return shell.model_copy(update={"input_hash": input_hash, "repeated_runs": repeats})


def _with_edges(body: SampleBatchBody, mode: Literal["harm", "no_lift"]) -> SampleBatchBody:
    consensus = next(Decimal(item.edge) for item in body.outcome.baseline_edges if item.kind is BaselineKind.CONSENSUS)
    current = body.outcome.candidate_edge
    if current is None:
        return body
    match mode:  # noqa: MATCH_OK - internal closed mutation mode
        case "harm":
            candidate = consensus - Decimal("0.030000")
        case "no_lift":
            candidate = consensus
    outcome = body.outcome.model_copy(update={"candidate_edge": f"{candidate:.6f}"})
    ablation = body.ablation.model_copy(update={"remove_novel_observations_edge": f"{candidate - Decimal('0.012000'):.6f}", "existing_signal_only_edge": f"{consensus + Decimal('0.002000'):.6f}", "shuffled_candidate_edge": f"{consensus + Decimal('0.000500'):.6f}"})
    candidate_output = body.candidate.model_copy(update={"confidence": "0.050000"}) if mode == "no_lift" else body.candidate
    return body.model_copy(update={"outcome": outcome, "ablation": ablation, "candidate": candidate_output})


def _clone(body: SampleBatchBody) -> SampleBatchBody:
    candidate_edge = body.outcome.candidate_edge
    if candidate_edge is None:
        return body
    predictions = tuple(item.model_copy(update={"verdict_direction": body.candidate.verdict_direction}) if item.perspective is ExistingPerspective.QUANT else item for item in body.perspectives)
    edges = tuple(item.model_copy(update={"edge": candidate_edge}) if item.perspective is ExistingPerspective.QUANT else item for item in body.outcome.perspective_edges)
    return body.model_copy(update={"perspectives": predictions, "outcome": body.outcome.model_copy(update={"perspective_edges": edges})})


def mutate_evidence(value: FrozenEvaluationInput, name: MutationName) -> FrozenEvaluationInput:
    records = value.records
    match name:  # noqa: MATCH_OK - every MutationName member is explicit
        case MutationName.STALE:
            body = records[0].body.model_copy(update={"feature_generated_at": value.manifest.body.feature_cutoff + timedelta(seconds=1)})
            return seal_input(value, (_record(body), *records[1:]), OfflineCode.MALFORMED)
        case MutationName.DIRTY:
            return value.model_copy(update={"manifest": value.manifest.model_copy(update={"manifest_hash": f"sha256:{'f' * 64}"})})
        case MutationName.LEAKAGE:
            body = records[0].body.model_copy(update={"feature_fields": (*records[0].body.feature_fields, "future_return")})
            return seal_input(value, (_record(body), *records[1:]), OfflineCode.MALFORMED)
        case MutationName.MISLEADING:
            changed = tuple(_record(_with_edges(record.body, "no_lift")) for record in records)
            return seal_input(value, changed, OfflineCode.PASS)
        case MutationName.NA_TIMEOUT:
            candidate = records[0].body.candidate.model_copy(update={"missing_required_input": True})
            return seal_input(value, (_record(records[0].body.model_copy(update={"candidate": candidate})), *records[1:]), OfflineCode.MALFORMED)
        case MutationName.CLONE:
            return seal_input(value, tuple(_record(_clone(record.body)) for record in records), OfflineCode.CLONE)
        case MutationName.HARM:
            return seal_input(value, tuple(_record(_with_edges(record.body, "harm")) for record in records), OfflineCode.HARMFUL)
        case MutationName.NO_LIFT:
            return seal_input(value, tuple(_record(_with_edges(record.body, "no_lift")) for record in records), OfflineCode.NO_LIFT)
        case MutationName.INSUFFICIENT:
            return seal_input(value, records[:2], OfflineCode.INSUFFICIENT)
        case MutationName.MISSING_ADAPTER:
            changed = tuple(_record(record.body.model_copy(update={"outcome": record.body.outcome.model_copy(update={"adapter_available": False})})) for record in records)
            return seal_input(value, changed, OfflineCode.MISSING_ADAPTER)
        case MutationName.FLAKY:
            codes = (*tuple(OfflineCode.PASS for _ in value.repeated_runs[:-1]), OfflineCode.NO_LIFT)
            return seal_input(value, records, OfflineCode.PASS, codes)
        case MutationName.ABLATION:
            changed = tuple(_record(record.body.model_copy(update={"ablation": record.body.ablation.model_copy(update={"remove_novel_observations_edge": record.body.outcome.candidate_edge})})) for record in records)
            return seal_input(value, changed, OfflineCode.NO_LIFT)
        case MutationName.MALFORMED_PRECEDENCE:
            clone = seal_input(value, tuple(_record(_clone(record.body)) for record in records), OfflineCode.MALFORMED)
            return clone.model_copy(update={"manifest": clone.manifest.model_copy(update={"manifest_hash": f"sha256:{'f' * 64}"})})
        case MutationName.CLONE_PRECEDENCE:
            changed = tuple(_record(_clone(_with_edges(record.body, "harm"))) for record in records)
            return seal_input(value, changed, OfflineCode.CLONE)
        case MutationName.HARM_PRECEDENCE:
            changed = tuple(_record(_with_edges(record.body, "no_lift")) for record in records)
            first = changed[1]
            candidate = first.body.candidate.model_copy(update={"confidence": "0.999999"})
            return seal_input(value, (changed[0], _record(first.body.model_copy(update={"candidate": candidate})), *changed[2:]), OfflineCode.HARMFUL)
        case MutationName.LIFT_PRECEDENCE:
            changed = tuple(_record(_with_edges(record.body, "no_lift")) for record in records[:2])
            return seal_input(value, changed, OfflineCode.NO_LIFT)
        case MutationName.ALL_TRAIN:
            changed = tuple(_record(record.body.model_copy(update={"split": "train_window"})) for record in records)
            return seal_input(value, changed, OfflineCode.INSUFFICIENT)
        case MutationName.OVER_BUDGET:
            candidate = records[0].body.candidate.model_copy(update={"wall_ms": 999999, "llm_calls": 1})
            changed = (_record(records[0].body.model_copy(update={"candidate": candidate})), *records[1:])
            return seal_input(value, changed, OfflineCode.MALFORMED)
        case MutationName.ZERO_REPEATS:
            config_body = value.config.body.model_copy(update={"expected_repeat_runs": 0})
            config = value.config.model_copy(update={"body": config_body, "config_hash": canonical_hash(boundary_json(config_body))})
            return seal_input(value.model_copy(update={"config": config, "repeated_runs": ()}), records, OfflineCode.MALFORMED)
        case MutationName.MISSING_OUTCOMES:
            missing_records: list[SampleBatchRecord] = []
            for record in records:
                outcome = record.body.outcome.model_copy(update={"adapter_available": False, "candidate_edge": None})
                ablation = record.body.ablation.model_copy(update={"remove_novel_observations_edge": None, "existing_signal_only_edge": None, "shuffled_candidate_edge": None})
                missing_records.append(_record(record.body.model_copy(update={"outcome": outcome, "ablation": ablation})))
            return seal_input(value, tuple(missing_records), OfflineCode.MISSING_ADAPTER)
        case MutationName.MISSING_TARGET:
            changed = tuple(_record(record.body.model_copy(update={"target_error": False})) for record in records)
            return seal_input(value, changed, OfflineCode.INSUFFICIENT)
