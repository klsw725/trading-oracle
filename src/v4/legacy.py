from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from src.v4.models import ContentHash, JsonValue, canonical_hash, sha256_bytes
from .legacy_models import (
    LegacyAuditEligibility,
    LegacyDerivedAudit,
    LegacyField,
    LegacyInventoryReport,
    LegacyMigrationTier,
    LegacyParseState,
    LegacyProvenance,
    LegacyRecommendationAudit,
    LegacyRecommendationId,
    LegacySnapshotId,
    LegacySourceInventory,
)


POLICY_VERSION: Final = "v4.phase24.1"
EXPECTED_SOURCE_COUNT: Final = 82
UNKNOWN_NATIVE_FIELDS: Final = ("raw_prompt", "prompt_hash", "raw_provider_response", "provider_request_id", "decision_data_cutoff_at", "candidate_universe", "candidate_rejections", "portfolio_state", "risk_state")
_JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)

__all__ = (
    "EXPECTED_SOURCE_COUNT",
    "POLICY_VERSION",
    "LegacyAuditEligibility",
    "LegacyDerivedAudit",
    "LegacyField",
    "LegacyInventoryReport",
    "LegacyMigrationTier",
    "LegacyParseState",
    "LegacyProvenance",
    "LegacyRecommendationAudit",
    "LegacyRecommendationId",
    "LegacySnapshotId",
    "LegacySourceInventory",
    "build_legacy_derived_audit",
    "inventory_legacy_snapshot",
    "inventory_legacy_sources",
    "legacy_derived_body",
)


def _field(record: dict[str, JsonValue], key: str) -> LegacyField:
    if key in record:
        return LegacyField(record[key], LegacyProvenance.DIRECT)
    return LegacyField(None, LegacyProvenance.UNKNOWN)


def _recommendation(snapshot_id: LegacySnapshotId, index: int, item: tuple[str, JsonValue]) -> LegacyRecommendationAudit:
    ticker, value = item
    record = value if isinstance(value, dict) else {}
    price = record.get("price")
    perspectives = record.get("perspectives")
    malformed = (
        isinstance(price, bool)
        or not isinstance(price, int | float)
        or not isinstance(perspectives, list)
    )
    failures = ("malformed_recommendation_record",) if malformed else ()
    verdict = record.get("consensus_verdict")
    identity_hash = canonical_hash(
        {
            "consensus_verdict": verdict,
            "legacy_snapshot_id": snapshot_id,
            "recommendation_price": price,
            "source_record_index": index,
            "ticker": ticker,
        }
    )
    recommendation_id = LegacyRecommendationId(
        f"legacy_rec_{identity_hash.removeprefix('sha256:')[:20]}"
    )
    return LegacyRecommendationAudit(
        recommendation_id,
        index,
        LegacyField(ticker, LegacyProvenance.DIRECT),
        _field(record, "name"),
        _field(record, "price"),
        _field(record, "consensus_verdict"),
        _field(record, "perspectives"),
        UNKNOWN_NATIVE_FIELDS,
        failures,
    )


def _snapshot_id(source_path: Path, source_hash: ContentHash) -> LegacySnapshotId:
    identity_hash = canonical_hash(
        {
            "policy_version": POLICY_VERSION,
            "source_path": source_path.as_posix(),
            "source_sha256": source_hash,
        }
    )
    return LegacySnapshotId(
        f"legacy_snap_{identity_hash.removeprefix('sha256:')[:20]}"
    )


def inventory_legacy_snapshot(source_path: Path) -> LegacySourceInventory:
    source_bytes = source_path.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    empty_date = LegacyField(None, LegacyProvenance.UNKNOWN)
    empty_market = LegacyField(None, LegacyProvenance.UNKNOWN)
    try:
        value = _JSON_ADAPTER.validate_json(source_bytes)
    except ValidationError as error:
        return LegacySourceInventory(
            source_path, source_hash, len(source_bytes), LegacyParseState.MALFORMED,
            LegacyMigrationTier.T0_SOURCE_INVENTORY, 0, str(error), empty_date,
            empty_market, (),
        )

    match value:  # noqa: MATCH_OK - untrusted JSON has an intentional fallback
        case {"date": str() as date, "recommendations": dict() as recommendations} as source:
            snapshot_id = _snapshot_id(source_path, source_hash)
            records = tuple(
                _recommendation(snapshot_id, index, item)
                for index, item in enumerate(recommendations.items())
            )
            return LegacySourceInventory(
                source_path, source_hash, len(source_bytes), LegacyParseState.PARSED,
                LegacyMigrationTier.T1_STRUCTURAL_AUDIT, len(records), None,
                LegacyField(date, LegacyProvenance.DIRECT), _field(source, "market"),
                records,
            )
        case _:
            return LegacySourceInventory(
                source_path, source_hash, len(source_bytes),
                LegacyParseState.MISSING_REQUIRED_FIELD,
                LegacyMigrationTier.T0_SOURCE_INVENTORY, 0,
                "date and recommendations are required legacy fields",
                empty_date, empty_market, (),
            )


