from __future__ import annotations

from decimal import Decimal

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash
from src.v8.identity import model_json
from src.v8.reconciliation_compiler import forbidden_persisted_keys
from src.v8.reconciliation_identity import (
    execution_seed,
    rebuild_delta,
    rebuild_execution,
    rebuild_fill,
    rebuild_reconciliation,
    rebuild_truth,
)
from src.v8.reconciliation_models import (
    ReconciliationArtifact,
    ReconciliationErrorCode,
    ReconciliationVerificationResult,
)
from src.v8.reconciliation_records import inventory_errors


def _identity_errors(
    artifact: ReconciliationArtifact,
) -> list[ReconciliationErrorCode]:
    errors: list[ReconciliationErrorCode] = []
    order = artifact.execution_order
    if rebuild_execution(order) != order or canonical_hash(execution_seed(order)) != artifact.execution_seed_hash:
        errors.append(ReconciliationErrorCode.RECORD_HASH_MISMATCH)
    truth = artifact.broker_truth
    if truth is not None:
        if rebuild_truth(truth) != truth:
            errors.append(ReconciliationErrorCode.RECORD_HASH_MISMATCH)
        rebuilt_fills = tuple(
            rebuild_fill(fill, order.execution_order_id, truth.broker_truth_id)
            for fill in artifact.fill_fragments
        )
        if rebuilt_fills != artifact.fill_fragments:
            errors.append(ReconciliationErrorCode.RECORD_HASH_MISMATCH)
        if len({fill.fill_fragment_id for fill in artifact.fill_fragments}) != len(
            artifact.fill_fragments
        ):
            errors.append(ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT)
        delta = artifact.portfolio_delta
        if delta is not None and rebuild_delta(
            delta,
            order,
            artifact.fill_fragments,
            str(truth.fee_total),
            str(truth.tax_total),
        ) != delta:
            errors.append(ReconciliationErrorCode.RECORD_HASH_MISMATCH)
        previous = delta.record_hash if delta is not None else truth.record_hash
        rebuilt_reconciliation = rebuild_reconciliation(
            artifact.reconciliation,
            order,
            truth.broker_truth_id,
            "sha256:genesis",
            previous,
        )
    else:
        rebuilt_reconciliation = rebuild_reconciliation(
            artifact.reconciliation,
            order,
            "unknown",
            "sha256:genesis",
            order.record_hash,
        )
    if rebuilt_reconciliation != artifact.reconciliation:
        errors.append(ReconciliationErrorCode.RECORD_HASH_MISMATCH)
    return errors


def _record_errors(
    artifact: ReconciliationArtifact,
) -> list[ReconciliationErrorCode]:
    errors: list[ReconciliationErrorCode] = []
    previous = "sha256:genesis"
    hashes: set[str] = set()
    identities: set[str] = set()
    for record in artifact.records:
        seed = model_json(record, exclude={"record_hash"})
        if record.prev_record_hash != previous or canonical_hash(seed) != record.record_hash:
            errors.append(ReconciliationErrorCode.BROKEN_HASH_CHAIN)
        if record.record_hash in hashes or record.artifact_id in identities:
            code = (
                ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT
                if record.artifact_type == "fill_fragment"
                else ReconciliationErrorCode.BROKEN_HASH_CHAIN
            )
            errors.append(code)
        if not record.source_hashes or any(
            not source_hash.startswith("sha256:") for source_hash in record.source_hashes
        ):
            errors.append(ReconciliationErrorCode.BROKEN_HASH_CHAIN)
        hashes.add(record.record_hash)
        identities.add(record.artifact_id)
        previous = record.record_hash
    return errors


