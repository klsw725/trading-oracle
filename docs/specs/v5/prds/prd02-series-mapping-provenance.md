# PRD 02: Series Mapping Provenance
> **상태**: 📝 초안
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## Problem

Canonical nodes from PRD 01 need an auditable path to quantitative series before any Granger run can use them. The current mapper turns node text into a series key by substring rules, then writes a plain node to series JSON file. That is useful as discovery evidence, but it is not enough to approve a mapping.

This PRD defines the canonical node to series mapping contract. A mapping must carry transform, unit, direction, source, as_of, provenance, suitability, manual approval, and expiry. Keyword hits can create candidates only. They must never be named approved or statistically proven.

## Scope

This PRD covers:

1. Mapping schema version `causal-series-mapping.1`.
2. Canonical node to one or many series links.
3. Transform, unit, direction, source, as_of, provenance, suitability, approval, and expiry fields.
4. Unmappable, stale, proxy, misleading, dirty, and malformed rejection rules.
5. Read, JSON, and mutation QA fixtures.

This PRD excludes:

1. Node canonicalization rules already owned by PRD 01.
2. Granger p-value, lag, Bonferroni, or confidence policy.
3. Prompt injection ordering.
4. Recommendation attribution.

## Exact Evidence From The Current Codebase

| Evidence | Exact observation | Contract impact |
| --- | --- | --- |
| `docs/specs/v5/prds/prd01-node-canonicalization.md:25` to `:28` | PRD 01 explicitly excludes statistical tests, prompt injection, and series mapping provenance. | PRD 02 owns only mapping provenance. |
| `docs/specs/v5/prds/prd01-node-canonicalization.md:70` to `:157` | PRD 01 output stores canonical nodes and triples separately. | Mapping input must reference `canonical_node_id`, not raw legacy strings. |
| `src/causal/verifier.py:16` to `:18` | The current mapper is labeled rule based and keyword to series. | Keyword output is candidate evidence only. |
| `src/causal/verifier.py:47` to `:50` | The mapper accepts a series when a keyword substring appears in lowercased node text. | Substring match cannot approve suitability. |
| `src/causal/verifier.py:160` to `:164` | A triple becomes mappable only when both endpoint node strings have series keys and those keys differ. | PRD 02 must expose why each endpoint is approved, rejected, or unmappable before pair testing. |
| `src/causal/verifier.py:185` to `:188` | Granger receives only `macro_df[s_key]` and `macro_df[o_key]`. | Transform, unit, and direction need to be resolved before this call. |
| `src/causal/verifier.py:260` to `:261` | Verification writes `data/node_series_map.json` from the generated map. | New mapping output must be a new artifact or controlled mutation, not an implicit rewrite of raw evidence. |
| `data/node_series_map.json:1` to `:420` | The existing file is a flat object of node text to one series key. | It lacks source, as_of, transform, unit, approval, expiry, and rejection evidence. |
| `data/node_series_map.json:2` | `미국 기준금리 인상` maps to `GOLD`. | Proxy or misleading links must be rejected unless explicitly approved by an owner. |
| `data/node_series_map.json:98` | `미국 10년물 국채금리 상승` maps to `US10YT`. | Similar rate concepts already map to different series, so canonical node mapping must carry exact rationale. |
| `src/data/macro.py:20` to `:34` | `MACRO_SYMBOLS` defines available base series and raw symbols. | Mapping can only approve series present in the versioned catalog. |
| `src/data/macro.py:117` to `:138` | Derived columns are calculated after fetch, including percentage changes, diffs, and term spread. | Mapping must say whether a node uses raw close, diff, percentage change, or composite transform. |
| `src/data/macro.py:224` to `:228` | Prompt formatting assigns units for macro series. | Mapping unit must be explicit and not inferred by prompt formatting. |

## Canonical Input

The mapper consumes the PRD 01 artifact.

Required input fields:

| Field | Rule |
| --- | --- |
| `schema_version` | Must equal `causal-node-canonicalization.1`. |
| `nodes[].canonical_node_id` | Required stable key. |
| `nodes[].canonical_label` | Human readable label for approval review. |
| `nodes[].direction.kind` | Used to pick level, flow, event, or entity mapping. |
| `nodes[].direction.polarity` | Used to check series direction compatibility. |
| `triples[]` | Optional for mapping a single node, required when generating pair test candidates. |

Raw legacy text can be retained in evidence, but it cannot be the primary mapping key.

