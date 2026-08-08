from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from src.v4.models import JsonValue, canonical_hash
from src.v8.fixture import load_json
from src.v8.identity import model_json
from src.v8.reconciliation_compiler import compile_reconciliation_fixture
from src.v8.reconciliation_ledger import (
    ReconciliationLedger,
    append_reconciliation,
    request_reorder,
    with_record_prefix,
)
from src.v8.reconciliation_models import ReconciliationErrorCode
from src.v8.reconciliation_verifier import verify_reconciliation_artifact

HAPPY_FIXTURE_PATH: Final = Path(
    "docs/specs/v8/fixtures/prd03-order-state-reconciliation-happy.json"
)
UNKNOWN_FIXTURE_PATH: Final = Path(
    "docs/specs/v8/fixtures/prd03-order-state-reconciliation-unknown.json"
)
_JSON: Final = TypeAdapter[JsonValue](JsonValue)


def _record(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    return value


def _nested(record: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    value = record[key]
    assert isinstance(value, dict)
    return value


def _error(value: JsonValue) -> str | None:
    result = compile_reconciliation_fixture(value)
    return result.error_code.value if result.error_code is not None else None


def run_reconciliation_acceptance() -> JsonValue:
    happy = load_json(HAPPY_FIXTURE_PATH)
    unknown = load_json(UNKNOWN_FIXTURE_PATH)
    compiled = compile_reconciliation_fixture(happy)
    unknown_compiled = compile_reconciliation_fixture(unknown)
    artifact = compiled.artifact
    unknown_artifact = unknown_compiled.artifact
    assert artifact is not None and unknown_artifact is not None
    verified = verify_reconciliation_artifact(model_json(artifact))
    unknown_verified = verify_reconciliation_artifact(model_json(unknown_artifact))

    malformed = deepcopy(happy)
    _ = _record(malformed).pop("schema_version")
    status = deepcopy(happy)
    status_truth = _nested(_record(status), "broker_truth")
    status_truth["order_status"] = "filled"
    arithmetic = deepcopy(happy)
    _nested(_nested(_record(arithmetic), "portfolio_delta"), "cash_after")[
        "KRW"
    ] = "959970.00"
    duplicate_fill = deepcopy(happy)
    duplicate_truth = _nested(_record(duplicate_fill), "broker_truth")
    duplicate_fragments = duplicate_truth["fill_fragments"]
    assert isinstance(duplicate_fragments, list)
    duplicate = deepcopy(duplicate_fragments[0])
    assert isinstance(duplicate, dict)
    duplicate["fill_fragment_id"] = "ffill_v8_claimed_duplicate"
    duplicate_fragments.append(duplicate)
    duplicate_truth["cumulative_filled_quantity"] = "8"
    duplicate_truth["remaining_quantity"] = "2"
    stale = deepcopy(happy)
    stale_truth = _nested(_record(stale), "broker_truth")
    stale_truth["observed_at"] = "2026-08-06T09:10:20+09:00"
    stale_truth["truth_fresh_until"] = "2026-08-06T09:08:40+09:00"
    forbidden = deepcopy(happy)
    _nested(_record(forbidden), "broker_truth")["account_number"] = None
    lifecycle_alias = deepcopy(happy)
    _record(lifecycle_alias)["stage"] = None
    position = deepcopy(happy)
    _nested(_nested(_record(position), "portfolio_delta"), "position_delta")[
        "quantity_delta"
    ] = "5"
    unknown_status = deepcopy(happy)
    _nested(_record(unknown_status), "broker_truth")["order_status"] = "unknown"
    unknown_status_compiled = compile_reconciliation_fixture(unknown_status)
    unknown_status_artifact = unknown_status_compiled.artifact
    assert unknown_status_artifact is not None
    numeric_decimal = deepcopy(happy)
    _nested(_record(numeric_decimal), "execution_order")["quantity"] = 10
    numeric_compiled = compile_reconciliation_fixture(numeric_decimal)
    numeric_append = append_reconciliation(ReconciliationLedger.empty(), numeric_compiled)

    hash_mutation = deepcopy(model_json(artifact))
    hash_fills = _record(hash_mutation)["fill_fragments"]
    assert isinstance(hash_fills, list)
    hash_fill = hash_fills[0]
    assert isinstance(hash_fill, dict)
    hash_fill["quantity"] = "5"
    hash_result = verify_reconciliation_artifact(hash_mutation)
    misleading = deepcopy(model_json(artifact))
    misleading_reconciliation = _nested(_record(misleading), "reconciliation")
    misleading_reconciliation["mismatch_count"] = 1
    misleading_result = verify_reconciliation_artifact(misleading)
    forged_payload = deepcopy(model_json(artifact))
    forged_records = _record(forged_payload)["records"]
    assert isinstance(forged_records, list)
    forged_previous = forged_records[-1]
    assert isinstance(forged_previous, dict)
    forged_seed: dict[str, JsonValue] = {
        "schema_version": "v8.order_reconciliation.record.1",
        "artifact_type": "execution_order",
        "artifact_id": "exec_v8_forged_persisted_payload",
        "order_status": "partial",
        "payload": {"audit": {"account_id": None}},
        "source_hashes": [artifact.source_input_hash],
        "prev_record_hash": forged_previous["record_hash"],
    }
    forged_records.append({**forged_seed, "record_hash": canonical_hash(forged_seed)})
    forged_result = verify_reconciliation_artifact(forged_payload)
    duplicate_inventory = deepcopy(model_json(artifact))
    duplicate_records = _record(duplicate_inventory)["records"]
    assert isinstance(duplicate_records, list)
    duplicate_record = _record(deepcopy(duplicate_records[2]))
    duplicate_record["artifact_id"] = "ffill_v8_fresh_semantic_duplicate"
    duplicate_record["prev_record_hash"] = _record(duplicate_records[-1])["record_hash"]
    _ = duplicate_record.pop("record_hash")
    duplicate_record["record_hash"] = canonical_hash(duplicate_record)
    duplicate_records.append(duplicate_record)
    duplicate_inventory_result = verify_reconciliation_artifact(duplicate_inventory)

    interrupted_ledger = with_record_prefix(artifact, 2)
    recovered = append_reconciliation(interrupted_ledger, compiled)
    retried = append_reconciliation(recovered.ledger, compiled)
    initial_unknown = append_reconciliation(ReconciliationLedger.empty(), unknown_compiled)
    recovered_unknown = append_reconciliation(initial_unknown.ledger, compiled)
    assert recovered_unknown.artifact is not None
    recovered_unknown_verification = verify_reconciliation_artifact(model_json(recovered_unknown.artifact))
    reordered = request_reorder(
        initial_unknown.ledger, artifact.execution_order.idempotency_key
    )
    conflict = deepcopy(happy)
    conflict_order = _nested(_record(conflict), "execution_order")
    conflict_order["quantity"] = "11"
    conflict_truth = _nested(_record(conflict), "broker_truth")
    conflict_truth["original_quantity"] = "11"
    conflict_truth["remaining_quantity"] = "7"
    conflicted = append_reconciliation(
        recovered.ledger, compile_reconciliation_fixture(conflict)
    )

    probes = {
        "json_malformed": _error(malformed),
        "status_mismatch": _error(status),
        "hash_mismatch": hash_result.errors[0].value,
        "arithmetic_mismatch": _error(arithmetic),
        "interruption_duplicate_fill": _error(duplicate_fill),
        "unknown_reorder": reordered.value if reordered is not None else None,
        "forbidden_field": _error(forbidden),
        "misleading_success": misleading_result.errors[0].value,
        "stale_broker_truth": _error(stale),
        "position_mismatch": _error(position),
        "lifecycle_alias": _error(lifecycle_alias),
        "numeric_decimal": numeric_compiled.error_code.value
        if numeric_compiled.error_code is not None
        else None,
    }
    expected = {
        "json_malformed": ReconciliationErrorCode.MALFORMED_INPUT.value,
        "status_mismatch": ReconciliationErrorCode.BROKER_TRUTH_CONTRADICTION.value,
        "hash_mismatch": ReconciliationErrorCode.RECORD_HASH_MISMATCH.value,
        "arithmetic_mismatch": ReconciliationErrorCode.CASH_MISMATCH.value,
        "interruption_duplicate_fill": ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT.value,
        "unknown_reorder": ReconciliationErrorCode.REORDER_BLOCKED_UNDER_UNKNOWN.value,
        "forbidden_field": ReconciliationErrorCode.LIVE_STATE_CONTAMINATION.value,
        "misleading_success": ReconciliationErrorCode.MISLEADING_SUCCESS_OUTPUT.value,
        "stale_broker_truth": ReconciliationErrorCode.STALE_BROKER_TRUTH.value,
        "position_mismatch": ReconciliationErrorCode.POSITION_MISMATCH.value,
        "lifecycle_alias": ReconciliationErrorCode.MALFORMED_INPUT.value,
        "numeric_decimal": ReconciliationErrorCode.MALFORMED_INPUT.value,
    }
    truth = artifact.broker_truth
    delta = artifact.portfolio_delta
    arithmetic_result = artifact.reconciliation.expected_arithmetic
    assert truth is not None and delta is not None and arithmetic_result is not None
    checks = {
        "happy_partial_fill": verified.verification_status == "pass"
        and artifact.order_status == "partial"
        and str(truth.cumulative_filled_quantity) == "4"
        and str(arithmetic_result.gross_notional) == "40000.00"
        and str(arithmetic_result.fee) == "40.00"
        and str(arithmetic_result.cash_delta) == "-40040.00"
        and str(arithmetic_result.remaining_quantity) == "6",
        "unknown_fail_closed": unknown_verified.verification_status == "pass"
        and unknown_artifact.order_status == "unknown"
        and not unknown_artifact.cash_delta_appended
        and not unknown_artifact.position_delta_appended
        and not unknown_artifact.reorder_allowed,
        "normative_probes": probes == expected,
        "claimed_boundaries_recomputed": artifact.execution_order.execution_order_id
        != _nested(_record(happy), "execution_order")["execution_order_id"]
        and artifact.execution_order.record_hash
        != _nested(_record(happy), "execution_order")["record_hash"],
        "canonical_determinism": compile_reconciliation_fixture(happy) == compiled,
        "append_only_hash_chain": verified.record_count == 5,
        "recovery_appends_missing_only": recovered.appended_count == 3
        and retried.appended_count == 0
        and retried.returned_existing,
        "same_key_conflict_appends_nothing": conflicted.error_code
        is ReconciliationErrorCode.IDEMPOTENCY_CONFLICT
        and conflicted.ledger == recovered.ledger,
        "unknown_same_ref_recovery": recovered_unknown.appended_count == 4
        and recovered_unknown_verification.verification_status == "pass"
        and sum(
            record.artifact_type == "execution_order"
            for record in recovered_unknown.ledger.entries[0].records
        )
        == 1,
        "order_status_only": all(
            key not in {"state", "stage"}
            for record in artifact.records
            for key in _record(model_json(record))
        ),
        "strict_no_side_effects": not artifact.real_order_created
        and not artifact.portfolio_mutated
        and not artifact.reorder_allowed,
        "portfolio_delta_accounting": delta.cash_delta == {"KRW": -40040}
        and delta.position_delta.quantity_delta == 4
        and delta.position_delta.cost_basis_delta == 40000,
        "unknown_operator_path": unknown_artifact.reconciliation.operator_review_required
        and unknown_artifact.reconciliation.allowed_next_action
        == "refresh_broker_truth_for_same_ref_hash",
        "redacted_reference_only": artifact.execution_order.broker_order_ref_hash.startswith(
            "sha256:"
        ),
        "happy_unknown_status_fail_closed": unknown_status_compiled.error_code
        is ReconciliationErrorCode.BROKER_TRUTH_CONTRADICTION
        and unknown_status_artifact.order_status == "unknown"
        and unknown_status_artifact.portfolio_delta is None
        and not unknown_status_artifact.cash_delta_appended
        and not unknown_status_artifact.position_delta_appended
        and not unknown_status_artifact.reorder_allowed
        and unknown_status_artifact.reconciliation.expected_arithmetic is None,
        "forged_payload_rejected": forged_result.verification_status == "fail"
        and forged_result.errors
        == (ReconciliationErrorCode.LIVE_STATE_CONTAMINATION,),
        "decimal_strings_required": numeric_compiled.artifact is None
        and numeric_append.appended_count == 0,
        "canonical_record_inventory": duplicate_inventory_result.errors
        == (ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT,),
    }
    return _JSON.validate_python(
        {
            "verification_status": "pass" if all(checks.values()) else "fail",
            "acceptance_count": len(checks),
            "checks": checks,
            "failure_probes": probes,
        }
    )
