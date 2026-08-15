from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

from src.v11.canonical import canonical_hash, model_json
from src.v4.models import JsonValue, canonical_json

from .failure import V14Failure
from .holdout import consume_lease, issue_lease
from .integrity import verify_bundle
from .manifest import verify_manifest_value
from .pipeline import build_prd01
from .prd04_bundle import ROOT, build_prd04_from_loaded
from .prd04_fixture import load_prd04_fixture, load_prd04_history
from .prd04_run_models import ValidationRunArtifact, ValidationRunBody
from .prd03_pipeline import SegmentPrd03Artifacts, SegmentPrd03ArtifactsBody
from .prd04_models import V14ResultBundle
from .prd04_runs import (
    build_holdout_run,
    verify_holdout_samples,
    verify_validation_run,
)
from .prd04_sources import load_sources
from .prd04_source_models import LoadedSources, Prd04Source
from .prd04_validation_probe import reject_validation_before_holdout
from .series_models import ResearchSegment
from .verdict_models import HoldoutVerdict


EXPECTED_FAILURES = {
    "validation_tune": "V14_VALIDATION_TUNE",
    "holdout_repeat": "V14_HOLDOUT_REUSE",
    "cost_change": "V14_MANIFEST_MISMATCH",
    "sample_or": "V14_SAMPLE_INSUFFICIENT",
    "validation_undefined": "V14_VALIDATION_GATE",
    "uncorrected_family": "V14_MULTIPLE_TESTING",
    "context_gap_fill": "V14_COHORT_CONTINUITY",
    "secondary_override": "V14_VERDICT",
    "future_revision": "V14_POINT_IN_TIME",
    "manifest_partial": "V14_MANIFEST_INCOMPLETE",
}


def _killed[T](code: str, operation: Callable[[], T]) -> bool:
    try:
        _ = operation()
    except V14Failure as error:
        return error.code.value == code
    return False


def _seal_validation(run: ValidationRunArtifact) -> ValidationRunArtifact:
    body = ValidationRunBody.model_validate(
        run.model_dump(exclude={"validation_run_hash"}))
    return run.model_copy(update={
        "validation_run_hash": canonical_hash(model_json(body))})


def _seal_prd03(run: SegmentPrd03Artifacts) -> SegmentPrd03Artifacts:
    body = SegmentPrd03ArtifactsBody.model_validate(
        run.model_dump(exclude={"artifact_hash"}))
    return run.model_copy(update={"artifact_hash": canonical_hash(model_json(body))})


def _partial(value: JsonValue) -> None:
    _ = verify_manifest_value(value)


def _insufficient_sample(value: V14ResultBundle, loaded: LoadedSources) -> None:
    descriptors = tuple(item.model_copy(update={"completed_trades_per_trade": 1})
        if item.segment is ResearchSegment.HOLDOUT else item
        for item in loaded.prd02.descriptors)
    insufficient_sources = loaded.model_copy(update={"prd02":
        loaded.prd02.model_copy(update={"descriptors": descriptors})})
    run = build_holdout_run(value.plan,
        build_prd01(insufficient_sources.prd01).selection,
        insufficient_sources, value.holdout_plan, value.approval,
        value.lease, value.validation_run)
    if not any(not item.sample.sufficient for item in run.prd02.metrics) \
            or not all(item.verdict is HoldoutVerdict.INSUFFICIENT_SAMPLE
                for item in run.prd03.observed_strategy_verdicts):
        raise AssertionError("insufficient holdout did not produce verdict")
    consumed = consume_lease(value.prior_history, value.lease, run.holdout_run_hash)
    if consumed.entries[-1].holdout_run_hash != run.holdout_run_hash:
        raise AssertionError("insufficient holdout lease was not consumed")
    first = run.prd03.observed_strategy_verdicts[0].model_copy(
        update={"verdict": HoldoutVerdict.PASS})
    forged_prd03 = run.prd03.model_copy(update={
        "observed_strategy_verdicts": (first,
            *run.prd03.observed_strategy_verdicts[1:]),
        "observed_verdicts": (first, *run.prd03.observed_verdicts[1:])})
    verify_holdout_samples(run.model_copy(update={"prd03": forged_prd03}))


def _source_path_rejected(source: Prd04Source) -> bool:
    changed = source.model_copy(update={"sources": source.sources.model_copy(
        update={"prd02_input": source.sources.prd03_input})})
    try:
        _ = load_sources(changed, ROOT)
    except V14Failure:
        return True
    return False


def _source_hash_rejected(bundle: V14ResultBundle, sources: LoadedSources) -> bool:
    first = sources.evidence.files[0].model_copy(update={"content_hash": "tampered"})
    changed = sources.model_copy(update={"evidence": sources.evidence.model_copy(
        update={"files": (first, *sources.evidence.files[1:])})})
    try:
        verify_validation_run(bundle.plan, changed, bundle.validation_run)
    except V14Failure:
        return True
    return False


def _invalid_lease_blocks_holdout(
    source: Prd04Source,
    bundle: V14ResultBundle,
    sources: LoadedSources,
) -> bool:
    with patch("src.v14.prd04_bundle.build_holdout_run") as holdout:
        try:
            _ = build_prd04_from_loaded(source, bundle.history, sources)
        except V14Failure as error:
            return error.code.value == "V14_HOLDOUT_REUSE" and not holdout.called
    return False