## Series Catalog

Every approved series link must point to a catalog entry. A catalog entry describes the series before any node mapping.

```json
{
  "schema_version": "causal-series-mapping.1",
  "series_catalog": [
    {
      "series_id": "USD_KRW",
      "raw_symbol": "USD/KRW",
      "source_id": "finance_data_reader",
      "adapter_version": "macro-series.1",
      "native_unit": "KRW_per_USD",
      "native_frequency": "daily_close",
      "as_of": "2026-08-06",
      "expires_at": "2026-08-07",
      "provenance_hash": "sha256:66b90b8003ce65927c603a4450be9f5b91fc81849930a34125c9c0a540389d85"
    }
  ]
}
```

Catalog rules:

| Field | Rule |
| --- | --- |
| `series_id` | Must match a base or explicitly derived series key. |
| `raw_symbol` | Must match the upstream query symbol or derived formula name. |
| `source_id` | Required. Examples are `finance_data_reader`, `toss_exchange_rate`, or `derived_macro_series`. |
| `adapter_version` | Required version of the fetch or derive code path. |
| `native_unit` | Required. Examples are `percent`, `KRW_per_USD`, `USD_per_barrel`, `index_points`. |
| `native_frequency` | Required. Daily close is the default for current macro data. |
| `as_of` | Required data cutoff for the catalog entry. |
| `expires_at` | Required. A mapping cannot be used after this instant without refresh. |
| `provenance_hash` | Required hash over redacted source identity, symbol, cutoff, and adapter version. |

## Mapping Output Schema

The mapping artifact is append friendly and auditable.

```json
{
  "schema_version": "causal-series-mapping.1",
  "source_node_schema_version": "causal-node-canonicalization.1",
  "mapping_policy_version": "series-mapper.1",
  "generated_at": "2026-08-06T00:00:00+09:00",
  "series_catalog": [],
  "mappings": [],
  "mapping_mutations": [],
  "qa": {
    "read_checks": [],
    "json_checks": [],
    "mutation_checks": []
  }
}
```

Each mapping record follows this shape.

```json
{
  "canonical_node_id": "cnode_0b6a943c2860b6e61893",
  "canonical_label": "원달러 환율 상승",
  "mapping_result": "approved_manual",
  "mapping_kind": "single_series",
  "series_links": [
    {
      "series_id": "USD_KRW",
      "transform": "pct_change_1d",
      "unit": "percent_change",
      "direction": "same",
      "source_id": "finance_data_reader",
      "as_of": "2026-08-06",
      "provenance_hash": "sha256:66b90b8003ce65927c603a4450be9f5b91fc81849930a34125c9c0a540389d85",
      "suitability": "direct_market_series",
      "suitability_evidence": "Node label describes USD/KRW level moving up, and USD_KRW native unit is KRW per USD.",
      "manual_approval": {
        "required": true,
        "approved_by": "macro-domain-owner",
        "approved_at": "2026-08-06T00:00:00+09:00",
        "approval_reason": "Direct series measures the same exchange rate concept and same direction.",
        "expires_at": "2026-09-05T00:00:00+09:00"
      }
    }
  ],
  "proxy_candidates_rejected": [],
  "unmappable_reason": null
}
```

Allowed `mapping_result` values:

| Value | Meaning |
| --- | --- |
| `approved_manual` | Human approved a direct or composite mapping with evidence and expiry. |
| `needs_manual_review` | Candidate exists, but approval is missing or expired. |
| `unmappable` | No allowed series can represent the node. |
| `rejected_proxy` | Available series is only a proxy and proxy use is not approved. |
| `rejected_stale` | Source or approval expired. |
| `rejected_misleading` | Label direction or economic meaning conflicts with the proposed series. |
| `rejected_malformed` | Required fields are missing or invalid. |
| `rejected_dirty` | Input includes duplicate, conflicting, or previously mutated evidence that cannot be reconciled. |

Allowed `mapping_kind` values:

| Value | Meaning |
| --- | --- |
| `single_series` | One canonical node maps to one series link. |
| `composite_series` | One canonical node maps to two or more links with an explicit formula. |
| `unmappable` | No series link is emitted. |
| `rejected` | A candidate was inspected and rejected with evidence. |

## Field Rules

