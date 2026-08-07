from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Final, override

from pydantic import TypeAdapter, ValidationError

from src.v4.models import JsonValue, canonical_hash

from .prompt_injection_models import (
    PROMPT_PACKAGE_ADAPTER,
    VERIFICATION_ARTIFACT_ADAPTER,
    Eligibility,
    ExcludedPromptRecord,
    MutationName,
    PromptConfig,
    PromptMutation,
    VerifiedPromptRecord,
)
from .prompt_injection_records import (
    ExclusionSeed,
    MutationSeed,
    RecordContext,
    candidate_sort_key,
    excluded_record,
    prompt_mutation,
    rekey_record,
    verified_record,
)
from .statistical_output_models import PAIR_RESULT_ADAPTER, VerificationStatus


@dataclass(frozen=True, slots=True)
class PromptBuildResult:
    artifact: JsonValue


@dataclass(frozen=True, slots=True)
class PromptAssemblyError(ValueError):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


_RECORD = TypeAdapter(dict[str, JsonValue])
_STATUS_GATE: Final[
    dict[VerificationStatus, tuple[Eligibility | None, MutationName | None]]
] = {
    "verified_stable": (None, None),
    "inconclusive": ("excluded_inconclusive", "exclude_inconclusive"),
    "rejected_in_sample_only": ("excluded_rejected", "exclude_rejected"),
    "rejected_direction_mismatch": ("excluded_rejected", "exclude_rejected"),
    "rejected_multiple_testing": ("excluded_rejected", "exclude_rejected"),
    "rejected_structural_break": ("excluded_rejected", "exclude_rejected"),
    "rejected_leakage": ("excluded_rejected", "exclude_rejected"),
    "rejected_p_hacking": ("excluded_rejected", "exclude_rejected"),
    "rejected_flaky": ("excluded_rejected", "exclude_rejected"),
    "rejected_malformed": ("excluded_rejected", "exclude_rejected"),
}


def _malformed_identity(value: JsonValue, index: int) -> str:
    try:
        record = _RECORD.validate_python(value)
    except ValidationError:
        return f"malformed_pair_{index}"
    pair_id = record.get("pair_id")
    return pair_id if isinstance(pair_id, str) else f"malformed_pair_{index}"


