import ast
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from src.v4.models import JsonValue
from src.v6.models import JsonBoundary

from .value_artifact import compile_value_artifact, ensure_value_paths, verify_value_artifact
from .value_attacks import remove_value, replace_value, verify_value_attack
from .value_evaluator import evaluate_value
from .value_external_attacks import run_external_attacks
from .value_input import ValueFixture, ValueTrustDocument
from .value_models import ValueContractError, ValueErrorCode, canonical_thresholds
from .value_observations import fact_audit_hash, observation_hash, outcome_hash, outcome_registry_root, output_hash
from .value_trust import cohort_manifest_root, trust_value_fixture


def _reject(action: Callable[[], JsonValue], expected: ValueErrorCode) -> bool:
    try:
        _ = action()
    except ValueContractError as error:
        return error.code == expected
    return False


def _contains_key(value: JsonValue, forbidden: str) -> bool:
    match value:  # noqa: MATCH_OK - recursive JSON variants are fully handled
        case dict() as record:
            return forbidden in record or any(_contains_key(item, forbidden) for item in record.values())
        case list() as items:
            return any(_contains_key(item, forbidden) for item in items)
        case _:
            return False


def _path_safety() -> bool:
    path = Path("value.json")
    try:
        ensure_value_paths(path, path)
    except ValueContractError as error:
        return error.code == "OUTPUT_PATH_UNSAFE"
    return False


