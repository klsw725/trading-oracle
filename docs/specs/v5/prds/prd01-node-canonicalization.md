# PRD 01: Node Canonicalization
> **상태**: ✅ 완료

## 문제

현재 인과 그래프는 `subject`와 `object`를 문자열 노드로 바로 저장한다. 같은 시장 개념이 다른 표현으로 들어오면 서로 다른 노드가 되고, 반대 방향 의미가 같은 노드로 합쳐질 위험도 있다. v5의 첫 계약은 legacy triple을 versioned canonical node로 바꾸는 규칙을 고정한다.

이 문서는 [v5 SPEC](../SPEC.md)의 로컬 PRD 01이다. 독립 실행 가능한 계약이며, 다른 v4 문서 완료 여부에 의존하지 않는다.

## 범위

이 PRD는 node canonicalization만 다룬다.

포함한다.

1. canonical node schema와 schema version
2. deterministic canonical node ID
3. alias와 synonym 수집 규칙
4. 방향 의미와 반대 방향 collapse 금지
5. merge, conflict, domain ownership, migration 규칙
6. legacy fixture와 실패 우선 검증 시나리오

제외한다.

1. 통계 검증, Granger test, p-value, lag
2. prompt 주입 우선순위
3. 시계열 mapping provenance
4. 추천 성과 측정과 attribution

## 현재 입력 계약

`data/causal_graph.json`의 legacy schema는 다음 구조다.

```json
{
  "metadata": {
    "created_at": null,
    "updated_at": "2026-08-06",
    "num_topics": 2436,
    "num_triples": 1500,
    "llm_model": ""
  },
  "triples": [
    {
      "subject": "원인 문자열",
      "relation": "increases",
      "object": "결과 문자열",
      "domain": "매크로"
    }
  ]
}
```

Observed schema constraints from the current fixture:

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `metadata.created_at` | yes | string or null | Legacy fixture can be null. |
| `metadata.updated_at` | yes | string | Date string. |
| `metadata.num_topics` | yes | integer | Legacy count. |
| `metadata.num_triples` | yes | integer | Legacy count. |
| `metadata.llm_model` | yes | string | Can be empty. |
| `triples[].subject` | yes | string | Legacy node text. |
| `triples[].relation` | yes | string enum | `increases`, `decreases`, `causes`, `enables`, `blocks`. |
| `triples[].object` | yes | string | Legacy node text. |
| `triples[].domain` | yes | string | Source topic domain. |

Legacy data has no `schema_version` and no `nodes` collection. Migration must treat that absence as legacy input, not as a parse failure.

## Canonical Output Schema

The migrated graph stores nodes separately from triples. Triples keep direction by referencing canonical node IDs.

```json
{
  "schema_version": "causal-node-canonicalization.1",
  "metadata": {
    "created_at": null,
    "updated_at": "2026-08-06",
    "num_topics": 2436,
    "num_triples": 1500,
    "llm_model": "",
    "canonicalized_at": "2026-08-06",
    "canonicalizer_version": "node-canonicalizer.1"
  },
  "nodes": [
    {
      "canonical_node_id": "cnode_0b6a943c2860b6e61893",
      "canonical_label": "원달러 환율 상승",
      "normalized_label": "원달러 환율 상승",
      "direction": {
        "kind": "level_change",
        "polarity": "up"
      },
      "owner_domain": "환율",
      "secondary_domains": ["글로벌매크로"],
      "aliases": [
        {
          "alias": "원/달러 환율 상승",
          "normalized_alias": "원달러 환율 상승",
          "source": "legacy_triple",
          "merge_status": "merged"
        }
      ],
      "created_from": [
        {
          "legacy_field": "subject",
          "legacy_text": "원/달러 환율 상승",
          "legacy_triple_index": 0
        }
      ]
    },
    {
      "canonical_node_id": "cnode_96b23578f19cae76707f",
      "canonical_label": "수출기업 마진 개선",
      "normalized_label": "수출기업 마진 개선",
      "direction": {
        "kind": "state",
        "polarity": "up"
      },
      "owner_domain": "환율",
      "secondary_domains": [],
      "aliases": [
        {
          "alias": "수출기업 마진 개선",
          "normalized_alias": "수출기업 마진 개선",
          "source": "legacy_triple",
          "merge_status": "merged"
        }
      ],
      "created_from": [
        {
          "legacy_field": "object",
          "legacy_text": "수출기업 마진 개선",
          "legacy_triple_index": 0
        }
      ]
    }
  ],
  "triples": [
    {
      "subject_node_id": "cnode_0b6a943c2860b6e61893",
      "relation": "increases",
      "object_node_id": "cnode_96b23578f19cae76707f",
      "domain": "환율",
      "legacy_subject": "원/달러 환율 상승",
      "legacy_object": "수출기업 마진 개선"
    }
  ],
  "canonicalization_report": {
    "legacy_nodes_seen": 2,
    "canonical_nodes_created": 2,
    "aliases_merged": 1,
    "conflicts_rejected": 0,
    "malformed_triples_rejected": 0
  }
}
```