| Field | Required | Rule |
| --- | --- | --- |
| `canonical_node_id` | yes | Must exist in the PRD 01 node artifact. |
| `canonical_label` | yes | Copied for reviewer readability. The ID remains authoritative. |
| `mapping_result` | yes | One of the allowed values above. |
| `mapping_kind` | yes | Must match the presence or absence of `series_links`. |
| `series_links[].series_id` | approved only | Must exist in `series_catalog`. |
| `series_links[].transform` | approved only | One of `level`, `diff_1d`, `pct_change_1d`, `pct_change_5d`, `pct_change_20d`, `spread`, `custom_formula`. |
| `series_links[].unit` | approved only | Unit after transform, not raw source unit. |
| `series_links[].direction` | approved only | `same`, `inverse`, `component`, or `not_directional`. |
| `series_links[].source_id` | approved only | Must match catalog source. |
| `series_links[].as_of` | approved only | Must be within `expires_at`. |
| `series_links[].provenance_hash` | approved only | Must match catalog entry or transform evidence. |
| `series_links[].suitability` | approved only | Reviewer readable classification. |
| `manual_approval` | approved only | Required for every approved mapping. |
| `manual_approval.expires_at` | approved only | Required so stale mapping cannot pass silently. |
| `proxy_candidates_rejected` | yes | Empty list when no proxy was considered. |
| `unmappable_reason` | no | Required when `mapping_result` is `unmappable` or rejected. |

## Transform And Direction Rules

Transform must follow node semantics.

| Node direction | Preferred transform | Direction rule |
| --- | --- | --- |
| Level up or down | `pct_change_1d`, `pct_change_5d`, or `diff_1d` | `same` if higher series value means the same economic direction. |
| Spread expansion or compression | `spread` or `custom_formula` | Each component uses `component`; formula defines final direction. |
| Event | No default series | Requires owner approval or unmappable. |
| Entity | No default series | Requires owner approval or unmappable. |
| Generic business metric | No default series | Unmappable unless a direct sector or company series exists with provenance. |

Examples:

| Node label | Series link | Direction |
| --- | --- | --- |
| `원달러 환율 상승` | `USD_KRW`, `pct_change_1d` | `same`, because KRW per USD rises when USD/KRW rises. |
| `원화 강세` | `USD_KRW`, `pct_change_1d` | `inverse`, because USD/KRW falls when KRW strengthens. |
| `미국 장단기 금리차 확대` | `US10YT` and `US13WT`, formula `US10YT - US13WT` | Formula output direction is `same`. |
| `한국 금융지주의 대손충당금 확대` | none | Unmappable with current macro catalog. |

## One To Many Mapping

One canonical node can map to multiple series only when the mapping includes an explicit formula and per component provenance.

```json
{
  "canonical_node_id": "cnode_444f9e9f245dcdc58c7e",
  "canonical_label": "미국 장단기 금리차 확대",
  "mapping_result": "approved_manual",
  "mapping_kind": "composite_series",
  "formula": "US10YT - US13WT",
  "series_links": [
    {
      "series_id": "US10YT",
      "transform": "level",
      "unit": "percent",
      "direction": "component",
      "source_id": "finance_data_reader",
      "as_of": "2026-08-06",
      "provenance_hash": "sha256:b3b9a57cce3b7fd6de46bc76abcd90f594b017dd44f6078677611c9650c1939f",
      "suitability": "direct_component",
      "manual_approval": {
        "required": true,
        "approved_by": "macro-domain-owner",
        "approved_at": "2026-08-06T00:00:00+09:00",
        "approval_reason": "Long rate component of term spread.",
        "expires_at": "2026-09-05T00:00:00+09:00"
      }
    },
    {
      "series_id": "US13WT",
      "transform": "level",
      "unit": "percent",
      "direction": "component",
      "source_id": "finance_data_reader",
      "as_of": "2026-08-06",
      "provenance_hash": "sha256:610b49c4bca22cc5fb9b10a1f949703fb2e645d42a60b5eb91437cec01a376b6",
      "suitability": "direct_component",
      "manual_approval": {
        "required": true,
        "approved_by": "macro-domain-owner",
        "approved_at": "2026-08-06T00:00:00+09:00",
        "approval_reason": "Short rate component of term spread.",
        "expires_at": "2026-09-05T00:00:00+09:00"
      }
    }
  ],
  "proxy_candidates_rejected": [],
  "unmappable_reason": null
}
```

Composite rules:

