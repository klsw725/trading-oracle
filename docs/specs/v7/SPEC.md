# v7 SPEC: Information Source Expansion
> **상태**: 📝 초안

## Scope

v7 defines how Trading Oracle accepts an information source, checks its quality, measures its decision value, and controls its operating lifecycle. It is independent from older SPEC lines. A source is not trusted because it exists, returns many rows, is cheap, or is already mentioned in README. It is trusted only when its source artifact, quality result, value report, and policy event all parse and link cleanly.

This SPEC does not choose a vendor, add a scraper, change source code, edit config, read credentials, rewrite cache files, or alter recommendation scoring. Current sources remain current sources until a later implementation changes them under this contract.

## Local PRD Map

| PRD | Local document | Contract focus | Reads from | Produces for |
| --- | --- | --- | --- | --- |
| PRD 01 | [Source Adapter Provenance](prds/prd01-source-adapter-provenance.md) | Adapter identity, auth boundary, market coverage, timestamps, as-of, license, retention, normalized record, raw hash, redaction, and error envelope. | Existing data source behavior and adapter output. | PRD 02 quality input and PRD 04 provenance gate. |
| PRD 02 | [Quality Freshness Dedup](prds/prd02-quality-freshness-dedup.md) | Freshness SLA, TTL, duplicate clustering, factuality, reliability, contradiction, degraded behavior, fallback, and count separate from quality. | PRD 01 provenance envelope. | PRD 03 prompt eligibility input and PRD 04 quality gate. |
| PRD 03 | [Incremental Value Evaluation](prds/prd03-incremental-value-evaluation.md) | Source ON/OFF cohorts, factual correction, verdict lift, calibration lift, latency, cost, coverage, harm, minimum sample, and no-op policy. | PRD 01 hashes and PRD 02 quality results. | PRD 04 value gate and source policy no-op reasons. |
| PRD 04 | [Promotion Retirement](prds/prd04-promotion-retirement.md) | Promotion, traffic share, fallback order, incident disable, contract expiry, retirement, cache invalidation, owner, and audit log. | PRD 01, PRD 02, PRD 03, current policy snapshot, incident report, and owner approval. | Operating source lifecycle, cache eligibility, fallback order, and audit events. |

The map is bidirectional by contract: every PRD row names what it consumes and what later contract consumes its output. A parser must fail if a row is missing, a local document link appears more than once, or a later contract claims an input that the prior contract does not produce.

## Current Source Baseline

The current product already has several source families:

| Source family | Current role | v7 treatment |
| --- | --- | --- |
| Toss Open API | Preferred read path for OHLCV, current price, index data, market cap inputs, candidate ranking, and USD/KRW where configured. | Treat as a source bundle that still needs PRD 01 envelope, PRD 02 quality result, PRD 03 value report, and PRD 04 policy before lifecycle claims. |
| pykrx, FinanceDataReader, yfinance | Existing fallback paths for market data, listings, market cap calculation inputs, indexes, macro series, and US data. | Preserve as current behavior, but never let fallback hide a failed primary source. |
| Naver Finance and yfinance fundamentals | PER, PBR, dividend, and fallback cache behavior. | Treat statement date, fetch time, license boundary, and cache TTL as separate facts. |
| DuckDuckGo web context | News and web context for prompt enrichment with local TTL cache. | Treat snippets and titles as untrusted text, not instruction text. Count is not quality. |
| Local caches | Performance and rate limit protection. | Require upstream provenance, freshness inheritance, cache generation, and policy hash before current use. |

v7 narrows the gap between the source list and an auditable source system. It records where a value came from, whether it is fresh and distinct, whether it improves decisions, and whether it is allowed to receive prompt traffic.

## End To End Flow

```text
onboarding -> quality -> evaluation -> lifecycle
```

1. Onboarding creates a PRD 01 source artifact. It must name source identity, auth boundary, as-of, license, retention, normalized record, redaction report, and hashes. Missing as-of, leaked secret material, bad timestamp order, unknown redistribution, or trusted external instructions block success.
2. Quality reads that artifact and creates a PRD 02 quality result. It calculates freshness, deduplicates repeated claims, separates independent evidence from raw count, flags contradictions, and keeps untrusted web text out of trusted prompt instructions.
3. Evaluation reads source OFF, source ON, and source masked cohorts under PRD 03. It accepts only frozen paired samples with the same cutoff, checks factual correction and verdict quality, and subtracts cost, latency, coverage gaps, and harm.
4. Lifecycle reads the source bundle, quality hashes, value report, current policy snapshot, incident reports, and owner approval under PRD 04. It opens traffic gradually, invalidates caches on policy change, disables harmful sources immediately, and retires sources without erasing audit history.