## Canonical Node Fields

| Field | Required | Mutable | Rule |
|-------|----------|---------|------|
| `canonical_node_id` | yes | no | Deterministic ID from canonical seed. |
| `canonical_label` | yes | controlled | Human label chosen by owner domain. Changing it requires ID impact review. |
| `normalized_label` | yes | no | Text after Unicode NFKC, trim, repeated whitespace collapse, punctuation normalization, and domain dictionary rewrite. |
| `direction.kind` | yes | no | One of `level_change`, `flow_change`, `event`, `state`, `entity`, `unknown`. |
| `direction.polarity` | yes | no | One of `up`, `down`, `neutral`, `mixed`, `unknown`. |
| `owner_domain` | yes | controlled | Domain that owns label, alias, and conflict decisions. |
| `secondary_domains` | yes | yes | Sorted unique domains that also used this node. |
| `aliases` | yes | yes | All accepted legacy texts and synonyms. |
| `created_from` | yes | append only | Trace back to legacy text and triple index. |

## Deterministic ID

Canonical node ID is deterministic and independent of input order.

Algorithm:

1. Parse legacy JSON into typed records before mutation.
2. Normalize every candidate node string.
3. Infer direction semantics from normalized text and relation context.
4. Resolve merge or reject decision.
5. Build ID seed only after the canonical label and direction are fixed.
6. Encode seed with canonical JSON: `ensure_ascii=false`, `sort_keys=true`, separators `,` and `:`.
7. Set `canonical_node_id = "cnode_" + first_20_hex(sha256(canonical_json(seed)))`.

Seed shape:

```json
{
  "schema_version": "causal-node-canonicalization.1",
  "canonical_label": "원달러 환율 상승",
  "normalized_label": "원달러 환율 상승",
  "direction": {
    "kind": "level_change",
    "polarity": "up"
  }
}
```

Fixture IDs in this document must be recomputed from visible seeds. The schema example above uses these exact seeds:

| Canonical label | Visible seed | Expected ID |
|-----------------|--------------|-------------|
| `원달러 환율 상승` | `{"schema_version":"causal-node-canonicalization.1","canonical_label":"원달러 환율 상승","normalized_label":"원달러 환율 상승","direction":{"kind":"level_change","polarity":"up"}}` | `cnode_0b6a943c2860b6e61893` |
| `수출기업 마진 개선` | `{"schema_version":"causal-node-canonicalization.1","canonical_label":"수출기업 마진 개선","normalized_label":"수출기업 마진 개선","direction":{"kind":"state","polarity":"up"}}` | `cnode_96b23578f19cae76707f` |
| `원화 강세` | `{"schema_version":"causal-node-canonicalization.1","canonical_label":"원화 강세","normalized_label":"원화 강세","direction":{"kind":"level_change","polarity":"down"}}` | `cnode_9b5b931129be44d18451` |

`owner_domain`, `secondary_domains`, `aliases`, and `created_from` are excluded from the seed. Adding an alias or another domain must not change the canonical ID.

## Alias And Synonym Rules

An alias is accepted only when it preserves the same market concept and the same direction semantics.

Normalize text using this ordered rule set:

1. Unicode NFKC normalization.
2. Strip leading and trailing whitespace.
3. Collapse repeated whitespace to one space.
4. Remove pure formatting punctuation such as `/`, `·`, `_`, and repeated spaces when it does not change Korean reading.
5. Apply domain dictionary rewrites, for example `원/달러`, `USD/KRW`, and `달러 대비 원화` can map to `원달러` only after direction is checked.
6. Keep direction words such as `상승`, `하락`, `약세`, `강세`, `증가`, `감소`, `완화`, `긴축`.

Synonyms are not free text. Each synonym must store the source:

| Source | Meaning |
|--------|---------|
| `legacy_triple` | Text came from current `subject` or `object`. |
| `domain_dictionary` | Text came from a reviewed dictionary entry. |
| `manual_review` | Human approved an ambiguous synonym. |

## Direction Semantics

