from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Final

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash
from src.v8.reconciliation_identity import (
    execution_seed,
    rebuild_delta,
    rebuild_execution,
    rebuild_fill,
    rebuild_reconciliation,
    rebuild_truth,
)
from src.v8.reconciliation_models import (
    BrokerTruth,
    CompileReconciliationResult,
    ExecutionOrder,
    ExpectedArithmetic,
    HappyFixture,
    OrderStatus,
    Reconciliation,
    ReconciliationArtifact,
    ReconciliationErrorCode,
    UnknownFixture,
)
from src.v8.reconciliation_records import build_records
from src.v8.reconciliation_rules import accounting_error, truth_error

_HASH: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_KEYS: Final = frozenset(
    {
        "access_token", "account_id", "account_number", "api_key", "broker_account",
        "broker_order_id", "client_secret", "credential", "credentials", "live_order_id",
        "raw_broker_order_id", "refresh_token", "state", "stage",
    }
)


def forbidden_persisted_keys(value: JsonValue) -> tuple[str, ...]:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            own = tuple(sorted(_FORBIDDEN_KEYS.intersection(record)))
            return own + tuple(
                key
                for child in record.values()
                for key in forbidden_persisted_keys(child)
            )
        case list() as items:
            return tuple(
                key for child in items for key in forbidden_persisted_keys(child)
            )
        case None | bool() | int() | float() | str():
            return ()


def _failure(code: ReconciliationErrorCode) -> CompileReconciliationResult:
    return CompileReconciliationResult("unknown", None, code)


def order_side_is_buy(truth: BrokerTruth) -> bool:
    return truth.side == "BUY"


def _unknown_artifact(
    order: ExecutionOrder,
    source_hash: str,
    as_of: datetime,
    code: ReconciliationErrorCode,
) -> ReconciliationArtifact:
    arithmetic = None
    reconciliation = Reconciliation(
        order_reconciliation_id="claimed",
        as_of=as_of,
        order_status="unknown",
        matched_checks=(),
        mismatches=(code,),
        mismatch_count=1,
        quality_result="fail",
        reorder_allowed=False,
        operator_review_required=True,
        allowed_next_action="refresh_broker_truth_for_same_ref_hash",
        expected_arithmetic=arithmetic,
        prev_record_hash=order.record_hash,
        record_hash="sha256:" + "0" * 64,
    )
    reconciliation = rebuild_reconciliation(
        reconciliation, order, "unknown", "sha256:genesis", order.record_hash
    )
    records = build_records(source_hash, order, None, (), None, reconciliation)
    return ReconciliationArtifact(
        schema_version="v8.order_reconciliation.artifact.1",
        source_input_hash=source_hash,
        execution_seed_hash=canonical_hash(execution_seed(order)),
        order_status="unknown",
        execution_order=order,
        broker_truth=None,
        fill_fragments=(),
        portfolio_delta=None,
        reconciliation=reconciliation,
        records=records,
        cash_delta_appended=False,
        position_delta_appended=False,
        reorder_allowed=False,
        real_order_created=False,
        portfolio_mutated=False,
    )


def _compile_happy(fixture: HappyFixture, source_hash: str) -> CompileReconciliationResult:
    order = rebuild_execution(fixture.execution_order)
    truth = rebuild_truth(fixture.broker_truth)
    error = truth_error(order, truth, fixture.reconciliation.as_of <= truth.truth_fresh_until)
    if error is not None:
        return CompileReconciliationResult(
            "unknown", _unknown_artifact(order, source_hash, fixture.reconciliation.as_of, error), error
        )
    fills = tuple(
        rebuild_fill(fill, order.execution_order_id, truth.broker_truth_id)
        for fill in truth.fill_fragments
    )
    if len({fill.fill_fragment_id for fill in fills}) != len(fills):
        error = ReconciliationErrorCode.DUPLICATE_FILL_FRAGMENT
    else:
        error = accounting_error(fixture, truth)
    delta = None
    if error is None:
        delta = rebuild_delta(
            fixture.portfolio_delta, order, fills, str(truth.fee_total), str(truth.tax_total)
        )
    gross = sum((fill.gross_notional for fill in fills), Decimal(0))
    fee = sum((fill.fee for fill in fills), Decimal(0))
    tax = sum((fill.tax for fill in fills), Decimal(0))
    currency = truth.currency
    cash_before = fixture.portfolio_delta.cash_before.get(currency, Decimal(0))
    cash_delta = -(gross + fee + tax) if order_side_is_buy(truth) else gross - fee - tax
    status: OrderStatus = truth.order_status if error is None else "unknown"
    reconciliation = fixture.reconciliation.model_copy(
        update={
            "order_status": status,
            "matched_checks": fixture.reconciliation.matched_checks if error is None else (),
            "mismatches": () if error is None else (error,),
            "mismatch_count": 0 if error is None else 1,
            "quality_result": "pass" if error is None else "fail",
            "operator_review_required": error is not None,
            "allowed_next_action": "refresh_broker_truth_for_same_ref_hash" if error is not None else None,
            "expected_arithmetic": ExpectedArithmetic(
                gross_notional=gross,
                fee=fee,
                tax=tax,
                cash_delta=cash_delta,
                cash_after=cash_before + cash_delta,
                remaining_quantity=truth.remaining_quantity,
            ),
        }
    )
    previous_hash = delta.record_hash if delta is not None else truth.record_hash
    reconciliation = rebuild_reconciliation(
        reconciliation, order, truth.broker_truth_id, "sha256:genesis", previous_hash
    )
    records = build_records(source_hash, order, truth, fills, delta, reconciliation)
    artifact = ReconciliationArtifact(
        schema_version="v8.order_reconciliation.artifact.1",
        source_input_hash=source_hash,
        execution_seed_hash=canonical_hash(execution_seed(order)),
        order_status=status,
        execution_order=order,
        broker_truth=truth,
        fill_fragments=fills,
        portfolio_delta=delta,
        reconciliation=reconciliation,
        records=records,
        cash_delta_appended=delta is not None,
        position_delta_appended=delta is not None,
        reorder_allowed=False,
        real_order_created=False,
        portfolio_mutated=False,
    )
    return CompileReconciliationResult(status, artifact, error)


def compile_reconciliation_fixture(value: JsonValue) -> CompileReconciliationResult:
    forbidden = forbidden_persisted_keys(value)
    if forbidden:
        code = (
            ReconciliationErrorCode.MALFORMED_INPUT
            if set(forbidden).issubset({"state", "stage"})
            else ReconciliationErrorCode.LIVE_STATE_CONTAMINATION
        )
        return _failure(code)
    try:
        match value:  # noqa: MATCH_OK - schema version selects the fixture boundary
            case {"schema_version": "v8.order_reconciliation.prd03.fixture.1"}:
                fixture = HappyFixture.model_validate(value)
                return _compile_happy(fixture, canonical_hash(value))
            case {"schema_version": "v8.order_reconciliation.prd03.failure_fixture.1"}:
                fixture = UnknownFixture.model_validate(value)
                order = rebuild_execution(fixture.execution_order)
                code = ReconciliationErrorCode.BROKER_TRUTH_CONTRADICTION
                artifact = _unknown_artifact(
                    order, canonical_hash(value), fixture.truth_failure.observed_at, code
                )
                return CompileReconciliationResult("unknown", artifact, code)
            case _:
                return _failure(ReconciliationErrorCode.MALFORMED_INPUT)
    except ValidationError:
        return _failure(ReconciliationErrorCode.MALFORMED_INPUT)
