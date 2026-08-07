from dataclasses import dataclass
from pathlib import Path
from typing import override

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash

from .candidate_artifact import (
    CandidateArtifact,
    CandidateArtifactBody,
    artifact_body_json,
)
from .candidate_contract import build_candidate_artifact
from .candidate_fixture_models import CandidateFixture, FIXTURE_ADAPTER
from .candidate_probes import observed_decisions
from .models import FIXTURE_SCHEMA_VERSION, CandidateDecision, RejectionCode


@dataclass(frozen=True, slots=True)
class CandidateFixtureError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return f"perspective candidate fixture: {self.detail}"


def load_fixture(path: Path) -> CandidateFixture:
    try:
        fixture = FIXTURE_ADAPTER.validate_json(path.read_bytes())
    except ValidationError as error:
        raise CandidateFixtureError(str(error)) from error
    if fixture.schema_version != FIXTURE_SCHEMA_VERSION:
        raise CandidateFixtureError(
            f"expected schema {FIXTURE_SCHEMA_VERSION}, got {fixture.schema_version}"
        )
    return fixture


def _code_value(code: RejectionCode | None) -> JsonValue:
    return code.value if code is not None else None


def _integrity_check(name: str, passed: bool) -> JsonValue:
    return {"name": name, "state": "pass" if passed else "fail"}


def _artifact_rejected(artifact: CandidateArtifact) -> bool:
    try:
        _ = CandidateArtifact.model_validate(artifact.model_dump(mode="json"))
    except ValidationError:
        return True
    return False


def _expected_integrity(
    expected_names: tuple[str, ...], observed_names: set[str]
) -> tuple[bool, bool]:
    unique = bool(expected_names) and len(expected_names) == len(set(expected_names))
    complete = set(expected_names) == observed_names
    return unique, complete


def verify_fixture(fixture: CandidateFixture) -> JsonValue:
    observed = observed_decisions(fixture)
    expected_names = tuple(expected.check for expected in fixture.expected)
    observed_names = set(observed)
    names_unique, names_complete = _expected_integrity(expected_names, observed_names)
    empty_expected_rejected = not all(_expected_integrity((), observed_names))
    duplicate_probe = (
        (*expected_names, expected_names[0])
        if expected_names
        else ("duplicate_probe", "duplicate_probe")
    )
    duplicate_expected_rejected = not all(
        _expected_integrity(duplicate_probe, observed_names)
    )
    artifact = build_candidate_artifact(fixture.base_candidate)
    hash_tamper_rejected = _artifact_rejected(
        artifact.model_copy(update={"artifact_hash": f"sha256:{'0' * 64}"})
    )
    proposal_hash_tamper_rejected = _artifact_rejected(
        artifact.model_copy(update={"candidate_proposal_hash": f"sha256:{'0' * 64}"})
    )
    identity_tamper_rejected = _artifact_rejected(
        artifact.model_copy(update={"candidate_id": "pcand_v6_other_candidate"})
    )
    rejected_artifact = build_candidate_artifact(fixture.quant_clone_candidate)
    forged_decision = CandidateDecision(
        accepted_for_evaluation=True,
        rejection_code=None,
    )
    forged_body = CandidateArtifactBody.model_validate(
        {
            **rejected_artifact.model_dump(mode="json", exclude={"artifact_hash"}),
            "decision": forged_decision.model_dump(mode="json"),
        }
    )
    decision_forgery_rejected = _artifact_rejected(
        rejected_artifact.model_copy(
            update={
                "decision": forged_decision,
                "artifact_hash": canonical_hash(artifact_body_json(forged_body)),
            }
        )
    )
    checks: list[JsonValue] = [
        _integrity_check("fixture_expected_names_unique", names_unique),
        _integrity_check("fixture_expected_names_complete", names_complete),
        _integrity_check("artifact_tampered_hash_rejected", hash_tamper_rejected),
        _integrity_check(
            "artifact_tampered_proposal_hash_rejected",
            proposal_hash_tamper_rejected,
        ),
        _integrity_check("artifact_tampered_identity_rejected", identity_tamper_rejected),
        _integrity_check(
            "artifact_rehashed_decision_forgery_rejected",
            decision_forgery_rejected,
        ),
        _integrity_check("fixture_empty_expected_rejected", empty_expected_rejected),
        _integrity_check("fixture_duplicate_expected_rejected", duplicate_expected_rejected),
    ]
    pass_count = sum(
        int(passed)
        for passed in (
            names_unique,
            names_complete,
            hash_tamper_rejected,
            proposal_hash_tamper_rejected,
            identity_tamper_rejected,
            decision_forgery_rejected,
            empty_expected_rejected,
            duplicate_expected_rejected,
        )
    )
    for expected in fixture.expected:
        actual = observed.get(expected.check)
        passed = actual == CandidateDecision(
            accepted_for_evaluation=expected.accepted_for_evaluation,
            rejection_code=expected.rejection_code,
        )
        pass_count += int(passed)
        checks.append(
            {
                "name": expected.check,
                "state": "pass" if passed else "fail",
                "expected": {
                    "accepted_for_evaluation": expected.accepted_for_evaluation,
                    "rejection_code": _code_value(expected.rejection_code),
                },
                "actual": (
                    {
                        "accepted_for_evaluation": actual.accepted_for_evaluation,
                        "rejection_code": _code_value(actual.rejection_code),
                    }
                    if actual is not None
                    else None
                ),
            }
        )
    total = len(fixture.expected) + 8
    return {
        "state": "pass" if pass_count == total else "fail",
        "schema_version": fixture.schema_version,
        "pass_count": pass_count,
        "total": total,
        "checks": checks,
    }
