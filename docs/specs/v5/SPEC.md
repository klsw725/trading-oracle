# Trading Oracle v5 - Causal Graph Quality
> **상태**: ✅ 완료

v5는 인과 그래프가 LLM 상식 문자열에서 macro prompt의 검증된 근거로 이동하기 전에 필요한 품질 계약이다. 이 SPEC은 v5 로컬 PRD 01부터 04까지만 종합한다. v2 SPEC과 누적 분석은 문제 근거이며, 다른 SPEC 완료 여부는 v5의 성공 또는 실패를 바꾸지 않는다.

## Local PRD Links

| PRD | PRD 문서 | 상태 | 계약 |
| --- | --- | --- | --- |
| PRD 01 | [Node Canonicalization](prds/prd01-node-canonicalization.md) | ✅ 완료 | legacy `subject`와 `object` 문자열을 versioned canonical node로 바꾸고, 방향 의미가 다른 노드 병합을 거절한다. |
| PRD 02 | [Series Mapping Provenance](prds/prd02-series-mapping-provenance.md) | ✅ 완료 | canonical node를 정량 series에 연결할 때 transform, unit, direction, source, as_of, provenance, approval, expiry를 보존한다. |
| PRD 03 | [Statistical Verification](prds/prd03-statistical-verification.md) | ✅ 완료 | approved mapping pair를 stationarity, lag search, corrected alpha, holdout, structural break, stability gate로 판정한다. |
| PRD 04 | [Prompt Injection Gate](prds/prd04-prompt-injection-gate.md) | ✅ 완료 | fresh `verified_stable` statistical lead evidence만 macro prompt의 verified section에 넣는다. |

## Exact Evidence

| Evidence | Exact observation | Contract impact |
| --- | --- | --- |
| `docs/2026-08-05-22-58-누적결과-기반-고도화-분석.md:40` to `:44` | 인과 그래프는 전체 1,500 triples, mapping 가능 90개, 검증 통과 17개, mapping 불가 1,410개로 기록됐다. | v5는 graph 확대보다 node 품질, mapping provenance, 검증 안정성, prompt eligibility를 먼저 고정한다. |
| `docs/specs/v2/SPEC.md:207` to `:224` | v2는 node to series mapping, Granger test, confidence tagging, direction match를 한 흐름으로 설명한다. | v5는 같은 흐름을 네 개의 독립 계약으로 쪼개고 각 경계의 artifact를 versioned schema로 만든다. |
| `docs/specs/v2/SPEC.md:594` to `:596` | Granger는 true causality가 아니라 predictive contribution이며, non-stationarity와 structural break가 제약으로 기록됐다. | v5는 `statistical_lead_evidence`라는 claim label만 허용하고 holdout 및 stability gate 없이 prompt promotion을 허용하지 않는다. |
| `docs/specs/v5/prds/prd01-node-canonicalization.md:70` to `:157` | PRD 01 output은 `schema_version`, `nodes`, `triples`, `canonicalization_report`를 분리한다. | downstream 계약은 legacy string이 아니라 `canonical_node_id`를 primary key로 소비한다. |
| `docs/specs/v5/prds/prd01-node-canonicalization.md:397` to `:405` | 세 exchange-rate alias는 하나의 canonical node로 merge되고, `원화 강세`는 `opposite_direction`으로 reject된다. | happy trace와 rejection trace는 node layer에서 시작해야 한다. |
| `docs/specs/v5/prds/prd02-series-mapping-provenance.md:6` to `:9` | substring mapping은 discovery evidence일 뿐 approved mapping이 아니며, mapping은 transform, unit, direction, source, as_of, provenance, suitability, manual approval, expiry를 가져야 한다. | PRD 02 approval 없이는 PRD 03 test 대상이 될 수 없다. |
| `docs/specs/v5/prds/prd02-series-mapping-provenance.md:153` to `:194` | mapping result와 field rules는 approved, manual review, unmappable, stale, proxy, misleading, malformed, dirty 상태를 구분한다. | false proxy와 stale approval은 통계 검증 전에 닫힌다. |
| `docs/specs/v5/prds/prd03-statistical-verification.md:6` to `:8` | approved mapped pair는 stable predictive relationship으로 부르기 전에 stationarity, lag search, correction, split, structural break, out-of-sample gates를 통과해야 한다. | train p value만 좋은 pair는 prompt 근거가 아니다. |
| `docs/specs/v5/prds/prd03-statistical-verification.md:264` to `:283` | terminal status는 `verified_stable`, all `rejected_*`, and `inconclusive`다. | PRD 04는 이 세 class를 prompt section에서 섞지 않는다. |
| `docs/specs/v5/prds/prd04-prompt-injection-gate.md:6` to `:9` | verified, inconclusive, rejected triples must stay separate, and verified section can contain only fresh `verified_stable` results from the current schema. | macro prompt injection is the last gate, not another verifier. |
| `docs/specs/v5/prds/prd04-prompt-injection-gate.md:150` to `:160` | verified triples need `verified_stable`, `statistical_lead_evidence`, freshness, confidence, provenance, valid JSON types, and budget fit; inconclusive and rejected triples are not eligible. | rejected triple failure must result in exclusion from verified prompt text. |

