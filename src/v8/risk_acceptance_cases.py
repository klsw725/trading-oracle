from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.v8.risk_json import JsonValue, model_json
from src.v8.risk_authority import build_acknowledgement
from src.v8.risk_compiler import compile_risk_fixture
from src.v8.risk_evaluator import evaluate_risk
from src.v8.risk_ledger import RiskLedger, append_risk
from src.v8.risk_models import RiskArtifact, RiskDecision, RiskErrorCode, RiskRequest
from src.v8.risk_verifier import verify_risk_artifact


@dataclass(frozen=True, slots=True)
class RiskScenarios:
    cash: RiskDecision
    stale: RiskDecision
    closed: RiskDecision
    sell: RiskDecision
    max_position: RiskDecision
    loss: RiskDecision
    active: RiskDecision
    unreadable: RiskDecision
    falsely_fresh: RiskDecision
    contradiction: RiskDecision

    @property
    def documented_failures(self) -> tuple[RiskDecision, ...]:
        return (
            self.cash,
            self.stale,
            self.closed,
            self.sell,
            self.max_position,
            self.loss,
            self.active,
            self.unreadable,
        )


def build_scenarios(request: RiskRequest) -> RiskScenarios:
    inputs = request.inputs
    with_cash = inputs.model_copy(
        update={"cash": inputs.cash.model_copy(update={"available_cash_after_floor": Decimal("50000")})}
    )
    stale_market = inputs.market_hours.model_copy(
        update={"checked_at": datetime.fromisoformat("2026-08-06T09:07:45+09:00")}
    )
    stale_inputs = inputs.model_copy(
        update={
            "market_hours": stale_market,
            "quote": inputs.quote.model_copy(update={"freshness_result": "stale"}),
        }
    )
    sell_inputs = inputs.model_copy(
        update={"position": inputs.position.model_copy(update={"current_quantity": Decimal("4")})}
    )
    max_inputs = inputs.model_copy(
        update={
            "position": inputs.position.model_copy(
                update={"current_distinct_positions": 3, "max_positions": 3}
            )
        }
    )
    loss_inputs = inputs.model_copy(
        update={
            "daily_loss": inputs.daily_loss.model_copy(
                update={"current_equity": Decimal("970000"), "daily_pnl_pct": Decimal("-3")}
            )
        }
    )
    active_inputs = inputs.model_copy(
        update={
            "kill_switch": inputs.kill_switch.model_copy(
                update={"switch_status": "active", "covered_actions": ("BUY", "SELL")}
            )
        }
    )
    return RiskScenarios(
        cash=evaluate_risk(request.model_copy(update={"inputs": with_cash})),
        stale=evaluate_risk(request.model_copy(update={"inputs": stale_inputs})),
        closed=evaluate_risk(
            request.model_copy(
                update={
                    "inputs": inputs.model_copy(
                        update={"market_hours": inputs.market_hours.model_copy(update={"is_open": False})}
                    )
                }
            )
        ),
        sell=evaluate_risk(
            request.model_copy(
                update={
                    "side": "SELL",
                    "quantity": Decimal("10"),
                    "risk_increasing_action": False,
                    "inputs": sell_inputs,
                }
            )
        ),
        max_position=evaluate_risk(
            request.model_copy(update={"ticker": "035420", "inputs": max_inputs})
        ),
        loss=evaluate_risk(request.model_copy(update={"inputs": loss_inputs})),
        active=evaluate_risk(request.model_copy(update={"inputs": active_inputs})),
        unreadable=evaluate_risk(
            request.model_copy(
                update={
                    "inputs": inputs.model_copy(
                        update={"kill_switch": inputs.kill_switch.model_copy(update={"readable": False})}
                    )
                }
            )
        ),
        falsely_fresh=evaluate_risk(
            request.model_copy(
                update={"inputs": inputs.model_copy(update={"market_hours": stale_market})}
            )
        ),
        contradiction=evaluate_risk(
            request.model_copy(
                update={
                    "inputs": inputs.model_copy(
                        update={"market_hours": inputs.market_hours.model_copy(update={"holiday": True})}
                    )
                }
            )
        ),
    )