def inventory_legacy_sources(source_paths: Iterable[Path]) -> LegacyInventoryReport:
    records = tuple(inventory_legacy_snapshot(path) for path in sorted(source_paths, key=lambda path: path.as_posix()))
    parsed_count = sum(record.parse_state is LegacyParseState.PARSED for record in records)
    invalid_count = sum(len(record.failure_states) for source in records for record in source.recommendation_records)
    count_matches = len(records) == EXPECTED_SOURCE_COUNT
    complete = count_matches and parsed_count == len(records) and invalid_count == 0
    failures = tuple(state for failed, state in ((not count_matches, "source_count_mismatch"), (parsed_count != len(records), "invalid_legacy_source"), (invalid_count > 0, "invalid_legacy_record")) if failed)
    return LegacyInventoryReport(
        EXPECTED_SOURCE_COUNT, records, parsed_count, len(records) - parsed_count,
        invalid_count, count_matches, complete, complete, failures,
    )


def legacy_derived_body(
    inventory: LegacySourceInventory | LegacyDerivedAudit,
) -> Mapping[str, JsonValue]:
    eligibility = LegacyAuditEligibility(
        outcome_audit_overlay_eligible=inventory.parse_state is LegacyParseState.PARSED
    )
    records: list[JsonValue] = []
    for record in inventory.recommendation_records:
        records.append(
            {
                "consensus_verdict": {"value": record.consensus_verdict.value, "provenance": record.consensus_verdict.provenance},
                "failure_states": list(record.failure_states),
                "blocked": bool(record.failure_states),
                "legacy_recommendation_id": record.legacy_recommendation_id,
                "name": {"value": record.name.value, "provenance": record.name.provenance},
                "perspectives": {"value": record.perspectives.value, "provenance": record.perspectives.provenance},
                "recommendation_price": {"value": record.recommendation_price.value, "provenance": record.recommendation_price.provenance, "phase22_entry_price": False},
                "source_record_index": record.source_record_index,
                "ticker": {"value": record.ticker.value, "provenance": record.ticker.provenance},
                "unknown_native_fields": list(record.unknown_native_fields),
            }
        )
    return {
        "audit_only": eligibility.audit_only,
        "canonical_metric_eligible": eligibility.canonical_metric_eligible,
        "eligibility": {
            "adaptive_weight_eligible": eligibility.adaptive_weight_eligible,
            "calibration_eligible": eligibility.calibration_eligible,
            "outcome_audit_overlay_eligible": eligibility.outcome_audit_overlay_eligible,
            "outcome_replay_eligible": eligibility.outcome_replay_eligible,
            "recompute_replay_eligible": eligibility.recompute_replay_eligible,
            "verbatim_replay_eligible": eligibility.verbatim_replay_eligible,
        },
        "legacy_snapshot_id": _snapshot_id(inventory.source_path, inventory.source_hash),
        "migration_tier": inventory.migration_tier,
        "parse_state": inventory.parse_state,
        "policy_version": POLICY_VERSION,
        "records": records,
        "schema_version": "v4.legacy_backfill.snapshot.phase24.1",
        "source": {
            "market": {"value": inventory.source_market.value, "provenance": inventory.source_market.provenance},
            "source_path": inventory.source_path.as_posix(),
            "source_sha256": inventory.source_hash,
            "source_snapshot_date": {"value": inventory.source_snapshot_date.value, "provenance": inventory.source_snapshot_date.provenance},
        },
    }


def build_legacy_derived_audit(inventory: LegacySourceInventory) -> LegacyDerivedAudit:
    body = legacy_derived_body(inventory)
    derived_hash = canonical_hash(dict(body))
    source_link_hash = canonical_hash(
        {
            "derived_artifact_hash": derived_hash,
            "policy_version": POLICY_VERSION,
            "source_path": inventory.source_path.as_posix(),
            "source_sha256": inventory.source_hash,
        }
    )
    return LegacyDerivedAudit(
        POLICY_VERSION, _snapshot_id(inventory.source_path, inventory.source_hash),
        inventory.source_path, inventory.source_hash, inventory.parse_state,
        inventory.migration_tier, inventory.recommendation_count,
        inventory.source_snapshot_date, inventory.source_market,
        inventory.recommendation_records,
        LegacyAuditEligibility(
            outcome_audit_overlay_eligible=inventory.parse_state is LegacyParseState.PARSED
        ),
        derived_hash, source_link_hash,
    )