def run_probes() -> tuple[dict[str, bool], dict[str, str], dict[str, str]]:
    source = load_prd04_fixture()
    prior = load_prd04_history()
    sources = load_sources(source, ROOT)
    bundle = build_prd04_from_loaded(source, prior, sources)
    verified = verify_bundle(canonical_json(bundle.model_dump(mode="json")))
    validation = bundle.validation_run
    tuned = validation.model_copy(update={"source_evidence_hash": "tampered"})
    bad_correction = validation.prd03.holm_corrections[0].model_copy(
        update={"segment": ResearchSegment.HOLDOUT})
    uncorrected_prd03 = validation.prd03.model_copy(update={"holm_corrections":
        (bad_correction, *validation.prd03.holm_corrections[1:])})
    uncorrected = _seal_validation(validation.model_copy(
        update={"prd03": _seal_prd03(uncorrected_prd03)}))
    context = _seal_validation(validation.model_copy(
        update={"source_evidence_hash": "sha256:context-gap"}))
    first_scope = validation.market_scopes[0]
    overridden = _seal_validation(validation.model_copy(update={"market_scopes":
        (first_scope.model_copy(update={"eligible_strategy_ids":
            first_scope.eligible_strategy_ids[:-1]}), *validation.market_scopes[1:])}))
    future = _seal_validation(validation.model_copy(
        update={"plan_manifest_hash": "sha256:future-revision"}))
    partial: JsonValue = bundle.plan.model_dump(mode="json", exclude={"prompt"})
    mutations = {
        "validation_tune": _killed("V14_VALIDATION_TUNE", lambda:
            verify_validation_run(bundle.plan, sources, tuned)),
        "holdout_repeat": _killed("V14_HOLDOUT_REUSE", lambda:
            build_prd04_from_loaded(source, bundle.history, sources)),
        "cost_change": _killed("V14_MANIFEST_MISMATCH", lambda: issue_lease(
            bundle.holdout_plan, bundle.approval.model_copy(
                update={"approved_cost_model_id": "changed"}),
            source.lease, prior)),
        "sample_or": _killed("V14_SAMPLE_INSUFFICIENT", lambda:
            _insufficient_sample(bundle, sources)),
        "validation_undefined": _killed("V14_VALIDATION_GATE", lambda:
            reject_validation_before_holdout(source, prior, sources, bundle)),
        "uncorrected_family": _killed("V14_MULTIPLE_TESTING", lambda:
            verify_validation_run(bundle.plan, sources, uncorrected)),
        "context_gap_fill": _killed("V14_COHORT_CONTINUITY", lambda:
            verify_validation_run(bundle.plan, sources, context)),
        "secondary_override": _killed("V14_VERDICT", lambda:
            verify_validation_run(bundle.plan, sources, overridden)),
        "future_revision": _killed("V14_POINT_IN_TIME", lambda:
            verify_validation_run(bundle.plan, sources, future)),
        "manifest_partial": _killed("V14_MANIFEST_INCOMPLETE",
            lambda: _partial(partial)),
    }
    checks = {"bundle_rebuild_verified": verified.bundle_hash == bundle.bundle_hash,
        "validation_inventory": (len(bundle.validation_run.prd02.metrics),
            len(bundle.validation_run.prd02.router_comparisons),
            len(bundle.validation_run.prd03.holm_corrections),
            len(bundle.validation_run.prd03.bh_corrections),
            len(bundle.validation_run.prd03.observed_verdicts)) == (30, 2, 2, 2, 32),
        "holdout_inventory": (len(bundle.holdout_run.prd02.metrics),
            len(bundle.holdout_run.prd02.router_comparisons),
            len(bundle.holdout_run.prd03.holm_corrections),
            len(bundle.holdout_run.prd03.bh_corrections),
            len(bundle.holdout_run.prd03.observed_verdicts)) == (30, 2, 2, 2, 32),
        "history_binds_holdout": bundle.history.entries[-1].holdout_run_hash
            == bundle.holdout_run.holdout_run_hash,
        "result_binds_consumed_head": bundle.result_manifest.history_head_hash
            == bundle.history.head_hash,
        "source_path_mutation_rejected": _source_path_rejected(source),
        "source_hash_mutation_rejected": _source_hash_rejected(bundle, sources),
        "invalid_lease_blocks_holdout": _invalid_lease_blocks_holdout(
            source, bundle, sources),
        "validation_reject_blocks_holdout":
            mutations["validation_undefined"],
        "compatibility_counts": (bundle.compatibility.v10_prd_count,
            bundle.compatibility.v11_prd_count, bundle.compatibility.v12_strategy_count,
            bundle.compatibility.v13_probe_count) == (4, 4, 15, 13),
        "seven_verdict_inventory": len(bundle.verdict_inventory) == 7,
        "zero_side_effects": bundle.paper_side_effect_count == 0
            and bundle.live_side_effect_count == 0 and not bundle.promotion_eligible}
    states = {key: "killed" if value else "survived"
        for key, value in mutations.items()}
    hashes = {"fixture_hash": canonical_hash(model_json(source)),
        "source_evidence_hash": bundle.source_evidence.evidence_hash,
        "validation_run_hash": bundle.validation_run.validation_run_hash,
        "holdout_plan_hash": bundle.holdout_plan.plan_hash,
        "holdout_run_hash": bundle.holdout_run.holdout_run_hash,
        "bundle_hash": bundle.bundle_hash,
        "result_manifest_hash": bundle.result_manifest.result_manifest_hash,
        "history_head_hash": bundle.history.head_hash,
        "compatibility_hash": bundle.compatibility.compatibility_hash}
    return checks, states, hashes