## Source State Diagram

```text
candidate -> shadow -> canary -> limited -> primary
candidate -> expired
shadow -> disabled
canary -> disabled
limited -> disabled
primary -> disabled
primary -> expired
primary -> retiring -> retired
disabled -> retiring -> retired
expired -> retired
```

`candidate` and `shadow` have no prompt traffic. `canary`, `limited`, and `primary` may enter prompt context only when provenance, quality, value, contract, owner, policy hash, and cache generation are valid. `disabled`, `retiring`, `retired`, and `expired` never appear in current fallback order. Reopening one of those closed statuses requires a new source bundle ID and fresh PRD 01 through PRD 04 evidence.

## Cost And Quality Success

Quality success means every prompt eligible source ref has PRD 01 provenance, PRD 02 `fresh` plus `usable` or `high`, no unresolved contradiction, no prompt injection treated as trusted text, no secret leakage, no missing as-of, and no duplicate counted as independent evidence.

Cost success means PRD 03 shows decision value after operating burden. The default bar is: eligible coverage at least `0.75`, target error cohort coverage at least `0.80`, p95 added wall time at most `2500` ms, mean added wall time at most `900` ms, added prompt tokens per ticker at most `1500`, timeout rate at most `0.02`, harm rate at most `0.20`, and severe harm rate at most `0.05`. A cheaper or faster source still fails when factual correction and verdict lift do not pass.

Promotion success requires both quality and cost success plus owner approval, matching policy hash, valid contract metadata, and gradual traffic movement. Source addition, high result count, low latency alone, or manual preference is not success.

## Happy Path: Promotion

1. A filing source bundle starts as `candidate` with PRD 01 provenance hashes and no prompt traffic.
2. PRD 02 marks the prompt eligible records `fresh` and `high` with independent evidence and no contradiction.
3. PRD 03 returns `PASS_INCREMENTAL_VALUE_EVALUATION` with source masked control near zero lift, factual correction above threshold, verdict lift above threshold, calibration improvement, coverage inside target, and harm inside limit.
4. PRD 04 receives owner approval, previous policy hash, source bundle hash, quality result hashes, provenance hashes, contract hash, and expiry review date.
5. Traffic opens in order: `shadow` at `0.00`, `canary` at `0.05`, `limited` at `0.25`, `limited` at `0.50`, then `primary` at `1.00`.
6. Each traffic movement creates a new cache generation and moves older prompt eligible cache entries to audit-only use.
7. Fallback order can put this bundle first only after state, capability, freshness, quality, value, cost, latency, policy hash, and cache generation all match.

## Failure Path: Harmful Retirement

1. A source with open traffic triggers severe harm, trusted prompt injection, secret leakage, auth boundary breach, contract expiry, stale cache served as fresh, or outage hidden as success.
2. The policy parser closes prompt traffic immediately. It sets traffic share to `0.00`, removes the bundle from fallback order, invalidates affected cache generation, and records an incident audit event without credential or raw user text.
3. Owner approval is not required before disable. Owner and reviewer sign the post audit record.
4. If the source is harmful rather than temporarily unavailable, the retirement reason is `harmful`. New decisions cannot use it. Audit TTL artifacts remain available only as hashes and redacted records under retention rules.
5. The source moves from `disabled` to `retiring` to `retired` only after current eligibility is closed, cache index is invalidated, and retention rules are satisfied.
6. Any report that leaves traffic above `0.00`, keeps disabled fallback, counts stale cache as fresh, or claims success after harm fails parsing.

## Parser And Mutation Requirements

A SPEC parser must read this Markdown, parse every fenced JSON block, and validate the PRD map, state diagram, success thresholds, happy promotion path, harmful retirement path, and local links. It must not read config, auth stores, account files, credential files, or raw cache bodies.

Required parser checks:

