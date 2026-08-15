from __future__ import annotations

from typing import Final

from pydantic import TypeAdapter, ValidationError

from src.v11.canonical import canonical_hash, normalize_scalar, parse_json, reject_forbidden
from src.v4.models import canonical_json
from src.v13.models import V13ContractError
from src.v13.coverage import verify_inventory
from src.v13.prd04_bundle import build_bundle
from src.v13.prd04_models import Prd04Bundle


_BUNDLE: Final = TypeAdapter(Prd04Bundle)


def verify_bundle(payload: bytes) -> Prd04Bundle:
    value = parse_json(payload)
    reject_forbidden(value)
    try:
        bundle = _BUNDLE.validate_json(payload)
    except ValidationError as error:
        raise V13ContractError("V13_BUNDLE_MALFORMED", str(error)) from error
    if bundle.fixture_hash != canonical_hash(normalize_scalar(
            bundle.source_fixture.model_dump(mode="json"))):
        raise V13ContractError("V13_FIXTURE_HASH", "source_fixture")
    body = normalize_scalar(bundle.model_dump(mode="json", exclude={"bundle_hash"}))
    if bundle.bundle_hash != canonical_hash(body):
        raise V13ContractError("V13_BUNDLE_HASH", bundle.bundle_hash)
    verify_inventory(tuple(item.probe_id for item in bundle.probes))
    candidate_ids = tuple(sorted(item.candidate_id
        for item in bundle.source_fixture.candidate_fixture))
    symbols = tuple(sorted({item.symbol
        for item in bundle.source_fixture.candidate_fixture}))
    if (bundle.inventory.candidate_ids != candidate_ids
            or bundle.inventory.candidate_inventory_hash != canonical_hash(list(candidate_ids))
            or bundle.inventory.canonical_symbols != symbols
            or bundle.inventory.symbol_inventory_hash != canonical_hash(list(symbols))):
        raise V13ContractError("V13_INVENTORY_BINDING", "candidate_or_symbol")
    if any(item.lineage.v12_bundle_hash != bundle.upstream.v12_bundle_hash
            or item.lineage.v12_run_hash != bundle.upstream.v12_run_hash
            or item.lineage.v12_candidate_id != item.candidate_id
            or item.lineage.verified_account_hash != bundle.upstream.verified_account_hash
            for item in bundle.source_fixture.candidate_fixture):
        raise V13ContractError("V13_CANDIDATE_LINEAGE", "upstream")
    rebuilt = build_bundle(bundle.source_fixture)
    if canonical_json(rebuilt.model_dump(mode="json")) != canonical_json(
            bundle.model_dump(mode="json")):
        raise V13ContractError("V13_DERIVED_FIELD_MISMATCH", "bundle")
    return bundle