Direction semantics belong to the node. Causal relation semantics belong to the edge.

Node direction examples:

| Text | `direction.kind` | `direction.polarity` |
|------|------------------|----------------------|
| `원달러 환율 상승` | `level_change` | `up` |
| `원화 약세` | `level_change` | `up` |
| `원화 강세` | `level_change` | `down` |
| `반도체 수요 증가` | `flow_change` | `up` |
| `반도체 수요 감소` | `flow_change` | `down` |
| `미중 무역 갈등` | `event` | `neutral` |

Relation direction examples:

| Relation | Edge meaning |
|----------|--------------|
| `increases` | Subject raises or amplifies object. |
| `decreases` | Subject lowers or weakens object. |
| `causes` | Subject causes object without signed magnitude. |
| `enables` | Subject makes object easier or possible. |
| `blocks` | Subject blocks or prevents object. |

Opposite node direction cannot collapse into the same canonical node. `원화 약세` and `원화 강세` are different nodes even if both mention won exchange rate. A caller that tries to merge them must receive a reject mutation with conflict evidence.

## Merge Rules

Two candidate nodes merge when all conditions hold:

1. `normalized_label` is equal after dictionary rewrite, or a reviewed synonym maps both texts to the same canonical label.
2. `direction.kind` is equal.
3. `direction.polarity` is equal.
4. Neither side has a conflict record against the other side.

When nodes merge:

1. Keep the existing `canonical_node_id` if one side already has it.
2. Sort and deduplicate `aliases` by `normalized_alias` then `alias`.
3. Sort and deduplicate `secondary_domains`.
4. Append `created_from` entries without dropping prior provenance.
5. Rewrite migrated triples to canonical node IDs.

Merge is a mutation on canonical graph output, not an in-place mutation of legacy JSON.

## Reject Rules

A candidate node is rejected from a merge when any condition holds:

1. Direction polarity is opposite.
2. Direction kind differs and no reviewed mapping allows it.
3. Text is misleading, for example label says `상승` but direction parser returns `down`.
4. The candidate comes from a malformed triple.
5. The owner domain has an unresolved conflict for the alias.

Reject mutation shape:

```json
{
  "mutation": "reject_merge",
  "reason": "opposite_direction",
  "left": {
    "legacy_text": "원화 약세",
    "direction": {
      "kind": "level_change",
      "polarity": "up"
    }
  },
  "right": {
    "legacy_text": "원화 강세",
    "direction": {
      "kind": "level_change",
      "polarity": "down"
    }
  }
}
```

## Conflict Matrix

| Case | Example A | Example B | Expected decision | Reason |
|------|-----------|-----------|-------------------|--------|
| Formatting alias | `원/달러 환율 상승` | `원달러 환율 상승` | merge | Same label and direction. |
| Economic synonym | `달러 대비 원화 약세` | `원달러 환율 상승` | merge | Same exchange rate direction after dictionary rewrite. |
| Opposite direction | `원화 약세` | `원화 강세` | reject | Polarity differs. |
| Signed demand conflict | `반도체 수요 증가` | `반도체 수요 감소` | reject | Polarity differs. |
| Generic text | `수요 증가` | `반도체 수요 증가` | reject pending owner review | Generic text lacks domain ownership. |
| Misleading direction | `원달러 환율 상승` with parsed polarity `down` | `원달러 환율 상승` with parsed polarity `up` | reject malformed candidate | Parser and label disagree. |
| Domain collision | `마진 개선` in `반도체` | `마진 개선` in `자동차` | reject pending owner review | Same label may mean different business driver. |

## Domain Ownership

Domain ownership decides label and alias authority, not statistical truth.

Rules:

1. If a legacy triple has a non-empty `domain`, the first canonical node candidate gets that value as `owner_domain`.
2. If another domain uses the same canonical node, it is added to `secondary_domains`.
3. A new alias from a secondary domain is accepted only when direction semantics match and no owner conflict exists.
4. Ambiguous generic terms require owner review before merge.
5. Owner changes are allowed only through a migration record that states old owner, new owner, reason, and affected node IDs.

## Migration Rules

Migration reads legacy JSON and writes a new canonicalized artifact. It never rewrites the legacy file in place.

Execution order:

1. Read the source file.
2. Parse JSON.
3. Detect schema version.
4. If `schema_version` is absent, treat input as legacy schema.
5. Validate required legacy triple fields.
6. Produce failing-first fixtures before code changes.
7. Apply deterministic ID, merge, and reject mutations.
8. Write canonical output with `schema_version = "causal-node-canonicalization.1"`.