| Probe | Mutation | Expected result |
| --- | --- | --- |
| `prd_row_missing` | Remove one PRD row from the local map. | fail with `V7_PRD_ROW_MISSING`. |
| `prd_link_duplicate` | Add a second local link to one PRD file. | fail with `V7_PRD_LINK_DUPLICATE`. |
| `bidirectional_gap` | Remove a produced output or consuming input from a PRD row. | fail with `V7_PRD_BIDIRECTIONAL_GAP`. |
| `state_jump` | Move `candidate` directly to `primary`. | fail with `ILLEGAL_PROMOTION_JUMP`. |
| `quality_count_misuse` | Treat raw result count as quality. | fail with `COUNT_USED_AS_QUALITY`. |
| `source_addition_success` | Mark source addition successful without factual correction or verdict lift. | fail with `REJECT_NO_INCREMENTAL_VALUE`. |
| `latency_only_success` | Mark lower latency successful with zero source value. | fail with `REJECT_LATENCY_ONLY`. |
| `harmful_source_current` | Keep a harmful or disabled source in current fallback. | fail with `FALLBACK_USES_INELIGIBLE_SOURCE`. |
| `stale_cache_current` | Count stale cache as fresh current input. | fail with `STALE_CACHE_POLICY_MISMATCH`. |
| `policy_hash_mismatch` | Change source bundle or policy hash after approval. | fail with `POLICY_HASH_MISMATCH`. |

```json
{
  "schema_version": "v7.information_source_expansion.spec.1",
  "contract_id": "information_source_expansion_spec_v7",
  "flow": ["onboarding", "quality", "evaluation", "lifecycle"],
  "required_prds": [
    "PRD 01",
    "PRD 02",
    "PRD 03",
    "PRD 04"
  ],
  "local_prd_links": [
    "prds/prd01-source-adapter-provenance.md",
    "prds/prd02-quality-freshness-dedup.md",
    "prds/prd03-incremental-value-evaluation.md",
    "prds/prd04-promotion-retirement.md"
  ],
  "states": [
    "candidate",
    "shadow",
    "canary",
    "limited",
    "primary",
    "disabled",
    "retiring",
    "retired",
    "expired"
  ],
  "happy_promotion_fixture": {
    "source_bundle_id": "filing_source_bundle_v1",
    "provenance_gate": "pass",
    "quality_gate": "fresh_high",
    "value_gate": "PASS_INCREMENTAL_VALUE_EVALUATION",
    "traffic_path": ["0.00", "0.05", "0.25", "0.50", "1.00"],
    "final_state": "primary",
    "expected_code": "PROMOTION_ACCEPTED_GRADUAL"
  },
  "harmful_retirement_fixture": {
    "source_bundle_id": "web_context_bundle_v1",
    "incident_code": "severe_harm_breach",
    "previous_state": "limited",
    "previous_traffic_share": "0.25",
    "disable_state": "disabled",
    "disable_traffic_share": "0.00",
    "retirement_reason": "harmful",
    "final_state": "retired",
    "fallback_removed": true,
    "current_cache_allowed": false,
    "expected_code": "SOURCE_RETIRED_HARMFUL"
  },
  "success_thresholds": {
    "quality_min_label": "usable",
    "coverage_rate_min": "0.75",
    "target_coverage_rate_min": "0.80",
    "p95_added_wall_ms_max": 2500,
    "mean_added_wall_ms_max": 900,
    "added_prompt_tokens_per_ticker_max": 1500,
    "timeout_rate_max": "0.02",
    "harm_rate_max": "0.20",
    "severe_harm_rate_max": "0.05"
  },
  "required_mutations": [
    "prd_row_missing",
    "prd_link_duplicate",
    "bidirectional_gap",
    "state_jump",
    "quality_count_misuse",
    "source_addition_success",
    "latency_only_success",
    "harmful_source_current",
    "stale_cache_current",
    "policy_hash_mismatch"
  ]
}
```

## Acceptance Criteria

1. The document is marked draft near the title and has no done marker.
2. The local PRD map has rows whose first cells are exactly `PRD 01`, `PRD 02`, `PRD 03`, and `PRD 04`.
3. Each local PRD file is linked exactly once with the `prds/<filename>` form.
4. The onboarding -> quality -> evaluation -> lifecycle flow is independent and does not rely on older SPEC output.
5. The state diagram blocks closed sources from current fallback and requires fresh evidence for reopening.
6. Cost and quality success criteria both have explicit thresholds or labels.
7. Happy promotion and harmful retirement are both covered by prose and parseable fixture data.
8. Parser and mutation requirements cover links, bidirectional contract gaps, quality misuse, value misuse, policy hash mismatch, stale cache, harmful fallback, and illegal promotion.
