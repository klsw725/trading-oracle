from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from src.v4.models import JsonValue, canonical_hash

from .fixture import parse_json_bytes
from .models import ProvenanceContractError
from .quality_artifact import build_quality_artifacts
from .quality_models import QualityFixture
from .quality_registry_models import QualityTrustDocument as QualityTrustRoots
from .value_input import ValueFixture, ValueTrustDocument
from .value_models import Action, Arm, CohortManifest, CohortManifestBody, CohortSample, FactAuditClass, Market, SourceBinding, ValueContractError, canonical_thresholds
from .value_observations import FactAudit, OutcomeAdapterIdentity, OutcomeAdapterIdentityBody, OutcomeArtifact, OutcomeRegistry, OutcomeRegistryBody, OutputArtifact, PairedObservation, fact_audit_hash, observation_hash, outcome_adapter_hash, outcome_hash, outcome_registry_root, output_hash
from .value_trust import cohort_manifest_root


@dataclass(frozen=True, slots=True)
class SampleDraft:
    index: int
    sample_id: str
    market: Market
    ticker: str
    action: Action
    target_error: bool
    fact: FactAudit
    outcome: OutcomeArtifact


@dataclass(frozen=True, slots=True)
class FixtureSeed:
    generated_at: datetime
    decision_cutoff: datetime
    outcome_cutoff: datetime
    prompt_bundle: str
    scorer_version: str
    portfolio_hash: str
    binding: SourceBinding


def parse_value_json_bytes(payload: bytes) -> JsonValue:
    try:
        return parse_json_bytes(payload)
    except ProvenanceContractError as error:
        raise ValueContractError("MALFORMED_EVALUATION_INPUT", error.detail) from error


def parse_value_fixture_bytes(payload: bytes) -> ValueFixture:
    value = parse_value_json_bytes(payload)
    try:
        return ValueFixture.model_validate(value)
    except ValidationError as error:
        code = "REQUIRED_FIELD_MISSING" if any(item["type"] == "missing" for item in error.errors()) else "MALFORMED_EVALUATION_INPUT"
        raise ValueContractError(code, str(error)) from error


def load_value_fixture(path: Path) -> ValueFixture:
    return parse_value_fixture_bytes(path.read_bytes())


def parse_value_trust_bytes(payload: bytes) -> ValueTrustDocument:
    value = parse_value_json_bytes(payload)
    try:
        return ValueTrustDocument.model_validate(value)
    except ValidationError as error:
        code = "REQUIRED_FIELD_MISSING" if any(item["type"] == "missing" for item in error.errors()) else "MALFORMED_EVALUATION_INPUT"
        raise ValueContractError(code, str(error)) from error


def load_value_trust(path: Path) -> ValueTrustDocument:
    return parse_value_trust_bytes(path.read_bytes())


def _fact(index: int) -> FactAudit:
    audit_class: FactAuditClass = "clean"
    if index < 46 or 76 <= index < 81 or 82 <= index < 96:
        audit_class = "known_error_uncorrected"
    elif 46 <= index < 76:
        audit_class = "known_error_corrected"
    elif index == 81:
        audit_class = "unsupported_correction"
    elif index in (100, 101, 102):
        audit_class = "new_false_fact"
    value = FactAudit(
        audit_class=audit_class, known_baseline_error=index < 96,
        correction_claimed=46 <= index < 82, correction_true=46 <= index < 76,
        correction_supported=index != 81, new_false_fact=index in (100, 101, 102),
        fact_audit_hash="sha256:" + "0" * 64,
    )
    return value.model_copy(update={"fact_audit_hash": fact_audit_hash(value)})


