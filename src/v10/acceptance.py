from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from src.v4.models import JsonValue, canonical_json

from .build import build_fixture
from .bundle import ArtifactBundle
from .canonical import parse_json_bytes, reject_forbidden
from .models import V10ContractError
from .probe_runner import error_probe
from .spec_contract import ROOT, verify_documents
from .verifier import verify_bundle


FIXTURES: Final[dict[int, Path]] = {
    1: ROOT / "docs/specs/v10/fixtures/prd01-calendar-minute.json",
    2: ROOT / "docs/specs/v10/fixtures/prd02-aggregation-revision.json",
    3: ROOT / "docs/specs/v10/fixtures/prd03-universe-actions.json",
    4: ROOT / "docs/specs/v10/fixtures/prd04-context.json",
}


def load_fixture(path: Path) -> JsonValue:
    try:
        value = parse_json_bytes(path.read_bytes())
    except OSError as error:
        raise V10ContractError("V10_FIXTURE_ERROR", str(error)) from error
    reject_forbidden(value)
    return value


def build_path(path: Path) -> JsonValue:
    return build_fixture(load_fixture(path))


def accept_prd(prd: Literal[1, 2, 3, 4]) -> JsonValue:
    bundle_value = build_path(FIXTURES[prd])
    verified = verify_bundle(canonical_json(bundle_value))
    failed = tuple(probe for probe in verified.probes if not _passed(probe))
    if failed:
        raise V10ContractError("V10_PROBE_FAILED", str(len(failed)))
    return _summary(verified)


def run_acceptance() -> JsonValue:
    documents = verify_documents()
    reports = tuple(accept_prd(prd) for prd in (1, 2, 3, 4))
    boundary_probes = (
        error_probe("duplicate_key", "V10_JSON_PARSE_ERROR",
                    lambda: parse_json_bytes(b'{"x":1,"x":2}')),
        error_probe("non_finite", "V10_JSON_PARSE_ERROR",
                    lambda: parse_json_bytes(b'{"x":NaN}')),
        error_probe("forbidden_field", "V10_FORBIDDEN_FIELD",
                    lambda: reject_forbidden({"credential": "x"})),
    )
    return {
        "state": "pass",
        "schema_version": "v10.intraday_data_foundation.acceptance.2",
        "documents": documents,
        "fixture_count": len(FIXTURES),
        "artifact_count": sum(_integer(report, "artifact_count") for report in reports),
        "probe_count": sum(_integer(report, "probe_count") for report in reports) + len(boundary_probes),
        "prd_reports": list(reports),
        "boundary_probes": list(boundary_probes),
        "broker_submit_count": 0,
        "portfolio_mutation_count": 0,
    }


def _summary(bundle: ArtifactBundle) -> JsonValue:
    return {"state": "pass", "prd": bundle.prd, "fixture_hash": bundle.fixture_hash,
            "bundle_hash": bundle.bundle_hash, "artifact_count": len(bundle.artifacts),
            "probe_count": len(bundle.probes)}


def _passed(value: JsonValue) -> bool:
    return isinstance(value, dict) and value.get("state") == "pass"


def _integer(value: JsonValue, field: str) -> int:
    match value:  # noqa: MATCH_OK - acceptance summary requires integer field
        case dict() as record if isinstance(record.get(field), int):
            item = record[field]
            return item if isinstance(item, int) else 0
        case _:
            raise V10ContractError("V10_BUNDLE_MALFORMED", field)
