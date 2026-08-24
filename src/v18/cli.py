from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import BinaryIO, Final

from pydantic import ValidationError

from .acceptance import run_acceptance
from .candidates import build_candidate
from .canonical import JsonValue, canonical_json, model_json
from .cohorts import build_manifest, freeze_cohort
from .errors import InputValueError, V18Error
from .fixtures import ROOT, load_fixture
from .models import (
    CandidateTransition,
    CohortSpecification,
    PredictionInput,
)
from .objective import perspective_contributions
from .outcomes import store_evaluation
from .policies import ELIGIBILITY_POLICY, EVALUATOR_POLICY, WEIGHT_POLICY
from .policy_repository import propose_candidate, transition_candidate
from .predictions import build_prediction
from .repository import MeasurementRepository
from .validation import canonical_utc

HELP: Final = (
    b"usage: python -m src.v18.cli {register-prediction,quarantine-legacy,evaluate,"
    b"build-candidate,candidate-transition,prd01-acceptance,prd02-acceptance,"
    b"prd03-acceptance,prd04-acceptance,acceptance}\n"
)
ACCEPTANCE_COMMANDS: Final = {
    "prd01-acceptance",
    "prd02-acceptance",
    "prd03-acceptance",
    "prd04-acceptance",
    "acceptance",
}


def _option(arguments: list[str], name: str) -> str:
    if arguments.count(name) != 1:
        raise V18Error("CLI_USAGE_ERROR", name)
    index = arguments.index(name)
    if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
        raise V18Error("CLI_USAGE_ERROR", name)
    return arguments[index + 1]