def _outcome(index: int, seed: FixtureSeed, adapter: OutcomeAdapterIdentity) -> OutcomeArtifact:
    sample_id = f"ive_sample_{index + 1:04d}"
    severe = index < 6
    ordinary = 6 <= index < 46
    off_edge = Decimal("0.060") if severe else Decimal("0.030") if ordinary else Decimal("0.000")
    on_edge = Decimal("0.000") if index < 46 else Decimal("0.020")
    value = OutcomeArtifact(
        schema_version="v7.incremental_value_evaluation.outcome.1", sample_id=sample_id,
        adapter_id=adapter.adapter_id, adapter_body_hash=adapter.body_hash,
        decision_cutoff=seed.decision_cutoff, outcome_cutoff=seed.outcome_cutoff,
        observed_at=seed.generated_at, instrument_return_5=Decimal("0.08"),
        benchmark_return_5=Decimal("0.02"), execution_cost_return=Decimal("0.001"),
        off_correctness_edge_5=off_edge, on_correctness_edge_5=on_edge,
        masked_correctness_edge_5=off_edge + Decimal("0.001"), outcome_hash="sha256:" + "0" * 64,
    )
    return value.model_copy(update={"outcome_hash": outcome_hash(value)})


def _output(draft: SampleDraft, seed: FixtureSeed, arm: Arm) -> OutputArtifact:
    outcome = draft.outcome
    edge = {"off": outcome.off_correctness_edge_5, "on": outcome.on_correctness_edge_5, "masked": outcome.masked_correctness_edge_5}[arm]
    source_arm = arm != "off"
    covered = draft.index < 330
    bundle = seed.binding.provenance_bundle
    value = OutputArtifact(
        schema_version="v7.incremental_value_evaluation.output.1", sample_id=draft.sample_id,
        arm=arm, market=draft.market, ticker=draft.ticker, action=draft.action, horizon=5,
        prompt_bundle=seed.prompt_bundle, scorer_version=seed.scorer_version,
        portfolio_hash=seed.portfolio_hash, decision_cutoff=seed.decision_cutoff,
        outcome_cutoff=seed.outcome_cutoff, emitted_at=seed.generated_at,
        latest_feature_at=seed.decision_cutoff,
        confidence=Decimal("0.80") if edge >= canonical_thresholds().success_threshold_5 else Decimal("0.35"),
        edge_5=edge, wall_ms=1000 if arm == "off" else 1600 + (draft.index % 3) * 100,
        prompt_tokens=1000 if arm == "off" else 1780, fetches=1 if source_arm else 0,
        timeout=arm == "on" and draft.index == 0, source_count=1 if source_arm else 0,
        source_eligible=covered if source_arm else True, source_fact_visible=arm == "on" and covered,
        provenance_hash=bundle.artifact.provenance_hash if source_arm else None,
        provenance_manifest_root=bundle.trusted_payload_manifest.manifest_hash if source_arm else None,
        quality_hash=seed.binding.quality_artifact.artifact_hash if source_arm else None,
        quality_registry_root=seed.binding.quality_artifact.source_registry_root if source_arm else None,
        output_hash="sha256:" + "0" * 64,
    )
    return value.model_copy(update={"output_hash": output_hash(value)})


def _observation(draft: SampleDraft, seed: FixtureSeed) -> PairedObservation:
    off, on, masked = (_output(draft, seed, arm) for arm in ("off", "on", "masked"))
    bundle = seed.binding.provenance_bundle
    value = PairedObservation(
        sample_id=draft.sample_id, market=draft.market, ticker=draft.ticker, action=draft.action,
        horizon=5, prompt_bundle=seed.prompt_bundle, scorer_version=seed.scorer_version,
        portfolio_hash=seed.portfolio_hash, decision_cutoff=seed.decision_cutoff,
        outcome_cutoff=seed.outcome_cutoff, target_error=draft.target_error,
        source_provenance_hash=bundle.artifact.provenance_hash,
        source_manifest_root=bundle.trusted_payload_manifest.manifest_hash,
        source_quality_hash=seed.binding.quality_artifact.artifact_hash,
        quality_registry_root=seed.binding.quality_artifact.source_registry_root,
        off=off, on=on, masked=masked, fact_audit=draft.fact, outcome=draft.outcome,
        content_hash="sha256:" + "0" * 64,
    )
    return value.model_copy(update={"content_hash": observation_hash(value)})


