from __future__ import annotations

from typing import Final

from src.v11.canonical import canonical_hash, model_json
from src.v4.models import JsonValue
from src.v13.prd01_probes import run_probes as run_prd01
from src.v13.prd02_probes import run_probes as run_prd02
from src.v13.prd03_reliability_probes import run_reliability_probes
from src.v13.prd03_switch_probes import run_switch_probes
from src.v13.models import V13ContractError
from src.v13.prd04_models import CoverageArtifact, CoverageEntry, NormativeProbe


NORMATIVE_IDS: Final[tuple[str, ...]] = (
    "invented_candidate", "order_instruction", "future_news", "partial_item_bad",
    "duplicate_id", "unbounded_batch", "confidence_weight", "unproven_veto",
    "replay_recall", "rank_tie_drift", "single_candidate_gap",
    "slot_tie_nondeterministic", "switch_same_boundary",
)


def normative_probes() -> tuple[NormativeProbe, ...]:
    _, prd01, _ = run_prd01()
    _, prd02, _ = run_prd02()
    _, replay, _ = run_reliability_probes()
    _, switch, _ = run_switch_probes()
    results = {**prd01, **prd02, **replay, **switch}
    verify_inventory(tuple(results))
    if any(results[probe_id] != "killed" for probe_id in NORMATIVE_IDS):
        raise V13ContractError("V13_PROBE_SURVIVED", "normative")
    return tuple(NormativeProbe(probe_id=probe_id, state="killed")
        for probe_id in NORMATIVE_IDS)


def coverage_artifact(probes: tuple[NormativeProbe, ...]) -> CoverageArtifact:
    entries = (
        CoverageEntry(requirement_id="SPEC_SCORING_POLICY", prd=1,
            fixture="prd01-candidates.json", probes=("confidence_weight",
                "rank_tie_drift", "single_candidate_gap", "slot_tie_nondeterministic")),
        CoverageEntry(requirement_id="SPEC_STRUCTURED_OUTPUT", prd=2,
            fixture="prd02-recorded-normal.json", probes=("invented_candidate",
                "order_instruction", "partial_item_bad", "duplicate_id")),
        CoverageEntry(requirement_id="SPEC_CONTEXT_SAFETY", prd=2,
            fixture="v10/prd04-context.json", probes=("future_news", "unproven_veto")),
        CoverageEntry(requirement_id="SPEC_BOUNDED_BATCH", prd=2,
            fixture="prd02-recorded-normal.json", probes=("unbounded_batch",)),
        CoverageEntry(requirement_id="SPEC_SWITCH_SEQUENCE", prd=3,
            fixture="prd03-switch-recorded.json", probes=("switch_same_boundary",)),
        CoverageEntry(requirement_id="SPEC_IMMUTABLE_REPLAY", prd=3,
            fixture="prd02-recorded-normal.json", probes=("replay_recall",)),
        CoverageEntry(requirement_id="SPEC_UPSTREAM_ADAPTER", prd=4,
            fixture="prd04-source.json", probes=()),
        CoverageEntry(requirement_id="SPEC_CANONICAL_BUNDLE", prd=4,
            fixture="prd04-source.json", probes=()),
    )
    covered = tuple(probe for entry in entries for probe in entry.probes)
    verify_inventory(covered)
    body: JsonValue = {"entries": [model_json(item) for item in entries],
        "requirement_count": len(entries), "prd_count": 4,
        "fixture_count": len({item.fixture for item in entries}),
        "probe_count": len(probes)}
    return CoverageArtifact(entries=entries, requirement_count=len(entries),
        prd_count=4, fixture_count=len({item.fixture for item in entries}),
        probe_count=13, coverage_hash=canonical_hash(body))


def verify_inventory(probe_ids: tuple[str, ...]) -> None:
    expected: set[str] = set(NORMATIVE_IDS)
    duplicates = tuple(sorted(item for item in set(probe_ids)
        if probe_ids.count(item) > 1))
    missing = tuple(sorted(expected.difference(probe_ids)))
    unexpected = tuple(sorted(set(probe_ids).difference(expected)))
    if duplicates or missing or unexpected:
        raise V13ContractError("V13_PROBE_INVENTORY",
            f"missing={missing};duplicate={duplicates};unexpected={unexpected}")
