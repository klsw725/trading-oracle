from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from pydantic import ValidationError

from src.v8.event_models import FrozenModel, Side
from src.v8.risk_evaluator import evaluate_risk
from src.v8.risk_json import JsonValue, canonical_hash
from src.v8.risk_models import (
    RiskArtifact,
    RiskContractError,
    RiskErrorCode,
    RiskInputs,
    RiskRequest,
)

_FORBIDDEN: Final = frozenset(
    {
        "state",
        "stage",
        "access_token",
        "client_secret",
        "account_number",
        "broker_order_id",
        "live_order_id",
        "broker_live",
        "real_account",
    }
)
_DECIMAL_FIELDS: Final = frozenset(
    {
        "quantity",
        "estimated_notional",
        "estimated_fee",
        "estimated_tax",
        "available_cash_after_floor",
        "required_cash",
        "cash_floor_after_order_pct",
        "current_quantity",
        "post_order_quantity",
        "post_order_weight_pct",
        "max_weight_pct",
        "sector_weight_after_pct",
        "max_sector_weight_pct",
        "max_pair_correlation",
        "pair_threshold",
        "day_start_equity",
        "current_equity",
        "daily_pnl_pct",
        "halt_threshold_pct",
    }
)


class ClaimedDecision(FrozenModel):
    schema_version: Literal["v8.risk_controls.decision.1"]
    ticker: str
    side: Side
    quantity: str
    currency: Literal["KRW", "USD"]
    estimated_notional: str
    estimated_fee: str
    estimated_tax: str
    idempotency_key: str
    risk_decision_id: str
    risk_status: str
    blocking_reasons: tuple[str, ...]
    ack_required_reasons: tuple[str, ...]
    source_hashes: dict[str, str]
    record_hash: str


class HappyRiskFixture(FrozenModel):
    schema_version: Literal["v8.risk_controls.prd04.fixture.1"]
    fixture_name: str
    strict_no_real_order: Literal[True]
    proposed_order_id: str
    paper_order_id: str
    risk_decision: ClaimedDecision
    inputs: RiskInputs
    expected_result: JsonValue


@dataclass(frozen=True, slots=True)
class CompileRiskResult:
    artifact: RiskArtifact | None
    error_code: RiskErrorCode | None = None


def _invalid_shape(value: JsonValue) -> bool:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            if _FORBIDDEN.intersection(record):
                return True
            for key, child in record.items():
                if key in _DECIMAL_FIELDS and not isinstance(child, str):
                    return True
                if _invalid_shape(child):
                    return True
            return False
        case list() as values:
            return any(_invalid_shape(child) for child in values)
        case None | bool() | int() | float() | str():
            return False


def request_from_fixture(value: JsonValue) -> RiskRequest:
    if _invalid_shape(value):
        raise RiskContractError(RiskErrorCode.MALFORMED_INPUT, "forbidden key or decimal shape")
    try:
        fixture = HappyRiskFixture.model_validate(value)
    except ValidationError as error:
        raise RiskContractError(RiskErrorCode.MALFORMED_INPUT, str(error)) from error
    claim = fixture.risk_decision
    required_cash = (
        Decimal(claim.estimated_notional)
        + Decimal(claim.estimated_fee)
        + Decimal(claim.estimated_tax)
    )
    if claim.side == "BUY" and fixture.inputs.cash.required_cash != required_cash:
        raise RiskContractError(
            RiskErrorCode.MALFORMED_INPUT,
            "required_cash must equal estimated_notional + estimated_fee + estimated_tax",
        )
    return RiskRequest(
        proposed_order_id=fixture.proposed_order_id,
        paper_order_id=fixture.paper_order_id,
        ticker=claim.ticker,
        side=claim.side,
        quantity=Decimal(claim.quantity),
        currency=claim.currency,
        estimated_notional=Decimal(claim.estimated_notional),
        estimated_fee=Decimal(claim.estimated_fee),
        estimated_tax=Decimal(claim.estimated_tax),
        idempotency_key=claim.idempotency_key,
        inputs=fixture.inputs,
    )


def compile_risk_fixture(value: JsonValue) -> CompileRiskResult:
    try:
        request = request_from_fixture(value)
    except RiskContractError as error:
        return CompileRiskResult(None, error.code)
    decision = evaluate_risk(request)
    return CompileRiskResult(
        RiskArtifact(
            schema_version="v8.risk_controls.artifact.1",
            source_input_hash=canonical_hash(value),
            request=request,
            decision=decision,
        )
    )
