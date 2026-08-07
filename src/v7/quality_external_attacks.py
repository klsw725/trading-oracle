from datetime import datetime
from collections.abc import Callable

from src.v4.models import JsonValue
from src.v6.models import JsonBoundary

from .freshness import assess_freshness
from .models import AsOf
from .quality_artifact import compile_quality
from .quality_derivation import derive_quality_sources
from .quality_fixture_factory import SourceSeed, build_source, claim_record, trust_fixture_for_sources
from .quality_models import QualityBuildInput, QualityContractError, QualityErrorCode, QualityFixture, SourceBundleEvidence
from .quality_registry import registry_root, trust_quality_fixture
from .quality_registry_models import QualityTrustDocument, QualityTrustExpectation, QualityTrustFixture, SourceMetadataRegistry


def _rejected[T](action: Callable[[], T], expected: QualityErrorCode) -> bool:
    try:
        _ = action()
    except QualityContractError as error:
        return error.code == expected
    return False


def _with_registry_root(trust: QualityTrustFixture, registry: SourceMetadataRegistry) -> QualityTrustFixture:
    root = registry_root(registry)
    return trust.model_copy(update={"registry": registry.model_copy(update={"registry_root": root})})


def _cache_attack(fixture: QualityFixture) -> tuple[bool, bool]:
    generated_at = fixture.primary_input.generated_at
    upstream = fixture.primary_input.sources[0].bundle
    upstream_hash = upstream.artifact.provenance_hash
    cache = build_source(
        SourceSeed(
            "cache_fixture",
            "local_cache",
            "local_cache",
            "unknown",
            "cache_family",
            "cache.local",
            claim_record("cache.local", "Cached HBM outlook", "Cached HBM claim", upstream_hash),
            AsOf(kind="published_at", value="2026-08-04T08:27:34+00:00", timezone=None),
            "news_fixture_a",
        ),
        generated_at,
    )
    wrong_upstream = fixture.primary_input.sources[1].bundle
    first_raw = fixture.primary_evidence.bundle_contexts[0].trusted_raw_payload.root
    second_raw = fixture.primary_evidence.bundle_contexts[1].trusted_raw_payload.root
    from .quality_fixture_factory import BuiltSource
    first = BuiltSource(fixture.primary_evidence.registry.entries[0], upstream, first_raw)
    second = BuiltSource(fixture.primary_evidence.registry.entries[1], wrong_upstream, second_raw)
    trust_fixture = trust_fixture_for_sources((cache, first, second), generated_at)
    expectation = QualityTrustExpectation(
        expected_registry_root=trust_fixture.registry.registry_root,
        expected_bundle_roots=tuple(source.bundle.trusted_payload_manifest.manifest_hash for source in (cache, first, second)),
    )
    context = trust_quality_fixture(trust_fixture, expectation, generated_at)
    valid_value = QualityBuildInput(
        schema_version="v7.quality_freshness_dedup.build.2",
        generated_at=generated_at,
        subject=fixture.primary_input.subject,
        sources=(SourceBundleEvidence(record_id="cache", bundle=cache.bundle, upstream_bundle=upstream),),
    )
    valid = compile_quality(valid_value, context)
    fake_value = valid_value.model_copy(update={"sources": (SourceBundleEvidence(record_id="cache", bundle=cache.bundle, upstream_bundle=wrong_upstream),)})
    lineage = valid.source_results[0].upstream_provenance_hash == upstream_hash
    return lineage, _rejected(lambda: compile_quality(fake_value, context), "CACHE_LINEAGE_INVALID")


def _session_boundary(fixture: QualityFixture) -> bool:
    generated_at = fixture.primary_input.generated_at
    record = claim_record("session.example", "Session HBM outlook", "Session claim")
    session = build_source(
        SourceSeed(
            "session_fixture",
            "search_result",
            "news_search",
            "wire_or_major_media",
            "session_family",
            "session.example",
            record,
            AsOf(kind="session", value="2026-08-06", timezone="Asia/Seoul"),
        ),
        generated_at,
    )
    trust_fixture = trust_fixture_for_sources((session,), generated_at)
    expectation = QualityTrustExpectation(
        expected_registry_root=trust_fixture.registry.registry_root,
        expected_bundle_roots=(session.bundle.trusted_payload_manifest.manifest_hash,),
    )
    context = trust_quality_fixture(trust_fixture, expectation, generated_at)
    value = QualityBuildInput(
        schema_version="v7.quality_freshness_dedup.build.2",
        generated_at=generated_at,
        subject=fixture.primary_input.subject,
        sources=(SourceBundleEvidence(record_id="session", bundle=session.bundle),),
    )
    derived = derive_quality_sources(value, context)[0]
    assessment = assess_freshness(derived, generated_at)
    return assessment.label == "fresh" and assessment.age_hours == 9.5