## Problem

The legacy causal graph stores market ideas as raw strings. v2 already added a Granger-based verifier and prompt filtering, but the current evidence shows that only a small part of the graph maps to series and an even smaller part passes verification. A larger graph would add more unchecked strings unless the quality path is fixed first.

v5 treats causal graph quality as a four-boundary problem.

1. Node identity must be stable and direction-aware.
2. Series mapping must be approved with provenance, not inferred from a keyword hit.
3. Statistical verification must separate stable evidence from in-sample, stale, flaky, leaky, or inconclusive results.
4. Prompt injection must render only fresh verified evidence and keep every rejected or inconclusive result out of the verified section.

## Users And Outcomes

| User | Need | v5 outcome |
| --- | --- | --- |
| Investor reading macro analysis | See which causal chains are supported by data without being told Granger proves causality. | Prompt text says statistical lead evidence with lag, train p value, holdout p value, confidence, and provenance. |
| Maintainer reviewing graph quality | Know why a node, mapping, or pair was accepted or rejected. | Each boundary emits append-only mutation evidence and machine-readable rejection reasons. |
| Macro perspective implementation | Build prompt context without mixing raw graph background with verified evidence. | PRD 04 package exposes `verified_prompt_records` and `excluded_prompt_records` separately. |

## Architecture

```text
node -> mapping -> statistical -> injection

legacy causal graph
  -> PRD 01 canonical graph
     schema_version: causal-node-canonicalization.1
     key: canonical_node_id
  -> PRD 02 mapping artifact
     schema_version: causal-series-mapping.1
     gate: non expired approved_manual mapping
  -> PRD 03 verification artifact
     schema_version: causal-statistical-verification.1
     gate: verified_stable with statistical_lead_evidence
  -> PRD 04 prompt package
     schema_version: causal-prompt-injection.1
     gate: fresh, confident, valid, within budget
  -> macro perspective verified causal evidence section
```

Each artifact is append friendly. Later artifacts do not rewrite earlier artifacts. Legacy graph, mapping candidates, rejected pairs, and excluded prompt records remain available as audit evidence, but they do not gain verified status by appearing later in the flow.

## Decided Contracts

### Canonical node contract

PRD 01 owns node identity. It reads legacy JSON without `schema_version`, parses triples, creates `causal-node-canonicalization.1`, and stores nodes separately from triples. `canonical_node_id` is deterministic from schema version, canonical label, normalized label, and direction. Alias changes, secondary domain additions, and `created_from` provenance do not change the ID.

Opposite direction collapse is forbidden. `원/달러 환율 상승`, `USD/KRW 상승`, and `달러 대비 원화 약세` can merge into `원달러 환율 상승`; `원화 강세` cannot merge with that up-polarity node.

### Mapping provenance contract

PRD 02 owns node to series approval. It consumes PRD 01 canonical nodes by `canonical_node_id`. A flat keyword file can create candidates only. Approved mappings require transform, unit, direction, source, as_of, provenance hash, suitability, manual approval, and expiry. Unmappable output is valid because it prevents a false statistical pair.

Proxy, misleading, dirty, stale, and malformed candidates close before any Granger run. A flat row such as interest-rate text mapped to `GOLD` is dirty evidence unless reviewed and approved with economic suitability.

### Statistical verification contract

PRD 03 owns pair testing after both endpoints have non expired approved mappings. It applies the PRD 02 transform, aligns series by timestamp, splits chronologically, locks stationarity and lag choice on train, applies Bonferroni corrected alpha, tests holdout, and checks structural breaks plus out-of-sample stability.

The only promoted statistical status is `verified_stable`. Train-only success becomes `rejected_in_sample_only`. Missing rows, expired mapping, non-stationarity after max diff, or insufficient holdout rows become `inconclusive` or rejected with evidence.

### Prompt injection contract

