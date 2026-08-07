from datetime import datetime
from decimal import Decimal

from src.v4.models import JsonValue, canonical_hash
from src.v6.models import JsonBoundary

from .value_artifact import ValueArtifact, ValueArtifactBody, verify_value_artifact
from .value_models import ValueContractError, ValueErrorCode
from .value_observations import PairedObservation, observation_hash, outcome_hash, output_hash
from .value_trust import ValueTrustContext


def _rehash_artifact(artifact: ValueArtifact) -> JsonValue:
    body = ValueArtifactBody.model_validate(artifact.model_dump(mode="json", exclude={"artifact_hash"}))
    body_value = JsonBoundary.model_validate(body.model_dump(mode="json")).root
    return JsonBoundary.model_validate({**body.model_dump(mode="json"), "artifact_hash": str(canonical_hash(body_value))}).root


def _rehashed_sample(sample: PairedObservation) -> PairedObservation:
    return sample.model_copy(update={"content_hash": observation_hash(sample)})


def _rejected(artifact: ValueArtifact, context: ValueTrustContext, expected: ValueErrorCode) -> bool:
    try:
        _ = verify_value_artifact(_rehash_artifact(artifact), context)
    except ValueContractError as error:
        return error.code == expected
    return False


def run_external_attacks(artifact: ValueArtifact, context: ValueTrustContext) -> dict[str, bool]:
    rows = artifact.observations
    ticker = rows[0]
    ticker_off = ticker.off.model_copy(update={"ticker": "FORGED"})
    ticker_on = ticker.on.model_copy(update={"ticker": "FORGED"})
    ticker_masked = ticker.masked.model_copy(update={"ticker": "FORGED"})
    ticker = ticker.model_copy(update={
        "ticker": "FORGED",
        "off": ticker_off.model_copy(update={"output_hash": output_hash(ticker_off)}),
        "on": ticker_on.model_copy(update={"output_hash": output_hash(ticker_on)}),
        "masked": ticker_masked.model_copy(update={"output_hash": output_hash(ticker_masked)}),
    })
    ticker = _rehashed_sample(ticker)
    edge = rows[1]
    edge_on = edge.on.model_copy(update={"edge_5": Decimal("999")})
    edge = _rehashed_sample(edge.model_copy(update={"on": edge_on.model_copy(update={"output_hash": output_hash(edge_on)})}))
    outcome = rows[2]
    outcome_body = outcome.outcome.model_copy(update={"instrument_return_5": Decimal("999"), "outcome_cutoff": datetime.fromisoformat("2099-01-01T00:00:00+00:00")})
    outcome = _rehashed_sample(outcome.model_copy(update={"outcome": outcome_body.model_copy(update={"outcome_hash": outcome_hash(outcome_body)})}))
    composite_rows = (ticker, edge, outcome, *rows[3:300])
    composite = artifact.model_copy(update={"observations": composite_rows})
    extra = artifact.model_copy(update={"observations": (*rows, rows[-1])})
    stale_repeat = artifact.model_copy(update={"repeat_run_hashes": (artifact.repeat_run_hashes[0], "sha256:" + "f" * 64, artifact.repeat_run_hashes[0])})
    lowered = artifact.model_copy(update={"thresholds": artifact.thresholds.model_copy(update={"verdict_lift_lower_90_min": Decimal("-999")})})
    source = rows[3].model_copy(update={"source_manifest_root": "sha256:" + "f" * 64})
    source = _rehashed_sample(source)
    source_rows = (*rows[:3], source, *rows[4:])
    aggregate = artifact.model_copy(update={"metrics": artifact.metrics.model_copy(update={"coverage_rate": Decimal("1")})})
    dropped = artifact.model_copy(update={"observations": rows[:300]})
    provenance = artifact.source_binding.provenance_bundle.artifact.model_copy(update={"provenance_hash": "sha256:" + "f" * 64})
    bundle = artifact.source_binding.provenance_bundle.model_copy(update={"artifact": provenance})
    bad_prd01 = artifact.model_copy(update={"source_binding": artifact.source_binding.model_copy(update={"provenance_bundle": bundle})})
    quality = artifact.source_binding.quality_artifact.model_copy(update={"source_registry_root": "sha256:" + "f" * 64})
    bad_prd02 = artifact.model_copy(update={"source_binding": artifact.source_binding.model_copy(update={"quality_artifact": quality})})
    return {
        "oracle_composite_300_ticker_edge_outcome_repeat": _rejected(composite, context, "INVENTORY_MISMATCH"),
        "dropped_sample": _rejected(dropped, context, "INVENTORY_MISMATCH"),
        "extra_sample": _rejected(extra, context, "DUPLICATE_SAMPLE_ID"),
        "identity_substitution_rehashed": _rejected(artifact.model_copy(update={"observations": (ticker, *rows[1:])}), context, "INVENTORY_MISMATCH"),
        "arm_edge_rehashed": _rejected(artifact.model_copy(update={"observations": (rows[0], edge, *rows[2:])}), context, "OBSERVATION_HASH_MISMATCH"),
        "outcome_result_cutoff_rehashed": _rejected(artifact.model_copy(update={"observations": (*rows[:2], outcome, *rows[3:])}), context, "OUTCOME_HASH_MISMATCH"),
        "stale_repeat_hash": _rejected(stale_repeat, context, "REPEAT_HASH_MISMATCH"),
        "threshold_lowering": _rejected(lowered, context, "POLICY_MISMATCH"),
        "source_lineage_root_mismatch": _rejected(artifact.model_copy(update={"observations": source_rows}), context, "SOURCE_LINEAGE_MISMATCH"),
        "prd01_trusted_root_mismatch": _rejected(bad_prd01, context, "PRD01_LINEAGE_INVALID"),
        "prd02_registry_root_mismatch": _rejected(bad_prd02, context, "PRD02_LINEAGE_INVALID"),
        "aggregate_forgery": _rejected(aggregate, context, "AGGREGATE_METRIC_MISMATCH"),
    }
