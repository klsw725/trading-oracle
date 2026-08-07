from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from src.v4.models import JsonValue, canonical_json

from .prompt_injection_models import (
    Eligibility,
    ExcludedPromptRecord,
    MutationName,
    PromptConfig,
    PromptEvidence,
    PromptFreshness,
    PromptMutation,
    PromptProvenance,
    VerifiedPromptRecord,
)
from .statistical_output_models import PairResultRead


@dataclass(frozen=True, slots=True)
class ExclusionSeed:
    pair_id: str
    eligibility: Eligibility
    reason: str
    rank: int | None = None
    token_estimate: int | None = None


@dataclass(frozen=True, slots=True)
class MutationSeed:
    name: MutationName
    pair_id: str | None
    from_status: str | None
    eligibility: str
    reason: str
    rank: int | None = None
    token_estimate: int | None = None


@dataclass(frozen=True, slots=True)
class RecordContext:
    source_hash: str
    verification_generated_at: datetime
    config: PromptConfig


def excluded_record(seed: ExclusionSeed) -> ExcludedPromptRecord:
    return ExcludedPromptRecord(
        pair_id=seed.pair_id,
        eligibility=seed.eligibility,
        reason=seed.reason,
        rank=seed.rank,
        token_estimate=seed.token_estimate,
    )


def prompt_mutation(seed: MutationSeed, config: PromptConfig) -> PromptMutation:
    return PromptMutation(
        mutation=seed.name,
        pair_id=seed.pair_id,
        from_status=seed.from_status,
        to_eligibility=seed.eligibility,
        reason=seed.reason,
        rank=seed.rank,
        token_estimate=seed.token_estimate,
        mutated_at=config.generated_at,
        mutated_by="prompt-injection-gate.1",
    )


def verified_record(
    pair: PairResultRead,
    context: RecordContext,
) -> VerifiedPromptRecord:
    if (
        pair.selected_lag is None
        or pair.train is None
        or pair.holdout is None
        or pair.multiple_testing is None
        or pair.stability is None
    ):
        raise AssertionError("strict verified pair evidence")
    render_text = (
        f"{pair.subject_label} {pair.relation} {pair.object_label}; "
        f"pair={pair.pair_id}; lag={pair.selected_lag}; train_p={pair.train.p_value}; "
        f"holdout_p={pair.holdout.p_value}; confidence={pair.confidence}; "
        f"source={context.source_hash}"
    )
    record_seed: JsonValue = {
        "schema_version": "causal-prompt-injection.1",
        "pair_id": pair.pair_id,
        "prompt_cutoff": context.config.prompt_cutoff.isoformat(),
        "source_artifact_hash": context.source_hash,
        "render_text": render_text,
    }
    record_id = f"promptrec_{sha256(canonical_json(record_seed)).hexdigest()[:20]}"
    return VerifiedPromptRecord(
        pair_id=pair.pair_id,
        prompt_record_id=record_id,
        eligibility="verified_prompt_eligible",
        claim_label="statistical_lead_evidence",
        render_label=context.config.verified_section_label,
        subject_node_id=pair.subject_node_id,
        object_node_id=pair.object_node_id,
        subject_label=pair.subject_label,
        object_label=pair.object_label,
        relation=pair.relation,
        selected_lag=pair.selected_lag,
        confidence=pair.confidence,
        freshness=PromptFreshness(
            verification_generated_at=context.verification_generated_at,
            verification_expires_at=pair.verification_expires_at,
            mapping_expires_at=pair.mapping_expires_at,
            is_fresh=True,
        ),
        provenance=PromptProvenance(
            source_artifact_hash=context.source_hash,
            run_config_hash=pair.run_config_hash,
            correction_scope_hash=pair.correction_scope_hash,
            subject_mapping_hash=pair.subject_mapping_hash,
            object_mapping_hash=pair.object_mapping_hash,
        ),
        evidence=PromptEvidence(
            train_p_value=pair.train.p_value,
            holdout_p_value=pair.holdout.p_value,
            corrected_alpha=pair.multiple_testing.corrected_alpha,
            direction_match_train=True,
            direction_match_holdout=True,
            stability="pass",
        ),
        token_estimate=max(1, (len(render_text.encode("utf-8")) + 3) // 4),
        render_text=render_text,
    )


def candidate_sort_key(
    record: VerifiedPromptRecord,
) -> tuple[float, Decimal, Decimal, int, str]:
    return (
        -record.freshness.verification_generated_at.timestamp(),
        -Decimal(record.confidence),
        Decimal(record.evidence.holdout_p_value),
        record.selected_lag,
        record.pair_id,
    )


def rekey_record(
    record: VerifiedPromptRecord, config: PromptConfig
) -> VerifiedPromptRecord:
    seed: JsonValue = {
        "schema_version": "causal-prompt-injection.1",
        "pair_id": record.pair_id,
        "prompt_cutoff": config.prompt_cutoff.isoformat(),
        "source_artifact_hash": record.provenance.source_artifact_hash,
        "render_text": record.render_text,
    }
    record_id = f"promptrec_{sha256(canonical_json(seed)).hexdigest()[:20]}"
    return record.model_copy(update={"prompt_record_id": record_id})
