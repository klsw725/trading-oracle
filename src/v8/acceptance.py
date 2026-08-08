from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter

from src.v4.models import JsonValue, canonical_hash
from src.v8.compiler import compile_fixture
from src.v8.identity import model_json
from src.v8.models import (
    FailureCode,
    LedgerContractError,
    PaperLedgerArtifact,
    PaperLedgerFixture,
    VerificationContext,
)
from src.v8.verifier import verify_artifact

FIXTURE_PATH: Final = Path(
    "docs/specs/v8/fixtures/prd01-paper-portfolio-ledger.json"
)
_JSON: Final = TypeAdapter[JsonValue](JsonValue)


@dataclass(frozen=True, slots=True)
class PayloadMutation:
    event_index: int
    key: str
    value: JsonValue


def _fixture_value() -> JsonValue:
    return _JSON.validate_json(FIXTURE_PATH.read_bytes())


def _mutated_artifact(
    artifact: PaperLedgerArtifact, mutation: PayloadMutation
) -> PaperLedgerArtifact:
    raw = model_json(artifact)
    assert isinstance(raw, dict)
    events = raw.get("events")
    assert isinstance(events, list)
    event = events[mutation.event_index]
    assert isinstance(event, dict)
    payload = event.get("payload")
    assert isinstance(payload, dict)
    payload[mutation.key] = mutation.value
    return PaperLedgerArtifact.model_validate(raw)


def _error_code(
    artifact: PaperLedgerArtifact, context: VerificationContext
) -> str | None:
    result = verify_artifact(artifact, context)
    return result.errors[0].value if result.errors else None


def _compile_error(value: JsonValue) -> str | None:
    try:
        _ = compile_fixture(value)
    except LedgerContractError as error:
        return error.code.value
    return None


def run_acceptance() -> JsonValue:
    fixture = _fixture_value()
    artifact = compile_fixture(fixture)
    source_hash = canonical_hash(fixture)
    clean = VerificationContext(
        replay_cutoff=datetime.fromisoformat("2026-08-06T09:08:00+09:00"),
        declared_input_hash=source_hash,
        observed_input_hash=source_hash,
        claimed_success=False,
    )
    result = verify_artifact(artifact, clean)
    claimed = PaperLedgerFixture.model_validate(fixture)

    stale = VerificationContext(
        replay_cutoff=datetime.fromisoformat("2026-08-06T09:06:30+09:00"),
        declared_input_hash=source_hash,
        observed_input_hash=source_hash,
        claimed_success=False,
    )
    dirty = VerificationContext(
        replay_cutoff=clean.replay_cutoff,
        declared_input_hash="sha256:" + "0" * 64,
        observed_input_hash=source_hash,
        claimed_success=False,
    )
    misleading = VerificationContext(
        replay_cutoff=clean.replay_cutoff,
        declared_input_hash=source_hash,
        observed_input_hash=source_hash,
        claimed_success=True,
    )
    broken = _mutated_artifact(artifact, PayloadMutation(3, "fee", "101.00"))
    duplicate_raw = deepcopy(model_json(artifact))
    assert isinstance(duplicate_raw, dict)
    duplicate_events = duplicate_raw.get("events")
    assert isinstance(duplicate_events, list)
    duplicate_events.insert(4, deepcopy(duplicate_events[3]))
    duplicate = PaperLedgerArtifact.model_validate(duplicate_raw)
    contaminated = _mutated_artifact(
        artifact, PayloadMutation(2, "destination", "broker")
    )
    malformed = deepcopy(fixture)
    assert isinstance(malformed, dict)
    malformed_recommendation = malformed.get("recommendation")
    assert isinstance(malformed_recommendation, dict)
    malformed_recommendation["quantity"] = "-1"
    numeric_fee_bps = deepcopy(fixture)
    assert isinstance(numeric_fee_bps, dict)
    numeric_fee_model = numeric_fee_bps.get("fee_model")
    assert isinstance(numeric_fee_model, dict)
    numeric_fee_model["fee_bps"] = 10
    numeric_money = deepcopy(fixture)
    assert isinstance(numeric_money, dict)
    numeric_balances = numeric_money.get("starting_balances")
    assert isinstance(numeric_balances, list)
    numeric_balance = numeric_balances[0]
    assert isinstance(numeric_balance, dict)
    numeric_balance["cash"] = 1000000.0
    numeric_quantity = deepcopy(fixture)
    assert isinstance(numeric_quantity, dict)
    numeric_recommendation = numeric_quantity.get("recommendation")
    assert isinstance(numeric_recommendation, dict)
    numeric_recommendation["quantity"] = 10
    credential = deepcopy(fixture)
    assert isinstance(credential, dict)
    credential["access_token"] = None

    probes = {
        "stale_state": _error_code(artifact, stale),
        "dirty_worktree": _error_code(artifact, dirty),
        "misleading_success_output": _error_code(broken, misleading),
        "malformed_input": _compile_error(malformed),
        "repeated_interruption": _error_code(duplicate, clean),
        "live_state_contamination": _error_code(contaminated, clean),
    }
    expected = {name: name for name in probes}
    decimal_string_probes = {
        "numeric_fee_bps": _compile_error(numeric_fee_bps),
        "numeric_money": _compile_error(numeric_money),
        "numeric_quantity": _compile_error(numeric_quantity),
    }
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("src/v8").glob("*.py"))
        if path.name != "acceptance.py"
    )
    checks = {
        "verified": result.state == "pass",
        "cash": result.cash == {"KRW": "899900.00"},
        "position": str(result.positions[0].quantity) == "10"
        and str(result.positions[0].cost_basis) == "100000.00",
        "fill": str(result.fills[0].gross_notional) == "100000.00"
        and str(result.fills[0].fee) == "100.00"
        and str(result.fills[0].net_cash_delta) == "-100100.00",
        "deterministic": compile_fixture(fixture) == artifact,
        "claimed_ids_and_hashes": claimed.events == artifact.events
        and claimed.recommendation.paper_recommendation_id
        == artifact.recommendation.paper_recommendation_id
        and claimed.expected_after_replay == artifact.expected_after_replay,
        "hash_chain": result.last_event_hash == artifact.events[-1].event_hash,
        "failure_probes": probes == expected,
        "decimal_string_boundary": all(
            code == FailureCode.MALFORMED_INPUT.value
            for code in decimal_string_probes.values()
        ),
        "paper_only": result.forbidden_keys == ()
        and result.broker_destinations == ()
        and result.live_orders == ()
        and _compile_error(credential)
        == FailureCode.LIVE_STATE_CONTAMINATION.value,
        "offline_isolation": all(
            token not in source_text
            for token in (
                "src.portfolio",
                "data/portfolio",
                "config.yaml",
                "os.environ",
                "client.messages.create",
            )
        ),
    }
    return _JSON.validate_python({
        "state": "pass" if all(checks.values()) else "fail",
        "acceptance_count": len(checks),
        "checks": checks,
        "failure_probes": probes,
        "decimal_string_probes": decimal_string_probes,
    })