def _accounting_errors(
    artifact: ReconciliationArtifact,
) -> list[ReconciliationErrorCode]:
    truth = artifact.broker_truth
    if truth is None:
        return []
    errors: list[ReconciliationErrorCode] = []
    fills = artifact.fill_fragments
    quantity = sum((fill.quantity for fill in fills), Decimal(0))
    gross = sum((fill.gross_notional for fill in fills), Decimal(0))
    fee = sum((fill.fee for fill in fills), Decimal(0))
    tax = sum((fill.tax for fill in fills), Decimal(0))
    if quantity != truth.cumulative_filled_quantity:
        errors.append(ReconciliationErrorCode.FILL_QUANTITY_MISMATCH)
    delta = artifact.portfolio_delta
    expected_cash = -(gross + fee + tax) if truth.side == "BUY" else gross - fee - tax
    expected_quantity = quantity if truth.side == "BUY" else -quantity
    expected_cost = gross if truth.side == "BUY" else -gross
    if delta is not None:
        currency = truth.currency
        if (
            delta.cash_delta.get(currency) != expected_cash
            or delta.cash_before.get(currency, Decimal(0)) + expected_cash
            != delta.cash_after.get(currency)
        ):
            errors.append(ReconciliationErrorCode.CASH_MISMATCH)
        if (
            delta.position_delta.quantity_delta != expected_quantity
            or delta.position_delta.cost_basis_delta != expected_cost
        ):
            errors.append(ReconciliationErrorCode.POSITION_MISMATCH)
    return errors


def _result(
    artifact: ReconciliationArtifact | None,
    errors: tuple[ReconciliationErrorCode, ...],
) -> ReconciliationVerificationResult:
    if artifact is None:
        return ReconciliationVerificationResult(
            verification_status="fail",
            order_status="unknown",
            errors=errors,
            record_count=0,
            fill_count=0,
            cash_delta_appended=False,
            position_delta_appended=False,
            reorder_allowed=False,
            real_order_created=False,
            portfolio_mutated=False,
        )
    return ReconciliationVerificationResult(
        verification_status="fail" if errors else "pass",
        order_status=artifact.order_status,
        errors=errors,
        record_count=len(artifact.records),
        fill_count=len(artifact.fill_fragments),
        cash_delta_appended=artifact.cash_delta_appended,
        position_delta_appended=artifact.position_delta_appended,
        reorder_allowed=artifact.reorder_allowed,
        real_order_created=artifact.real_order_created,
        portfolio_mutated=artifact.portfolio_mutated,
    )


def verify_reconciliation_artifact(value: JsonValue) -> ReconciliationVerificationResult:
    forbidden = forbidden_persisted_keys(value)
    if forbidden:
        code = (
            ReconciliationErrorCode.MALFORMED_INPUT
            if set(forbidden).issubset({"state", "stage"})
            else ReconciliationErrorCode.LIVE_STATE_CONTAMINATION
        )
        return _result(None, (code,))
    try:
        artifact = ReconciliationArtifact.model_validate(value)
    except ValidationError:
        return _result(None, (ReconciliationErrorCode.MALFORMED_INPUT,))
    errors = (
        _identity_errors(artifact)
        + _record_errors(artifact)
        + inventory_errors(artifact)
        + _accounting_errors(artifact)
    )
    reconciliation = artifact.reconciliation
    if (
        reconciliation.mismatch_count != len(reconciliation.mismatches)
        or (reconciliation.mismatch_count > 0 and reconciliation.quality_result == "pass")
        or (artifact.order_status == "unknown" and reconciliation.quality_result == "pass")
    ):
        errors.append(ReconciliationErrorCode.MISLEADING_SUCCESS_OUTPUT)
    if artifact.order_status == "unknown" and (
        artifact.cash_delta_appended
        or artifact.position_delta_appended
        or artifact.portfolio_delta is not None
        or artifact.reorder_allowed
    ):
        errors.append(ReconciliationErrorCode.MISLEADING_SUCCESS_OUTPUT)
    errors = list(dict.fromkeys(errors))
    priority = {
        ReconciliationErrorCode.MISLEADING_SUCCESS_OUTPUT: 0,
        ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT: 1,
        ReconciliationErrorCode.BROKEN_HASH_CHAIN: 2,
        ReconciliationErrorCode.RECORD_HASH_MISMATCH: 3,
    }
    errors.sort(key=lambda code: priority.get(code, 10))
    return _result(artifact, tuple(errors))