def _first_error(value: JsonValue) -> str | None:
    result = verify_risk_artifact(value)
    return result.errors[0].value if result.errors else None


def mutation_probes(
    fixture: JsonValue, artifact: RiskArtifact, scenarios: RiskScenarios
) -> dict[str, str | None]:
    malformed = deepcopy(fixture)
    understated_cash = deepcopy(fixture)
    assert isinstance(malformed, dict)
    assert isinstance(understated_cash, dict)
    _ = malformed.pop("schema_version")
    understated_inputs = understated_cash["inputs"]
    assert isinstance(understated_inputs, dict)
    understated_cash_input = understated_inputs["cash"]
    assert isinstance(understated_cash_input, dict)
    understated_cash_input["required_cash"] = "1"
    status = deepcopy(model_json(artifact))
    hashed = deepcopy(model_json(artifact))
    misleading = deepcopy(model_json(artifact))
    assert isinstance(status, dict) and isinstance(status["decision"], dict)
    assert isinstance(hashed, dict) and isinstance(hashed["decision"], dict)
    assert isinstance(misleading, dict) and isinstance(misleading["decision"], dict)
    status["decision"]["risk_status"] = "allowed"
    status["decision"]["state"] = None
    hashed["decision"]["quantity"] = "11"
    misleading["decision"]["risk_status"] = "allowed"
    misleading["decision"]["blocking_reasons"] = ["cash_insufficient"]
    first = append_risk(RiskLedger.empty(), artifact)
    duplicate = append_risk(first.ledger, artifact)
    malformed_code = compile_risk_fixture(malformed).error_code
    understated_cash_code = compile_risk_fixture(understated_cash).error_code
    request = artifact.request
    return {
        "json_malformed": malformed_code.value if malformed_code is not None else None,
        "required_cash_understatement": (
            understated_cash_code.value if understated_cash_code is not None else None
        ),
        "status_mutation": _first_error(status),
        "hash_mutation": _first_error(hashed),
        "interruption_duplicate": "stored_decision" if duplicate.returned_existing else None,
        "stale_quote": scenarios.falsely_fresh.blocking_reasons[0],
        "market_closed": scenarios.contradiction.blocking_reasons[0],
        "cash_failure": scenarios.cash.blocking_reasons[0],
        "position_failure": scenarios.sell.blocking_reasons[0],
        "daily_loss_failure": scenarios.loss.blocking_reasons[0],
        "kill_switch_unreadable": scenarios.unreadable.blocking_reasons[0],
        "ack_override_blocker": (
            "blocked_preserved"
            if build_acknowledgement(
                scenarios.cash,
                "operator_redacted_01",
                "warning_only",
                request.inputs.market_hours.checked_at,
                request.inputs.quote.quote_expires_at,
            )
            is None
            else None
        ),
        "misleading_success": _first_error(misleading),
    }


EXPECTED_PROBES: dict[str, str | None] = {
    "json_malformed": RiskErrorCode.MALFORMED_INPUT.value,
    "required_cash_understatement": RiskErrorCode.MALFORMED_INPUT.value,
    "status_mutation": RiskErrorCode.RISK_STATUS_TAMPERED.value,
    "hash_mutation": RiskErrorCode.RECORD_HASH_MISMATCH.value,
    "interruption_duplicate": "stored_decision",
    "stale_quote": RiskErrorCode.STALE_QUOTE_FALSELY_FRESH.value,
    "market_closed": RiskErrorCode.MARKET_HOURS_CONTRADICTION.value,
    "cash_failure": RiskErrorCode.CASH_INSUFFICIENT.value,
    "position_failure": RiskErrorCode.POSITION_INSUFFICIENT.value,
    "daily_loss_failure": RiskErrorCode.DAILY_LOSS_LIMIT_HIT.value,
    "kill_switch_unreadable": RiskErrorCode.KILL_SWITCH_UNREADABLE.value,
    "ack_override_blocker": "blocked_preserved",
    "misleading_success": RiskErrorCode.MISLEADING_RISK_SUCCESS.value,
}
