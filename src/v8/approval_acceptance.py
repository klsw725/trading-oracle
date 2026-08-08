from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Final, override

from pydantic import TypeAdapter

from src.v4.models import JsonValue, canonical_hash
from src.v8.approval_compiler import (
    BrokerValidationCapability,
    compile_approval_fixture,
)
from src.v8.approval_ledger import ApprovalLedger, append_approval_request
from src.v8.approval_models import ApprovalErrorCode, ApprovalFixture
from src.v8.approval_verifier import verify_approval_artifact
from src.v8.identity import model_json

FIXTURE_PATH: Final = Path(
    "docs/specs/v8/fixtures/prd02-operator-approval-dry-run.json"
)
_JSON: Final = TypeAdapter[JsonValue](JsonValue)


class UnavailableBroker(BrokerValidationCapability):
    validation_available: bool
    calls: int

    def __init__(self) -> None:
        self.validation_available = False
        self.calls = 0

    @override
    def validate(self, fixture: ApprovalFixture) -> JsonValue:
        self.calls += 1
        response = fixture.broker_dry_run_response
        assert response is not None
        return model_json(response)


def _fixture_value() -> JsonValue:
    return _JSON.validate_json(FIXTURE_PATH.read_bytes())


def _record(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    return value


def _nested(record: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    value = record[key]
    assert isinstance(value, dict)
    return value


def _compile_probe(value: JsonValue) -> tuple[str, str | None]:
    result = compile_approval_fixture(value)
    return result.approval_status, result.error_code.value if result.error_code else None


def run_approval_acceptance() -> JsonValue:
    fixture = _fixture_value()
    artifact = compile_approval_fixture(fixture).artifact
    assert artifact is not None
    verified = verify_approval_artifact(model_json(artifact))

    stale = deepcopy(fixture)
    _nested(_record(stale), "approval_decision")["approved_at"] = (
        "2026-08-06T09:07:45+09:00"
    )
    expired = deepcopy(fixture)
    _nested(_record(expired), "dry_run_request")["requested_at"] = (
        "2026-08-06T09:12:01+09:00"
    )
    malformed_response = deepcopy(fixture)
    _nested(_record(malformed_response), "broker_dry_run_response")[
        "broker_order_id"
    ] = None
    misleading = deepcopy(fixture)
    _nested(_record(misleading), "broker_dry_run_response")["live_submission"] = True
    dirty = deepcopy(fixture)
    _nested(_nested(_record(dirty), "proposed_order"), "quote_ref")["source_hash"] = (
        "sha256:" + "0" * 64
    )
    forbidden_null = deepcopy(fixture)
    _record(forbidden_null)["stage"] = None
    claimed_ids = deepcopy(fixture)
    _nested(_record(claimed_ids), "proposed_order")["proposed_order_id"] = "claimed"
    stale_before_dry_run = deepcopy(fixture)
    _nested(_record(stale_before_dry_run), "dry_run_request")["requested_at"] = (
        "2026-08-06T09:07:31+09:00"
    )
    self_approval = deepcopy(fixture)
    _nested(
        _nested(_record(self_approval), "proposed_order"), "permission_context"
    )["proposed_by"] = "operator_approver_01"

    ledger = ApprovalLedger.empty()
    first = append_approval_request(ledger, compile_approval_fixture(fixture))
    duplicate = append_approval_request(first.ledger, compile_approval_fixture(fixture))
    conflict = deepcopy(fixture)
    _nested(_record(conflict), "proposed_order")["ticker"] = "000660"
    conflicted = append_approval_request(
        first.ledger, compile_approval_fixture(conflict)
    )
    interrupted = append_approval_request(
        duplicate.ledger, compile_approval_fixture(fixture)
    )
    duplicate_artifact = deepcopy(model_json(artifact))
    duplicate_records = _record(duplicate_artifact)["records"]
    assert isinstance(duplicate_records, list)
    duplicate_response = deepcopy(_record(duplicate_records[-1]))
    duplicate_response.update({"artifact_id": "adry_v8_fresh_duplicate", "prev_record_hash": duplicate_response["record_hash"]})
    duplicate_response["record_hash"] = canonical_hash({key: value for key, value in duplicate_response.items() if key != "record_hash"})
    duplicate_records.append(duplicate_response)
    interrupted_verification = verify_approval_artifact(duplicate_artifact)

    forbidden_artifact = deepcopy(model_json(artifact))
    forbidden_records = _record(forbidden_artifact)["records"]
    assert isinstance(forbidden_records, list)
    _record(_record(forbidden_records[0])["payload"])["embedded"] = {"account_number": None}
    previous_hash = "sha256:genesis"
    for value in forbidden_records:
        record = _record(value)
        record["prev_record_hash"] = previous_hash
        seed = {key: item for key, item in record.items() if key != "record_hash"}
        previous_hash = canonical_hash(seed)
        record["record_hash"] = previous_hash
    forbidden_result = verify_approval_artifact(forbidden_artifact)
    forbidden_payload_result = (forbidden_result.approval_status, forbidden_result.errors[0].value if forbidden_result.errors else None)

    decimal_results: list[tuple[str, str | None]] = []
    decimal_mutations = (
        (("proposed_order", "permission_context", "max_notional"), 200000), (("proposed_order", "quantity"), 10),
        (("proposed_order", "limit_price"), 10000), (("proposed_order", "estimated_notional"), 100000),
        (("broker_dry_run_response", "estimated_fee"), 100), (("broker_dry_run_response", "estimated_tax"), 0),
        (("broker_dry_run_response", "estimated_cash_effect"), -100100),
    )
    for path, numeric_value in decimal_mutations:
        numeric_decimal = deepcopy(fixture)
        target = _record(numeric_decimal)
        for key in path[:-1]:
            target = _nested(target, key)
        target[path[-1]] = numeric_value
        decimal_results.append(_compile_probe(numeric_decimal))

    unavailable_value = deepcopy(fixture)
    _record(unavailable_value)["broker_dry_run_response"] = None
    unavailable = UnavailableBroker()
    unavailable_result = compile_approval_fixture(unavailable_value, unavailable)

    probes = {
        "stale_quote": _compile_probe(stale),
        "expired_approval": _compile_probe(expired),
        "malformed_response": _compile_probe(malformed_response),
        "dirty_input": _compile_probe(dirty),
        "misleading_success": _compile_probe(misleading),
        "malformed_json": _compile_probe(forbidden_null),
        "broker_validation_unavailable": (
            unavailable_result.approval_status,
            unavailable_result.error_code.value if unavailable_result.error_code else None,
        ),
        "quote_expired_before_dry_run": _compile_probe(stale_before_dry_run),
        "permission_separation": _compile_probe(self_approval),
        "idempotency_conflict": (
            "proposed",
            conflicted.error_code.value if conflicted.error_code else None,
        ),
        "repeated_interruption": (
            "dry_run_passed",
            (
                interrupted_verification.errors[0].value
                if interrupted_verification.errors
                else None
            ),
        ),
        "forbidden_persisted_payload": forbidden_payload_result,
    }
    expected = {
        "stale_quote": ("expired", ApprovalErrorCode.STALE_QUOTE.value),
        "expired_approval": ("expired", ApprovalErrorCode.APPROVAL_EXPIRED.value),
        "malformed_response": (
            "dry_run_failed",
            ApprovalErrorCode.FORBIDDEN_FIELD_PRESENT.value,
        ),
        "dirty_input": ("dry_run_failed", ApprovalErrorCode.DIRTY_INPUT.value),
        "misleading_success": (
            "dry_run_failed",
            ApprovalErrorCode.MISLEADING_SUCCESS_OUTPUT.value,
        ),
        "malformed_json": ("proposed", ApprovalErrorCode.MALFORMED_INPUT.value),
        "broker_validation_unavailable": (
            "dry_run_failed",
            ApprovalErrorCode.BROKER_VALIDATION_UNAVAILABLE.value,
        ),
        "quote_expired_before_dry_run": (
            "expired",
            ApprovalErrorCode.STALE_QUOTE.value,
        ),
        "permission_separation": (
            "checklisted",
            ApprovalErrorCode.SELF_APPROVAL_FORBIDDEN.value,
        ),
        "idempotency_conflict": (
            "proposed",
            ApprovalErrorCode.IDEMPOTENCY_CONFLICT.value,
        ),
        "repeated_interruption": (
            "dry_run_passed",
            ApprovalErrorCode.REPEATED_INTERRUPTION.value,
        ),
        "forbidden_persisted_payload": (
            "dry_run_failed",
            ApprovalErrorCode.FORBIDDEN_FIELD_PRESENT.value,
        ),
    }
    checks = {
        "happy_dry_run_passed": artifact.approval_status == "dry_run_passed",
        "strict_no_real_order": not artifact.live_submission
        and artifact.would_accept
        and not artifact.portfolio_mutated,
        "persisted_artifact_verified": verified.verification_status == "pass",
        "five_failure_fixtures": probes["stale_quote"] == expected["stale_quote"]
        and duplicate.returned_existing
        and probes["expired_approval"] == expected["expired_approval"]
        and probes["malformed_response"] == expected["malformed_response"]
        and interrupted.returned_existing,
        "normative_probes": probes == expected,
        "idempotent_replay": duplicate.artifact == first.artifact
        and duplicate.ledger == first.ledger
        and interrupted.ledger == first.ledger,
        "conflict_appends_nothing": conflicted.error_code
        is ApprovalErrorCode.IDEMPOTENCY_CONFLICT
        and conflicted.ledger == first.ledger,
        "claimed_boundaries_recomputed": (
            (claimed_artifact := compile_approval_fixture(claimed_ids).artifact) is not None
            and claimed_artifact.proposed_order.proposed_order_id
            == artifact.proposed_order.proposed_order_id
            and claimed_artifact.proposed_order.proposed_order_id != "claimed"
            and claimed_artifact.approval_decision.approval_decision_id
            == artifact.approval_decision.approval_decision_id
            and claimed_artifact.dry_run_request.dry_run_request_id
            == artifact.dry_run_request.dry_run_request_id
            and claimed_artifact.broker_dry_run_response.dry_run_response_id
            == artifact.broker_dry_run_response.dry_run_response_id
        ),
        "unavailable_adapter_not_called": unavailable.calls == 0,
        "approval_status_only": all(
            key not in {"state", "stage"}
            for record in artifact.records
            for key in _record(model_json(record))
        ),
        "permission_separation": probes["permission_separation"]
        == expected["permission_separation"],
        "freshness_checked_twice": probes["stale_quote"]
        == expected["stale_quote"]
        and probes["quote_expired_before_dry_run"]
        == expected["quote_expired_before_dry_run"],
        "strict_decimal_strings": all(
            result == ("proposed", ApprovalErrorCode.MALFORMED_INPUT.value)
            for result in decimal_results
        ),
    }
    return _JSON.validate_python(
        {
            "verification_status": "pass" if all(checks.values()) else "fail",
            "acceptance_count": len(checks),
            "checks": checks,
            "failure_probes": {
                name: {"approval_status": value[0], "error_code": value[1]}
                for name, value in probes.items()
            },
        }
    )