def build_prompt_package(
    source_value: JsonValue,
    config: PromptConfig,
    rollback_to_package_hash: str | None = None,
) -> PromptBuildResult:
    source = VERIFICATION_ARTIFACT_ADAPTER.validate_python(source_value)
    source_hash = str(canonical_hash(source_value))
    freshness_floor = config.prompt_cutoff - timedelta(hours=config.freshness_window_hours)
    if (
        source.generated_at > config.prompt_cutoff
        or source.verification_cutoff > config.prompt_cutoff
    ):
        raise PromptAssemblyError("source_verification_artifact_after_prompt_cutoff")
    if source.generated_at < freshness_floor:
        raise PromptAssemblyError("source_verification_artifact_outside_freshness_window")

    excluded: list[ExcludedPromptRecord] = []
    mutations: list[PromptMutation] = []
    candidates: list[VerifiedPromptRecord] = []
    for index, raw_pair in enumerate(source.pair_results):
        try:
            pair = PAIR_RESULT_ADAPTER.validate_python(raw_pair)
        except ValidationError:
            pair_id = _malformed_identity(raw_pair, index)
            seed = ExclusionSeed(pair_id, "excluded_malformed", "strict_pair_result_validation_failed")
            excluded.append(excluded_record(seed))
            mutations.append(prompt_mutation(MutationSeed("exclude_malformed", pair_id, None, seed.eligibility, seed.reason), config))
            continue
        provenance_matches = (
            pair.input_fingerprint == source.input_fingerprint
            and pair.run_config_hash == source.run_config_hash
            and pair.correction_scope_hash == source.correction_scope_hash
            and pair.split_policy_hash == source.split_policy_hash
            and pair.window_policy_hash == source.window_policy_hash
            and pair.verification_cutoff == source.verification_cutoff
        )
        if not provenance_matches:
            seed = ExclusionSeed(pair.pair_id, "excluded_malformed", "pair_root_provenance_mismatch")
            excluded.append(excluded_record(seed))
            mutations.append(prompt_mutation(MutationSeed("exclude_malformed", pair.pair_id, pair.verification_status, seed.eligibility, seed.reason), config))
            continue
        stale = (
            pair.verification_expires_at <= config.prompt_cutoff
            or pair.mapping_expires_at <= config.prompt_cutoff
        )
        if stale:
            seed = ExclusionSeed(pair.pair_id, "excluded_stale", "evidence_expired_before_prompt_cutoff")
            excluded.append(excluded_record(seed))
            mutations.append(prompt_mutation(MutationSeed("exclude_stale", pair.pair_id, pair.verification_status, seed.eligibility, seed.reason), config))
            continue
        eligibility, mutation_name = _STATUS_GATE[pair.verification_status]
        if eligibility is not None and mutation_name is not None:
            seed = ExclusionSeed(pair.pair_id, eligibility, pair.rejection_reason or "terminal_status")
            excluded.append(excluded_record(seed))
            mutations.append(prompt_mutation(MutationSeed(mutation_name, pair.pair_id, pair.verification_status, seed.eligibility, seed.reason), config))
            continue
        if Decimal(pair.confidence) < Decimal(config.minimum_confidence):
            seed = ExclusionSeed(pair.pair_id, "excluded_low_confidence", "confidence_below_minimum")
            excluded.append(excluded_record(seed))
            mutations.append(prompt_mutation(MutationSeed("exclude_low_confidence", pair.pair_id, pair.verification_status, seed.eligibility, seed.reason), config))
            continue
        candidates.append(
            verified_record(pair, RecordContext(source_hash, source.generated_at, config))
        )

    accepted: list[VerifiedPromptRecord] = []
    used_tokens = 0
    available_tokens = config.max_tokens - config.reserved_tokens
    for rank, record in enumerate(sorted(candidates, key=candidate_sort_key), start=1):
        if used_tokens + record.token_estimate <= available_tokens:
            accepted.append(record)
            used_tokens += record.token_estimate
            mutations.append(prompt_mutation(MutationSeed("inject_verified", record.pair_id, "verified_stable", "verified_prompt_eligible", "eligible_and_within_budget", rank, record.token_estimate), config))
        else:
            seed = ExclusionSeed(record.pair_id, "excluded_budget_overflow", "token_budget_exceeded", rank, record.token_estimate)
            excluded.append(excluded_record(seed))
            mutations.append(prompt_mutation(MutationSeed("exclude_budget_overflow", record.pair_id, "verified_stable", seed.eligibility, seed.reason, rank, record.token_estimate), config))

    configured_expiry = config.generated_at + timedelta(hours=config.package_ttl_hours)
    evidence_expiries = [
        min(record.freshness.verification_expires_at, record.freshness.mapping_expires_at)
        for record in accepted
    ]
    expires_at = min([configured_expiry, *evidence_expiries])
    body: dict[str, JsonValue] = {
        "schema_version": "causal-prompt-injection.1",
        "source_verification_schema_version": source.schema_version,
        "prompt_policy_version": "prompt-injection-gate.1",
        "generated_at": config.generated_at.isoformat(),
        "prompt_cutoff": config.prompt_cutoff.isoformat(),
        "expires_at": expires_at.isoformat(),
        "source_artifact_hash": source_hash,
        "rollback_to_package_hash": rollback_to_package_hash,
        "budget": {"max_tokens": config.max_tokens, "reserved_tokens": config.reserved_tokens, "used_tokens": used_tokens, "overflow_count": sum(item.eligibility == "excluded_budget_overflow" for item in excluded)},
        "verified_prompt_records": [item.model_dump(mode="json") for item in accepted],
        "excluded_prompt_records": [item.model_dump(mode="json") for item in sorted(excluded, key=lambda item: (item.pair_id, item.eligibility))],
        "prompt_mutations": [item.model_dump(mode="json") for item in mutations],
        "qa": {"read_checks": ["strict_prd03_schema", "pair_results_only", "freshness_before_budget"], "json_checks": ["strict_pair_types", "canonical_hashes"], "mutation_checks": ["inject", "exclude", "rollback"]},
    }
    artifact: JsonValue = {**body, "package_hash": canonical_hash(body)}
    package = PROMPT_PACKAGE_ADAPTER.validate_python(artifact)
    return PromptBuildResult(package.model_dump(mode="json"))


def rollback_prompt_package(prior_value: JsonValue, config: PromptConfig) -> PromptBuildResult:
    prior = PROMPT_PACKAGE_ADAPTER.validate_python(prior_value)
    freshness_floor = config.generated_at - timedelta(hours=config.freshness_window_hours)
    if (
        config.generated_at < prior.generated_at
        or config.prompt_cutoff < prior.prompt_cutoff
        or prior.expires_at <= config.generated_at
        or any(
            record.freshness.verification_generated_at < freshness_floor
            or record.freshness.verification_generated_at > config.prompt_cutoff
            or record.freshness.verification_expires_at <= config.generated_at
            or record.freshness.mapping_expires_at <= config.generated_at
            for record in prior.verified_prompt_records
        )
    ):
        raise PromptAssemblyError("rollback_package_or_evidence_expired")
    body = prior.model_dump(mode="json")
    del body["package_hash"]
    body["generated_at"] = config.generated_at.isoformat()
    body["prompt_cutoff"] = config.prompt_cutoff.isoformat()
    body["rollback_to_package_hash"] = prior.package_hash
    body["verified_prompt_records"] = [
        rekey_record(record, config).model_dump(mode="json")
        for record in prior.verified_prompt_records
    ]
    mutations = list(prior.prompt_mutations)
    mutations.append(prompt_mutation(MutationSeed("rollback_package", None, None, "rollback_retained", "new_package_rejected"), config))
    body["prompt_mutations"] = [item.model_dump(mode="json") for item in mutations]
    artifact: JsonValue = {**body, "package_hash": canonical_hash(body)}
    package = PROMPT_PACKAGE_ADAPTER.validate_python(artifact)
    return PromptBuildResult(package.model_dump(mode="json"))