def external_attack_report(fixture: QualityFixture, trust: QualityTrustDocument) -> JsonValue:
    context = trust_quality_fixture(fixture.primary_evidence, trust.primary, fixture.primary_input.generated_at)
    first = fixture.primary_input.sources[0]
    reused = fixture.primary_input.model_copy(update={"sources": (first, first.model_copy(update={"record_id": "alias"}))})
    entry = fixture.primary_evidence.registry.entries[0]
    alias_registry = fixture.primary_evidence.registry.model_copy(update={"entries": (entry.model_copy(update={"source_family": "attacker_family"}), *fixture.primary_evidence.registry.entries[1:])})
    omitted_registry = fixture.primary_evidence.registry.model_copy(update={"entries": fixture.primary_evidence.registry.entries[1:]})
    stale_registry = fixture.primary_evidence.registry.model_copy(update={"expires_at": datetime.fromisoformat("2026-08-06T09:00:00+09:00")})
    primary_registry = fixture.primary_evidence.registry.model_copy(update={"entries": (entry.model_copy(update={"reliability_class": "primary_disclosure"}), *fixture.primary_evidence.registry.entries[1:])})
    omitted_evidence = _with_registry_root(fixture.primary_evidence, omitted_registry)
    stale_evidence = _with_registry_root(fixture.primary_evidence, stale_registry)
    substituted_evidence = _with_registry_root(fixture.primary_evidence, alias_registry)
    omitted_expectation = trust.primary.model_copy(update={"expected_registry_root": omitted_evidence.registry.registry_root})
    stale_expectation = trust.primary.model_copy(update={"expected_registry_root": stale_evidence.registry.registry_root})
    normalized_tamper = JsonBoundary.model_validate({"record_type": "quality_claim"})
    tampered_bundle = first.bundle.model_copy(update={"artifact": first.bundle.artifact.model_copy(update={"normalized_record": normalized_tamper})})
    tampered_input = fixture.primary_input.model_copy(update={"sources": (first.model_copy(update={"bundle": tampered_bundle}),)})
    valid_cache, fake_cache = _cache_attack(fixture)
    checks = {
        "same_provenance_alias_rejected": _rejected(lambda: compile_quality(reused, context), "PROVENANCE_REUSED"),
        "metadata_alias_root_rejected": _rejected(lambda: trust_quality_fixture(fixture.primary_evidence.model_copy(update={"registry": alias_registry}), trust.primary, fixture.primary_input.generated_at), "SOURCE_REGISTRY_INVALID"),
        "registry_joint_substitution_rejected": _rejected(lambda: trust_quality_fixture(substituted_evidence, trust.primary, fixture.primary_input.generated_at), "SOURCE_REGISTRY_INVALID"),
        "registry_omission_rejected": _rejected(lambda: compile_quality(fixture.primary_input, trust_quality_fixture(omitted_evidence, omitted_expectation, fixture.primary_input.generated_at)), "SOURCE_METADATA_MISSING"),
        "registry_staleness_rejected": _rejected(lambda: trust_quality_fixture(stale_evidence, stale_expectation, fixture.primary_input.generated_at), "SOURCE_REGISTRY_STALE"),
        "arbitrary_primary_disclosure_rejected": _rejected(lambda: trust_quality_fixture(fixture.primary_evidence.model_copy(update={"registry": primary_registry}), trust.primary, fixture.primary_input.generated_at), "SOURCE_REGISTRY_INVALID"),
        "normalized_claim_tamper_rejected": _rejected(lambda: compile_quality(tampered_input, context), "PRD01_LINEAGE_INVALID"),
        "cache_lineage_verified": valid_cache,
        "fake_cache_upstream_rejected": fake_cache,
        "session_timezone_boundary": _session_boundary(fixture),
    }
    return JsonBoundary.model_validate({"state": "pass" if all(checks.values()) else "fail", "checks": checks, "pass_count": sum(checks.values()), "total": len(checks)}).root