def _static_checks() -> tuple[bool, bool]:
    root = Path(__file__).resolve().parent
    forbidden = ("src.data", "src.consensus", "src.common", "main")
    imports_clean = True
    loc_clean = True
    for path in root.glob("value_*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = tuple(node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module) + tuple(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        imports_clean &= not any(module.startswith(forbidden) for module in modules)
        pure = sum(1 for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#"))
        loc_clean &= pure <= 250
    return imports_clean, loc_clean


def verify_value_fixture(fixture: ValueFixture, trust: ValueTrustDocument) -> JsonValue:
    context = trust_value_fixture(fixture, trust)
    artifact = compile_value_artifact(fixture, context)
    value = JsonBoundary.model_validate(artifact.model_dump(mode="json")).root
    external = run_external_attacks(artifact, context)
    manifest = fixture.cohort_manifest
    rows = artifact.observations
    missing_adapter_fixture = fixture.model_copy(update={"outcome_registry": None})
    missing_adapter_trust = trust.model_copy(update={"expected_outcome_root": None})
    missing_adapter_context = trust_value_fixture(missing_adapter_fixture, missing_adapter_trust)
    missing_adapter = evaluate_value(missing_adapter_fixture.source_binding, missing_adapter_fixture.observations, missing_adapter_context)
    bad_manifest = trust.model_copy(update={"expected_cohort_root": "sha256:" + "f" * 64})
    bad_outcome = trust.model_copy(update={"expected_outcome_root": "sha256:" + "f" * 64})
    bad_quality = trust.model_copy(update={"quality": trust.quality.model_copy(update={"expected_registry_root": "sha256:" + "f" * 64})})
    substituted_manifest = manifest.model_copy(update={"prompt_bundle": "attacker_prompt"})
    substituted_manifest = substituted_manifest.model_copy(update={"manifest_root": cohort_manifest_root(substituted_manifest)})
    substituted_outcome = fixture.outcome_registry.outcomes[0].model_copy(update={"instrument_return_5": Decimal("999")}) if fixture.outcome_registry is not None else None
    if fixture.outcome_registry is None or substituted_outcome is None:
        raise ValueContractError("OUTCOME_ADAPTER_INVALID", "canonical outcome registry is required")
    substituted_outcome = substituted_outcome.model_copy(update={"outcome_hash": outcome_hash(substituted_outcome)})
    substituted_registry = fixture.outcome_registry.model_copy(update={"outcomes": (substituted_outcome, *fixture.outcome_registry.outcomes[1:])})
    substituted_registry = substituted_registry.model_copy(update={"registry_root": outcome_registry_root(substituted_registry)})
    imports_clean, loc_clean = _static_checks()
    checks: dict[str, bool] = {
        "canonical_pass": artifact.terminal_code == "PASS_INCREMENTAL_VALUE_EVALUATION" and artifact.promotion_eligible,
        "exact_360_inventory": len(rows) == len(manifest.samples) == 360 and tuple(item.sample_id for item in rows) == tuple(item.sample_id for item in manifest.samples),
        "exact_market_classes": {market: sum(item.market == market for item in rows) for market in ("KR", "US")} == {"KR": 180, "US": 180},
        "exact_action_classes": {action: sum(item.action == action for item in rows) for action in ("BUY", "SELL", "HOLD")} == {"BUY": 120, "SELL": 120, "HOLD": 120},
        "target_error_inventory": sum(item.target_error for item in rows) == 130,
        "factual_error_inventory": sum(item.fact_audit.known_baseline_error for item in rows) == 96,
        "full_prd01_bundle": bool(artifact.source_binding.provenance_bundle.trusted_payload_manifest.provenance_body.root),
        "full_prd02_artifact": bool(artifact.source_binding.quality_artifact.build_input.sources),
        "cohort_root_recomputed": cohort_manifest_root(manifest) == manifest.manifest_root,
        "arm_hashes_recomputed": all(output_hash(arm) == arm.output_hash for item in rows for arm in (item.off, item.on, item.masked)),
        "outcome_hashes_recomputed": all(outcome_hash(item.outcome) == item.outcome.outcome_hash for item in rows),
        "fact_hashes_recomputed": all(fact_audit_hash(item.fact_audit) == item.fact_audit.fact_audit_hash for item in rows),
        "pair_hashes_transitive": all(observation_hash(item) == item.content_hash for item in rows),
        "actual_outcomes_materialized": all(item.outcome.instrument_return_5 and item.outcome.adapter_body_hash for item in rows),
        "canonical_policy_only": artifact.thresholds == canonical_thresholds(),
        "current_repeat_hashes": len(set(artifact.repeat_run_hashes)) == 1 and len(artifact.repeat_run_hashes) == 3,
        "expected_roots_absent_from_evaluated_fixture": not any(_contains_key(JsonBoundary.model_validate(fixture.model_dump(mode="json")).root, key) for key in ("expected_cohort_root", "expected_outcome_root", "expected_registry_root", "expected_bundle_roots")),
        "artifact_roundtrip": verify_value_artifact(value, context) == artifact,
        "deterministic_rebuild": compile_value_artifact(fixture, context) == artifact,
        "trusted_context_required_compile": _reject(lambda: compile_value_artifact(fixture).model_dump(mode="json"), "TRUSTED_VALUE_CONTEXT_REQUIRED"),
        "trusted_context_required_verify": _reject(lambda: verify_value_artifact(value).model_dump(mode="json"), "TRUSTED_VALUE_CONTEXT_REQUIRED"),
        "manifest_root_tamper": _reject(lambda: trust_value_fixture(fixture, bad_manifest).cohort_manifest.model_dump(mode="json"), "COHORT_MANIFEST_INVALID"),
        "outcome_root_tamper": _reject(lambda: trust_value_fixture(fixture, bad_outcome).cohort_manifest.model_dump(mode="json"), "OUTCOME_ADAPTER_INVALID"),
        "quality_root_tamper": _reject(lambda: trust_value_fixture(fixture, bad_quality).cohort_manifest.model_dump(mode="json"), "PRD02_LINEAGE_INVALID"),
        "cohort_joint_substitution_rejected": _reject(lambda: trust_value_fixture(fixture.model_copy(update={"cohort_manifest": substituted_manifest}), trust).cohort_manifest.model_dump(mode="json"), "COHORT_MANIFEST_INVALID"),
        "outcome_joint_substitution_rejected": _reject(lambda: trust_value_fixture(fixture.model_copy(update={"outcome_registry": substituted_registry}), trust).cohort_manifest.model_dump(mode="json"), "OUTCOME_ADAPTER_INVALID"),
        "missing_outcome_no_promotion": missing_adapter.code == "INCONCLUSIVE_MISSING_OUTCOME_ADAPTER" and missing_adapter.policy_no_op and not missing_adapter.promotion_eligible,
        "required_field_removal": all(_reject(lambda field=field: verify_value_attack(remove_value(value, (field,)), context), "REQUIRED_FIELD_MISSING") for field in ("source_binding", "cohort_manifest", "observations", "metrics", "artifact_hash")),
        "artifact_hash_tamper": _reject(lambda: verify_value_attack(replace_value(value, ("artifact_hash",), "sha256:" + "f" * 64), context), "ARTIFACT_HASH_MISMATCH"),
        "persisted_secret_rejected": _reject(lambda: verify_value_attack(replace_value(value, ("report_id",), "Bearer benign-review-token"), context), "SECRET_LEAKAGE_DETECTED"),
        "input_output_path_safety": _path_safety(),
        "production_isolation": artifact.production_isolation == "offline_read_only_no_production_mutation" and imports_clean,
        "modules_within_250_loc": loc_clean,
        **external,
    }
    return JsonBoundary.model_validate({
        "state": "pass" if all(checks.values()) else "fail", "schema_version": fixture.schema_version,
        "pass_count": sum(checks.values()), "total": len(checks), "external_corpus_count": len(external),
        "manifest_root": manifest.manifest_root, "outcome_root": artifact.outcome_adapter_root,
        "repeat_run_hash": artifact.repeat_run_hashes[0], "checks": checks,
    }).root
