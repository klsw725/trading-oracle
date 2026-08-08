from __future__ import annotations

from src.v4.models import JsonValue, canonical_hash
from src.v8.identity import deterministic_id, model_json
from src.v8.reconciliation_models import (
    BrokerTruth,
    ExecutionOrder,
    FillFragment,
    PortfolioDelta,
    Reconciliation,
)


def execution_seed(order: ExecutionOrder) -> JsonValue:
    return {
        "dry_run_response_id": order.dry_run_response_id,
        "proposed_order_id": order.proposed_order_id,
        "side": order.side,
        "quantity": str(order.quantity),
        "order_type": order.order_type,
        "price": str(order.limit_price) if order.limit_price is not None else None,
        "idempotency_key": order.idempotency_key,
    }


def rebuild_execution(order: ExecutionOrder) -> ExecutionOrder:
    identity = deterministic_id("eord_v8_", execution_seed(order))
    rebuilt = order.model_copy(
        update={"execution_order_id": identity, "record_hash": "sha256:" + "0" * 64}
    )
    return rebuilt.model_copy(
        update={"record_hash": canonical_hash(model_json(rebuilt, exclude={"record_hash"}))}
    )


def rebuild_truth(truth: BrokerTruth) -> BrokerTruth:
    payload_hash = canonical_hash(
        model_json(truth, exclude={"broker_truth_id", "record_hash"})
    )
    identity = deterministic_id(
        "btru_v8_",
        {
            "broker_adapter": model_json(truth.broker_adapter),
            "broker_order_ref_hash": truth.broker_order_ref_hash,
            "observed_at": truth.observed_at.isoformat(),
            "broker_truth_payload_hash": payload_hash,
        },
    )
    rebuilt = truth.model_copy(
        update={"broker_truth_id": identity, "record_hash": "sha256:" + "0" * 64}
    )
    return rebuilt.model_copy(
        update={"record_hash": canonical_hash(model_json(rebuilt, exclude={"record_hash"}))}
    )


def rebuild_fill(
    fragment: FillFragment, execution_order_id: str, broker_truth_id: str
) -> FillFragment:
    identity = deterministic_id(
        "ffill_v8_",
        {
            "execution_order_id": execution_order_id,
            "broker_truth_id": broker_truth_id,
            "fill_sequence": fragment.sequence,
            "quantity": str(fragment.quantity),
            "price": str(fragment.price),
            "filled_at": fragment.filled_at.isoformat(),
        },
    )
    rebuilt = fragment.model_copy(
        update={"fill_fragment_id": identity, "record_hash": "sha256:" + "0" * 64}
    )
    return rebuilt.model_copy(
        update={"record_hash": canonical_hash(model_json(rebuilt, exclude={"record_hash"}))}
    )


def rebuild_delta(
    claimed: PortfolioDelta,
    order: ExecutionOrder,
    fills: tuple[FillFragment, ...],
    fee: str,
    tax: str,
) -> PortfolioDelta:
    identity = deterministic_id(
        "pdelta_v8_",
        {
            "execution_order_id": order.execution_order_id,
            "fill_fragment_ids": [fragment.fill_fragment_id for fragment in fills],
            "cash_delta": {key: str(value) for key, value in claimed.cash_delta.items()},
            "position_delta": model_json(claimed.position_delta),
            "fee": fee,
            "tax": tax,
        },
    )
    rebuilt = claimed.model_copy(
        update={"portfolio_delta_id": identity, "record_hash": "sha256:" + "0" * 64}
    )
    return rebuilt.model_copy(
        update={"record_hash": canonical_hash(model_json(rebuilt, exclude={"record_hash"}))}
    )


def rebuild_reconciliation(
    claimed: Reconciliation,
    order: ExecutionOrder,
    broker_truth_id: str,
    prior_reconciliation_hash: str,
    previous_artifact_hash: str,
) -> Reconciliation:
    identity = deterministic_id(
        "orecon_v8_",
        {
            "execution_order_id": order.execution_order_id,
            "broker_truth_id": broker_truth_id,
            "as_of": claimed.as_of.isoformat(),
            "prior_reconciliation_hash": prior_reconciliation_hash,
        },
    )
    rebuilt = claimed.model_copy(
        update={
            "order_reconciliation_id": identity,
            "prev_record_hash": previous_artifact_hash,
            "record_hash": "sha256:" + "0" * 64,
        }
    )
    return rebuilt.model_copy(
        update={"record_hash": canonical_hash(model_json(rebuilt, exclude={"record_hash"}))}
    )