def _path(value: str, *, must_exist: bool) -> Path:
    path = (ROOT / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        _ = path.relative_to(ROOT)
    except ValueError as error:
        raise V18Error("PATH_OUTSIDE_PROJECT", value) from error
    if must_exist and not path.is_file():
        raise V18Error("INPUT_NOT_FOUND", value)
    return path


def _register(arguments: list[str]) -> JsonValue:
    if len(arguments) != 5:
        raise V18Error("CLI_USAGE_ERROR", "register-prediction")
    input_path = _path(_option(arguments, "--input"), must_exist=True)
    database = _path(_option(arguments, "--database"), must_exist=False)
    value = PredictionInput.model_validate_json(input_path.read_bytes())
    record = build_prediction(value)
    with MeasurementRepository.open(database, migrate=True) as repository:
        stored = repository.register_prediction(record)
    return {
        "duplicate": stored.duplicate,
        "prediction": model_json(stored.record),
        "schema_version": "v18.register-result.1",
        "status": "PASS",
    }


def _quarantine(arguments: list[str]) -> JsonValue:
    if len(arguments) != 7:
        raise V18Error("CLI_USAGE_ERROR", "quarantine-legacy")
    input_path = _path(_option(arguments, "--input"), must_exist=True)
    database = _path(_option(arguments, "--database"), must_exist=False)
    as_of = canonical_utc(_option(arguments, "--as-of"))
    label = input_path.relative_to(ROOT).as_posix()
    with MeasurementRepository.open(database, migrate=True) as repository:
        stored = repository.quarantine_legacy(
            input_path.read_bytes(), label, "legacy.snapshot.unknown",
            ("MISSING_PREDICTION_IDENTITY",), as_of,
        )
    return {
        "duplicate": stored.duplicate,
        "quarantine": model_json(stored.record),
        "schema_version": "v18.quarantine-result.1",
        "status": "PASS",
    }


def _evaluate(arguments: list[str]) -> JsonValue:
    if len(arguments) != 7:
        raise V18Error("CLI_USAGE_ERROR", "evaluate")
    prediction_id = _option(arguments, "--prediction-id")
    as_of = canonical_utc(_option(arguments, "--as-of"))
    database = _path(_option(arguments, "--database"), must_exist=True)
    fixture = load_fixture()
    with MeasurementRepository.open(database) as repository:
        stored = store_evaluation(
            repository, prediction_id, fixture.sessions, fixture.prices, as_of, EVALUATOR_POLICY
        )
    return {
        "duplicate": stored.duplicate,
        "outcome": model_json(stored.outcome),
        "schema_version": "v18.evaluation-result.1",
        "status": "PASS",
    }


def _build_candidate(arguments: list[str]) -> JsonValue:
    if len(arguments) != 7:
        raise V18Error("CLI_USAGE_ERROR", "build-candidate")
    cohort_path = _path(_option(arguments, "--cohort"), must_exist=True)
    as_of = canonical_utc(_option(arguments, "--as-of"))
    database = _path(_option(arguments, "--database"), must_exist=True)
    specification = CohortSpecification.model_validate_json(cohort_path.read_bytes())
    fixture = load_fixture(specification.namespace.account_id, specification.namespace.arm_id)
    with MeasurementRepository.open(database) as repository:
        manifest = build_manifest(repository, specification, ELIGIBILITY_POLICY)
        _ = freeze_cohort(repository, manifest)
        contributions = perspective_contributions(repository, manifest, WEIGHT_POLICY)
        candidate = build_candidate(
            manifest, specification.namespace, contributions,
            tuple(item for item in fixture.sessions if item.market is specification.namespace.market),
            as_of, WEIGHT_POLICY,
        )
        stored = propose_candidate(repository, candidate)
    return {
        "candidate": model_json(stored),
        "schema_version": "v18.candidate-result.1",
        "status": "PASS",
    }


def _transition(arguments: list[str]) -> JsonValue:
    if len(arguments) != 7:
        raise V18Error("CLI_USAGE_ERROR", "candidate-transition")
    candidate_id = _option(arguments, "--candidate-id")
    try:
        transition = CandidateTransition(_option(arguments, "--transition"))
        as_of = canonical_utc(_option(arguments, "--as-of"))
    except ValueError as error:
        raise V18Error("CLI_USAGE_ERROR", "candidate-transition") from error
    database = _path(_option(arguments, "--database"), must_exist=True)
    with MeasurementRepository.open(database) as repository:
        candidate = transition_candidate(repository, candidate_id, transition, as_of)
    return {
        "candidate": model_json(candidate),
        "schema_version": "v18.candidate-transition-result.1",
        "status": "PASS",
    }


def dispatch(arguments: list[str]) -> JsonValue:
    if not arguments:
        raise V18Error("CLI_USAGE_ERROR", "command required")
    command = arguments[0]
    if command in ACCEPTANCE_COMMANDS:
        if len(arguments) != 1:
            raise V18Error("CLI_USAGE_ERROR", command)
        return run_acceptance()
    registry = {
        "register-prediction": _register,
        "quarantine-legacy": _quarantine,
        "evaluate": _evaluate,
        "build-candidate": _build_candidate,
        "candidate-transition": _transition,
    }
    handler = registry.get(command)
    if handler is None:
        raise V18Error("CLI_USAGE_ERROR", command)
    return handler(arguments)


def run_cli(arguments: list[str], stdout: BinaryIO, stderr: BinaryIO) -> int:
    if arguments == ["--help"]:
        _ = stdout.write(HELP)
        return 0
    try:
        report = dispatch(arguments)
    except (V18Error, InputValueError, ValidationError, sqlite3.Error, OSError) as error:
        code = error.code if isinstance(error, V18Error) else "INVALID_INPUT"
        payload: JsonValue = {"code": code, "schema_version": "v18.error.1", "status": "FAIL"}
        _ = stdout.write(canonical_json(payload) + b"\n")
        acceptance = bool(arguments) and arguments[0] in ACCEPTANCE_COMMANDS
        if acceptance and code != "CLI_USAGE_ERROR":
            return 1
        return 2
    except Exception:  # noqa: BROAD_EXCEPT_OK - final CLI boundary redacts defects.
        payload = {"code": "INTERNAL_ERROR", "schema_version": "v18.error.1", "status": "ERROR"}
        _ = stdout.write(canonical_json(payload) + b"\n")
        _ = stderr.write(b"INTERNAL_ERROR\n")
        return 1
    _ = stdout.write(canonical_json(report) + b"\n")
    return 0


def main(arguments: list[str] | None = None) -> int:
    return run_cli(
        list(sys.argv[1:] if arguments is None else arguments),
        sys.stdout.buffer,
        sys.stderr.buffer,
    )


if __name__ == "__main__":
    raise SystemExit(main())