1. Formula inputs must all appear in `series_links`.
2. Formula output unit must be declared by `unit` or top level `formula_unit`.
3. A stale component rejects the full composite mapping.
4. Missing component provenance rejects the full composite mapping.
5. A formula cannot be inferred from label text alone.

## Unmappable Nodes

A node is unmappable when no catalog series measures the same concept with acceptable direction and unit.

```json
{
  "canonical_node_id": "cnode_918374f6c129728a51be",
  "canonical_label": "한국 금융지주의 대손충당금 확대",
  "mapping_result": "unmappable",
  "mapping_kind": "unmappable",
  "series_links": [],
  "proxy_candidates_rejected": [
    {
      "series_id": "GOLD",
      "reason": "Gold price is not a direct measure of Korean financial holding loan loss provisions."
    },
    {
      "series_id": "KOSPI",
      "reason": "Broad equity index is not a direct measure of bank provisioning."
    }
  ],
  "unmappable_reason": "No catalog series measures loan loss provisions for Korean financial holding companies."
}
```

Unmappable output is valid. It protects the verifier from testing a false pair.

## Stale, Proxy, Misleading, Dirty, And Malformed Rejection

| Rejection | Trigger | Required evidence |
| --- | --- | --- |
| `rejected_stale` | `as_of` or approval expiry is older than the consuming run cutoff. | Expired field, run cutoff, and affected series ID. |
| `rejected_proxy` | Candidate series is related but not a direct measurement. | Candidate series, proxy reason, and missing direct source explanation. |
| `rejected_misleading` | Label meaning conflicts with series direction, unit, or economic concept. | Label, proposed link, expected direction, observed conflict. |
| `rejected_dirty` | Input map has duplicate or conflicting links, or was generated by an uncontrolled mutation. | Original records and conflict reason. |
| `rejected_malformed` | JSON shape or field type violates this PRD. | JSON pointer and parse error. |

The current `data/node_series_map.json` can seed dirty evidence, not approved mappings. A flat row such as `"미국 기준금리 인상": "GOLD"` must be rejected as proxy or misleading unless a manual approval record explains why gold is the measurement series.

## Mapping Mutations

Mapping changes are append only. They do not rewrite PRD 01 nodes and do not overwrite raw keyword evidence.

Allowed mutations:

| Mutation | Meaning |
| --- | --- |
| `add_candidate` | A keyword, dictionary, or reviewer proposed a series link. |
| `approve_mapping` | Manual reviewer approved a direct or composite mapping. |
| `reject_mapping` | Candidate was rejected with reason and evidence. |
| `expire_mapping` | Approval reached expiry or source became stale. |
| `mark_unmappable` | Reviewer confirmed no suitable series exists. |

Mutation shape:

```json
{
  "mutation": "reject_mapping",
  "canonical_node_id": "cnode_6f0a5cd90ab4847fd670",
  "candidate_series_id": "GOLD",
  "reason": "rejected_misleading",
  "evidence": {
    "current_flat_map": {
      "node_text": "미국 기준금리 인상",
      "series_id": "GOLD",
      "provenance_hash": "sha256:bf25646fd00ff2f88e2a4faa07461430b70c6ec58872b30d504d6ad874147b7b"
    },
    "expected_direct_series": ["US10YT", "US13WT"],
    "explanation": "The label describes interest rates. Gold is an asset price, not the rate series."
  },
  "mutated_at": "2026-08-06T00:00:00+09:00",
  "mutated_by": "series-mapper.1"
}
```

## Fixtures

### F1 Approved Single Series

Input node:

```json
{
  "canonical_node_id": "cnode_0b6a943c2860b6e61893",
  "canonical_label": "원달러 환율 상승",
  "direction": {
    "kind": "level_change",
    "polarity": "up"
  }
}
```

Expected mapping:

```json
{
  "mapping_result": "approved_manual",
  "mapping_kind": "single_series",
  "series_links": [
    {
      "series_id": "USD_KRW",
      "transform": "pct_change_1d",
      "unit": "percent_change",
      "direction": "same",
      "suitability": "direct_market_series"
    }
  ]
}
```

### F2 Approved One To Many Composite

Input node:

```json
{
  "canonical_node_id": "cnode_444f9e9f245dcdc58c7e",
  "canonical_label": "미국 장단기 금리차 확대",
  "direction": {
    "kind": "level_change",
    "polarity": "up"
  }
}
```

Expected mapping:

```json
{
  "mapping_result": "approved_manual",
  "mapping_kind": "composite_series",
  "formula": "US10YT - US13WT",
  "formula_unit": "percentage_point",
  "series_links": [
    {
      "series_id": "US10YT",
      "transform": "level",
      "direction": "component"
    },
    {
      "series_id": "US13WT",
      "transform": "level",
      "direction": "component"
    }
  ]
}
```

### F3 Unmappable Business Metric

Input node:

```json
{
  "canonical_node_id": "cnode_918374f6c129728a51be",
  "canonical_label": "한국 금융지주의 대손충당금 확대",
  "direction": {
    "kind": "flow_change",
    "polarity": "up"
  }
}
```

Expected mapping:

```json
{
  "mapping_result": "unmappable",
  "mapping_kind": "unmappable",
  "series_links": [],
  "unmappable_reason": "No catalog series measures loan loss provisions for Korean financial holding companies."
}
```

### F4 Stale Approval Rejection

```json
{
  "canonical_node_id": "cnode_d3b3108dbc99b25824db",
  "canonical_label": "국제유가 급등",
  "candidate_series_id": "WTI",
  "mapping_result": "rejected_stale",
  "as_of": "2026-07-01",
  "expires_at": "2026-07-02",
  "run_cutoff": "2026-08-06",
  "unmappable_reason": "Source cutoff and approval expiry are older than the consuming run cutoff."
}
```

### F5 Dirty Flat Map Rejection

```json
{
  "canonical_node_id": "cnode_6f0a5cd90ab4847fd670",
  "canonical_label": "미국 기준금리 인상",
  "candidate_series_id": "GOLD",
  "mapping_result": "rejected_dirty",
  "dirty_input": {
    "source_file": "data/node_series_map.json",
    "node_text": "미국 기준금리 인상",
    "series_id": "GOLD"
  },
  "unmappable_reason": "Flat keyword artifact lacks source, as_of, transform, unit, approval, and economic suitability evidence."
}
```

### F6 Misleading Proxy Rejection

```json
{
  "canonical_node_id": "cnode_6f0a5cd90ab4847fd670",
  "canonical_label": "미국 기준금리 인상",
  "candidate_series_id": "GOLD",
  "mapping_result": "rejected_misleading",
  "expected_direct_series": ["US10YT", "US13WT"],
  "unmappable_reason": "Interest rate label was linked to gold price. The proposed series measures a different asset."
}
```

### F7 Malformed Mapping Rejection

```json
{
  "canonical_node_id": "cnode_0b6a943c2860b6e61893",
  "canonical_label": "원달러 환율 상승",
  "mapping_result": "rejected_malformed",
  "json_pointer": "/mappings/0/series_links/0/as_of",
  "parse_error": "Missing required as_of for approved mapping."
}
```

## Read, JSON, And Mutation QA

| QA area | Fixture | Required result |
| --- | --- | --- |
| Read QA | PRD 01 artifact exists and has `schema_version = causal-node-canonicalization.1`. | Mapper reads nodes by `canonical_node_id`. |
| Read QA | `data/node_series_map.json` exists as flat legacy evidence. | Mapper may import candidates, but every candidate requires review. |
| Read QA | Series catalog `as_of` is older than `expires_at`. | Candidate is rejected as stale. |
| JSON QA | Approved mapping misses `manual_approval`. | Rejected as malformed. |
| JSON QA | `series_id` is not in catalog. | Rejected as malformed. |
| JSON QA | `mapping_kind = single_series` has two links. | Rejected as malformed. |
| Mutation QA | Keyword hit creates `add_candidate`. | No approved mapping appears until `approve_mapping`. |
| Mutation QA | Proxy is rejected. | `reject_mapping` records candidate series and reason. |
| Mutation QA | Unmappable node is reviewed. | `mark_unmappable` records reason and no series links. |
| Mutation QA | Manual approval expires. | `expire_mapping` records prior approval and cutoff. |

## Acceptance Criteria

1. The PRD defines `causal-series-mapping.1`.
2. The mapping key is `canonical_node_id`, not legacy node text.
3. Approved mappings require transform, unit, direction, source, as_of, provenance hash, suitability, manual approval, and expiry.
4. One to many mapping requires an explicit formula and per component provenance.
5. Unmappable nodes are valid outputs and keep rejection evidence.
6. Stale, proxy, dirty, misleading, and malformed inputs are rejected with evidence.
7. Keyword matching can create candidates only and is never enough for approval.
8. Fixtures cover read, JSON, and mutation QA.