def build_canonical_value_fixture(quality_fixture: QualityFixture, quality_trust: QualityTrustRoots) -> tuple[ValueFixture, ValueTrustDocument]:
    quality, _ = build_quality_artifacts(quality_fixture, quality_trust)
    bundle = quality.build_input.sources[0].bundle
    binding = SourceBinding(adapter_id=bundle.artifact.adapter_id, provenance_bundle=bundle, quality_artifact=quality)
    generated = datetime.fromisoformat("2026-08-06T10:00:00+09:00")
    adapter_body = OutcomeAdapterIdentityBody(schema_version="v7.incremental_value_evaluation.outcome-adapter.1", adapter_id="deterministic_matured_edge_5.v1", adapter_version="1", generated_at=generated)
    adapter = OutcomeAdapterIdentity.model_validate({**adapter_body.model_dump(mode="json"), "body_hash": outcome_adapter_hash(adapter_body)})
    seed = FixtureSeed(generated, datetime.fromisoformat("2026-08-06T09:00:00+09:00"), datetime.fromisoformat("2026-09-01T00:00:00+09:00"), "mp_prompt_20260806", "consensus_scorer_v1", str(canonical_hash({"portfolio": "frozen-v7-001"})), binding)
    actions: tuple[Action, ...] = ("BUY", "SELL", "HOLD")
    drafts = tuple(SampleDraft(index, f"ive_sample_{index + 1:04d}", "KR" if index < 180 else "US", f"{index + 1:06d}" if index < 180 else f"US{index - 179:04d}", actions[index % 3], index < 130, _fact(index), _outcome(index, seed, adapter)) for index in range(360))
    observations = tuple(_observation(draft, seed) for draft in drafts)
    registry_body = OutcomeRegistryBody(schema_version="v7.incremental_value_evaluation.outcome-registry.1", adapter=adapter, outcomes=tuple(item.outcome for item in observations))
    registry = OutcomeRegistry.model_validate({**registry_body.model_dump(mode="json"), "registry_root": "sha256:" + "0" * 64})
    registry = registry.model_copy(update={"registry_root": outcome_registry_root(registry)})
    samples = tuple(CohortSample(sample_id=item.sample_id, market=item.market, ticker=item.ticker, action=item.action, target_error=item.target_error, fact_audit_class=item.fact_audit.audit_class, fact_audit_hash=item.fact_audit.fact_audit_hash, off_output_hash=item.off.output_hash, on_output_hash=item.on.output_hash, masked_output_hash=item.masked.output_hash, outcome_hash=item.outcome.outcome_hash) for item in observations)
    manifest_body = CohortManifestBody(schema_version="v7.incremental_value_evaluation.cohort-manifest.1", prompt_bundle=seed.prompt_bundle, scorer_version=seed.scorer_version, portfolio_hash=seed.portfolio_hash, horizon=5, quality_contract="v7.quality_freshness_dedup.prd02.2", decision_cutoff=seed.decision_cutoff, outcome_cutoff=seed.outcome_cutoff, samples=samples)
    manifest = CohortManifest.model_validate({**manifest_body.model_dump(mode="json"), "manifest_root": "sha256:" + "0" * 64})
    manifest = manifest.model_copy(update={"manifest_root": cohort_manifest_root(manifest)})
    fixture = ValueFixture(schema_version="v7.incremental_value_evaluation.prd03.2", contract_id="incremental_value_evaluation_prd03", report_id="ive_v7_source_001", source_bundle_id="news_source_bundle_v1", generated_at=generated, source_binding=binding, cohort_manifest=manifest, outcome_registry=registry, observations=observations, quality_evidence=quality_fixture.primary_evidence)
    trust = ValueTrustDocument(
        schema_version="v7.incremental_value_evaluation.trust.1",
        contract_id="incremental_value_evaluation_prd03",
        expected_cohort_root=manifest.manifest_root,
        expected_outcome_root=registry.registry_root,
        expected_provenance_manifest_root=bundle.trusted_payload_manifest.manifest_hash,
        expected_quality_artifact_hash=quality.artifact_hash,
        quality=quality_trust.primary,
    )
    return fixture, trust