PRD 04 owns the final prompt-ready package. It consumes PRD 03 `pair_results`, not legacy `verified_triples`. A verified prompt record must keep `claim_label = statistical_lead_evidence`, must be fresh at `prompt_cutoff`, must meet confidence threshold, must carry provenance hashes, must have valid JSON types, and must fit token budget.

Rejected and inconclusive records can be retained for audit, but they never render inside the verified causal evidence section. Rollback preserves the last valid prompt package when a new package fails assembly, but rollback cannot revive expired evidence.

## Happy Trace

1. Legacy graph contains `원/달러 환율 상승 increases 수출기업 마진 개선`.
2. PRD 01 normalizes the subject to `원달러 환율 상승`, creates `cnode_0b6a943c2860b6e61893`, keeps direction `{ "kind": "level_change", "polarity": "up" }`, and rewrites the triple to canonical IDs.
3. PRD 02 approves that node to `USD_KRW` with `pct_change_1d`, `percent_change`, `same`, direct market suitability, provenance hash, manual approval, and expiry.
4. PRD 03 tests the approved pair and returns `statpair_fa52b889d05d6dbf97ab` as `verified_stable`, `claim_label = statistical_lead_evidence`, selected lag `5`, train p value `0.000400`, holdout p value `0.000600`, corrected alpha `0.000833333333`, and stability pass.
5. PRD 04 emits `promptrec_2af7c8b7135131b2e450` with `eligibility = verified_prompt_eligible`, render label `데이터 검증됨, 통계적 선행 근거`, freshness pass, confidence `0.910000`, provenance hashes, and token estimate `43`.
6. The macro prompt can render that one record in the verified causal evidence section.

## Rejected Triple Failure

1. A candidate attempts to merge `원화 강세` into the up-polarity exchange-rate node. PRD 01 rejects the mutation with `opposite_direction`.
2. A candidate maps `미국 기준금리 인상` to `GOLD` from the flat legacy map. PRD 02 rejects it as dirty or misleading unless explicit manual approval proves suitability.
3. A pair passes train with p value `0.000400` but holdout p value is `0.120000`. PRD 03 returns `rejected_in_sample_only` with reason `holdout_p_value_above_corrected_alpha`.
4. PRD 04 sees the rejected terminal status and appends `exclude_rejected`. No render text is produced for the verified causal evidence section.

## Implementation Order

1. Implement canonical node migration first. Mapping, statistics, and prompt injection must not consume raw legacy strings as primary keys.
2. Implement mapping provenance next. Statistical verification needs approved series links, transform, unit, direction, source, as_of, provenance, and expiry.
3. Implement statistical verification after mapping approval exists. Holdout and stability gates must be in place before any prompt promotion.
4. Implement prompt injection gate last. It consumes only the versioned verification artifact and emits a prompt package without rewriting upstream artifacts.

This order is local to v5. v5 can be designed, implemented, tested, and rejected without waiting for any other SPEC completion state.

## Success Criteria

1. Every tested pair is traceable from legacy triple text to canonical node IDs, approved mapping hashes, statistical pair ID, and prompt record ID.
2. Opposite-direction node collapse is rejected before mapping.
3. Keyword or flat-map series hits cannot become approved mappings without provenance and manual approval.
4. Granger output is labeled as statistical lead evidence, never true causality.
5. Train-only, stale, leaky, p-hacked, flaky, malformed, and inconclusive results cannot enter verified prompt text.
6. Fresh verified prompt records are ordered deterministically by freshness, confidence, holdout p value, lag, and pair ID.
7. Rejected and inconclusive records remain audit records and never share the verified causal evidence section.
8. The local PRD links and backlinks remain valid, and no other SPEC completion dependency is introduced.

## Validation Requirements For This SPEC

Authoring QA for this SPEC must include these checks.

1. Manual Read of this file and the four v5 PRDs.
2. Link validation for every Markdown link in this file and every v5 PRD backlink to `../SPEC.md`.
3. Anchor validation for any Markdown link that includes a fragment.
4. Sequence check that the local PRD table has exactly first cells `PRD 01`, `PRD 02`, `PRD 03`, and `PRD 04` in order.
5. Link count check that each relative local PRD link appears exactly once in this SPEC.
6. Term check that this file has exactly one completed status line, no draft marker, no numbered global work label, `statistical_lead_evidence`, `verified_stable`, `inconclusive`, and `rejected_*` separation.
7. Mutation probes for malformed PRD link, bad anchor, duplicate PRD row, missing PRD row, misleading true causality wording, rejected evidence rendered as verified, and dependency wording that makes another SPEC completion a gate.