Malformed triples are excluded from migrated triples and counted in `canonicalization_report.malformed_triples_rejected`. The report must include enough evidence to fix source extraction later.

## Legacy Fixture

This fixture proves that three aliases merge into one canonical node and one opposite-direction alias is rejected.

Input:

```json
{
  "metadata": {
    "created_at": null,
    "updated_at": "2026-08-06",
    "num_topics": 4,
    "num_triples": 4,
    "llm_model": "fixture"
  },
  "triples": [
    {
      "subject": "원/달러 환율 상승",
      "relation": "increases",
      "object": "수출기업 마진 개선",
      "domain": "환율"
    },
    {
      "subject": "USD/KRW 상승",
      "relation": "increases",
      "object": "수출기업 마진 개선",
      "domain": "글로벌매크로"
    },
    {
      "subject": "달러 대비 원화 약세",
      "relation": "increases",
      "object": "수출기업 마진 개선",
      "domain": "환율"
    },
    {
      "subject": "원화 강세",
      "relation": "decreases",
      "object": "수출기업 마진 개선",
      "domain": "환율"
    }
  ]
}
```

Expected canonicalization result:

1. `원/달러 환율 상승`, `USD/KRW 상승`, and `달러 대비 원화 약세` merge into one canonical node labeled `원달러 환율 상승`.
2. The merged node has ID `cnode_0b6a943c2860b6e61893` and direction `{ "kind": "level_change", "polarity": "up" }`.
3. The merged node has three aliases and at least three `created_from` entries.
4. `owner_domain` is `환율` and `secondary_domains` includes `글로벌매크로`.
5. `원화 강세` has candidate ID `cnode_9b5b931129be44d18451` and does not merge with the up-polarity node.
6. The rejected opposite-direction candidate appears in a `reject_merge` mutation with reason `opposite_direction`.

## Failing-First Scenarios

Each implementation starts by writing these failing tests or equivalent fixtures, then makes them pass.

| Scenario | Given | When | Then |
|----------|-------|------|------|
| Happy merge | Legacy fixture has three exchange-rate aliases with up polarity. | Migration runs after Read and parse JSON. | One canonical node exists with three aliases and ID `cnode_0b6a943c2860b6e61893`. |
| Opposite direction reject | Legacy fixture includes `원화 강세`. | Merge candidate is compared to `원달러 환율 상승`. | Merge is rejected with `opposite_direction`. |
| stale schema | Input has no `schema_version`. | Migration starts. | Input is treated as legacy and canonical output gets current schema version. |
| Dirty duplicate | Same alias appears twice in different triples. | Merge mutation runs. | Alias list is deduplicated and provenance keeps both source indexes. |
| Misleading direction | Candidate text says `상승` but parser returns down polarity. | Candidate is normalized. | Candidate is rejected as malformed direction evidence. |
| Malformed triple | Triple is missing `relation` or has non-string `subject`. | Parse boundary validates triples. | Triple is excluded and counted in report. |

## Acceptance Criteria

1. The PRD defines `causal-node-canonicalization.1` as the canonical node schema version.
2. Deterministic ID generation is defined with canonical JSON and SHA-256 first 20 hex.
3. Alias and synonym merge rules preserve direction semantics.
4. Opposite-direction node collapse is explicitly rejected.
5. Conflict matrix covers merge, reject, generic, misleading, and domain collision cases.
6. Legacy fixture shows three aliases merging into one canonical node.
7. Migration rules require Read, parse JSON, deterministic ID, merge mutations, and reject mutations.
8. The document does not define statistical verification or prompt injection policy.

## 구현 및 실행

- typed legacy parse boundary: `src/causal/canonical_models.py`
- normalization, direction, and owner-review rules: `src/causal/canonical_rules.py`
- deterministic ID and transactional merge/reject migration: `src/causal/canonicalizer.py`
- executable acceptance checks: `src/causal/canonical_acceptance.py`
- executable acceptance fixture: `docs/specs/v5/fixtures/prd01-node-canonicalization.json`
- migration and fixture CLI: `scripts/canonicalize_nodes.py`

```bash
uv run scripts/canonicalize_nodes.py verify-fixture
uv run scripts/canonicalize_nodes.py migrate \
  --input data/causal_graph.json \
  --output data/causal_graph_canonical.json
```

Migration은 legacy source와 같은 출력 경로를 거절한다. 동일한 canonical artifact를 재생성하면 `write_status = unchanged`를 반환하며, 다른 내용으로 기존 artifact를 덮어쓰지 않는다.
