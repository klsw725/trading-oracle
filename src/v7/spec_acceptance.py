from pathlib import Path
from typing import Final

from src.v4.models import JsonValue

from .spec_models import PrdDocument, SpecBundle, SpecErrorCode, SpecVerificationError
from .spec_parser import SpecMutation, expected_mutation_code, mutate_bundle, read_spec_bundle, verify_spec_bundle


REQUIRED_MUTATIONS: Final[tuple[SpecMutation, ...]] = (
    "prd_row_missing",
    "prd_link_duplicate",
    "bidirectional_gap",
    "state_jump",
    "quality_count_misuse",
    "source_addition_success",
    "latency_only_success",
    "harmful_source_current",
    "stale_cache_current",
    "policy_hash_mismatch",
)


def verify_spec_fixture(spec_path: Path) -> JsonValue:
    bundle = read_spec_bundle(spec_path)
    report = verify_spec_bundle(bundle)
    mutation_results: dict[str, JsonValue] = {}
    passed = 1
    for mutation in REQUIRED_MUTATIONS:
        expected = expected_mutation_code(mutation)
        observed: str | None = None
        try:
            _ = verify_spec_bundle(mutate_bundle(bundle, mutation))
        except SpecVerificationError as error:
            observed = error.code
        accepted = observed == expected
        mutation_results[mutation] = {
            "state": "pass" if accepted else "fail",
            "expected_error_code": expected,
            "observed_error_code": observed,
        }
        passed += int(accepted)
    parser_results: dict[str, JsonValue] = {}
    first_prd = bundle.prds[0]
    parser_probes: dict[str, tuple[SpecBundle, SpecErrorCode]] = {
        "duplicate_json_key": (
            SpecBundle(bundle.spec_path, bundle.spec_text.replace(
                '  "contract_id": "information_source_expansion_spec_v7",',
                '  "contract_id": "information_source_expansion_spec_v7",\n  "contract_id": "duplicate",', 1,
            ), bundle.prds),
            "V7_SPEC_MALFORMED",
        ),
        "non_finite_json": (
            SpecBundle(bundle.spec_path, bundle.spec_text.replace(
                '"p95_added_wall_ms_max": 2500', '"p95_added_wall_ms_max": NaN', 1,
            ), bundle.prds),
            "V7_SPEC_MALFORMED",
        ),
        "missing_prd_link": (
            SpecBundle(bundle.spec_path, bundle.spec_text.replace(
                '    "prds/prd01-source-adapter-provenance.md",\n', "", 1,
            ), bundle.prds),
            "V7_PRD_LINK_MISSING",
        ),
        "broken_local_link": (
            SpecBundle(bundle.spec_path, bundle.spec_text, (
                PrdDocument(first_prd.prd_id, first_prd.path, first_prd.text.replace(
                    "prd02-quality-freshness-dedup.md#freshness-sla-and-ttl", "missing-prd.md", 1,
                )),
            ) + bundle.prds[1:]),
            "V7_PRD_LINK_BROKEN",
        ),
        "unsafe_local_link": (
            SpecBundle(bundle.spec_path, bundle.spec_text, (
                PrdDocument(first_prd.prd_id, first_prd.path, first_prd.text.replace(
                    "](../SPEC.md)", "](../../../../config.yaml)", 1,
                )),
            ) + bundle.prds[1:]),
            "V7_SPEC_PATH_UNSAFE",
        ),
    }
    for name, (probe_bundle, expected_code) in parser_probes.items():
        observed = None
        try:
            _ = verify_spec_bundle(probe_bundle)
        except SpecVerificationError as error:
            observed = error.code
        accepted = observed == expected_code
        parser_results[name] = {
            "state": "pass" if accepted else "fail",
            "expected_error_code": expected_code,
            "observed_error_code": observed,
        }
        passed += int(accepted)
    total = len(REQUIRED_MUTATIONS) + len(parser_probes) + 1
    return {
        "state": "pass" if passed == total else "fail",
        "schema_version": report.schema_version,
        "json_block_count": report.json_block_count,
        "linked_prd_count": report.linked_prd_count,
        "pass_count": passed,
        "total": total,
        "mutations": mutation_results,
        "parser_probes": parser_results,
    }
