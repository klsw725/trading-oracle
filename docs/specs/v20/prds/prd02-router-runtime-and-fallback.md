# PRD: v20 PRD 02 V13 Router Runtime And Fallback
> **상태**: 📋 구현 예정
> 상위 SPEC: [v20 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-strategy-runtime-adapters.md)의 actual V12 execution-feasible candidate result와 decision mapping
- [v13 SPEC](../../v13/SPEC.md), [Router Scoring PRD](../../v13/prds/prd01-router-scoring-policy.md), [Codex Schema PRD](../../v13/prds/prd02-codex-context-schema.md), [Fallback/Replay PRD](../../v13/prds/prd03-switch-fallback-replay.md)
- [v14 SPEC](../../v14/SPEC.md)의 frozen router hypothesis/verdict/manifest
- [v15 SPEC](../../v15/SPEC.md)의 router shadow/challenger와 LLM operating state
- [v16 SPEC](../../v16/SPEC.md)의 point-in-time runtime/data identity
- [v17 SPEC](../../v17/SPEC.md)의 SQLite event/idempotency/replay contract
- [v19 SPEC](../../v19/SPEC.md)의 plan cutoff와 neutral envelope intake

## 목표

Actual v12 candidate batch를 실제 v13 mixed-router code path에 전달하고, recorded raw Codex response를 validate·score·fallback·replay하며 market/session별 circuit state와 quant-only 결과를 SQLite에 영속화한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v20/router_models.py` | Router request/result/call/circuit strict schemas |
| `src/v20/router_adapter.py` | V13 scoring·validation·policy·fallback typed orchestration |
| `src/v20/router_provider.py` | Live/recorded provider port와 replay no-call boundary |
| `src/v20/router_state.py` | Call event, circuit reducer와 next-session reset |
| `src/v20/migrations/005_router_runtime.sql` | Global head `004`→`005`; router call/circuit event/projection tables |

PRD 02는 v13 business rule을 복사한 별도 router engine을 만들지 않는다. V20 adapter는 typed input/output translation, transaction과 durable state만 소유한다.

## Router Request Schema

`v20.router-adapter-request.1`:

| Field | Contract |
| --- | --- |
| `invocation` | producer `V13_ROUTER`의 runtime invocation |
| `plan_id` | target v19 router arm plan |
| `candidate_batch_hash` | same market/cutoff의 complete v12 candidate inventory |
| `candidates` | execution-feasible candidate ordered tuple |
| `router_policy` | v13 허용 6개 중 frozen policy와 hash |
| identities | model, prompt, output schema, context corpus, v14 manifest |
| `recorded_response_ref` | acceptance/replay raw response bytes hash 또는 null |
| `circuit_head` | market/session durable projection hash |

Candidate를 budget에 맞추려고 자르거나 symbol별 provider call로 분할하지 않는다. Overflow는 v13 market·cutoff quant-only path다.

## Router Result Schema

`v20.router-adapter-result.1`:

| Field | Contract |
| --- | --- |
| `invocation_id` | request identity |
| `mode` | `MIXED` 또는 `QUANT_ONLY` |
| `call_record_id` | attempted/skipped provider call event |
| `validations` | candidate/item/envelope validation results |
| `rankings` | v13 deterministic/LLM percentile와 composite evidence |
| `decisions` | symbol별 selected candidate 또는 `NO_TRADE` |
| `fallbacks` | scope와 v13 reason code |
| `circuit_before/after` | projection hashes와 state |
| `raw_response_hash` | stored bytes hash, envelope로 전달하지 않음 |
| `result_hash` | strict canonical body hash |

`confidence`는 관측용이며 composite를 바꾸지 않는다. V13이 금지한 ticker, candidate, strategy, quantity, price와 order instruction을 result schema가 새로 허용하지 않는다.

## Actual V13 Call Path

Adapter는 v13의 scoring, policy, schema validation, switch, fallback, circuit breaker와 replay public services를 호출한다. Expected selection이나 fallback을 fixture field에서 읽지 않는다. Percentile, composite, veto, fallback, selection과 circuit transition은 `SOURCE_OUTPUT`; v20 invocation, namespace와 v19 decision mapping만 `V20_MAPPING` provenance다.

```text
actual v12 execution-feasible candidates
-> v13 hard eligibility and market batch
-> deterministic percentile
-> recorded provider response or provider port
-> v13 strict validation and verified veto
-> market LLM percentile and 80:20 composite
-> v13 NO_TRADE/selection total order
-> v20 result and v19 decision mapping
```

Mixed score, midrank, tie order, allowed `NO_TRADE` combinations, switch hold/gap, timeout과 fallback 원인은 전부 v13을 호출해 얻는다. V20에는 duplicate algorithm과 configurable override가 없다.

## Recorded Response와 Replay

Acceptance provider는 immutable request identity에 exact recorded raw response bytes를 반환한다. Recorded fixture는 response body와 source hash만 소유하고 parsed item, expected score, selected candidate, fallback 또는 circuit result를 소유하지 않는다.

PRD 02 acceptance는 v13에 등록된 최소점수 3개와 최소격차 2개의 6개 policy 조합을 모두 frozen request로 실제 실행한다. V20이 조합을 재정의하지 않으며 production invocation은 manifest가 고정한 한 조합만 사용한다.

First execution은 raw response 저장→v13 parse/validation→result/circuit commit 순서다. Replay는 stored prompt/model/schema/context/raw response/validation refs를 읽고 v13 replay path를 실행하며 provider port call count가 0이어야 한다.

Recorded request identity가 다르거나 raw bytes hash가 drift하면 `ROUTER_RECORDED_RESPONSE_MISMATCH`다. 현재 model 재호출로 과거 result를 복구하지 않는다.

## Fallback 범위

| V13 condition | Required scope/result |
| --- | --- |
| candidate item invalid 또는 abstain | 해당 symbol 전체 quant-only |
| verified hard veto | 해당 candidate 제거 뒤 percentile 재계산 |
| duplicate/unknown ID, cutoff/prompt/batch mismatch | 해당 market·cutoff quant-only |
| timeout/provider/auth failure | 해당 market·cutoff quant-only, retry 0 |
| input budget overflow | candidate truncate 없이 market·cutoff quant-only |
| model/prompt/schema/artifact identity failure | market·cutoff quant-only 또는 v15 integrity incident 분류 |

Quant-only score는 deterministic percentile 자체이며 `0.80`을 곱하지 않는다. Same cutoff의 KR fallback이 US result/circuit을 바꾸지 않는다.

Manifest mismatch는 단순 fallback으로 끝내지 않고 PRD 03의 operation kill input으로 전달한다. V20 adapter가 incident scope를 축소하지 않는다.

## Circuit State

Circuit event schema `v20.router-circuit-event.1`은 market, session, cutoff, call outcome, fallback reason, prior event hash와 event hash를 가진다. Projection은 v13의 연속 failure와 최근 call history를 replay한다.

- 3회 연속 failure 또는 최근 20회 중 20% 이상 failure에서 해당 market의 남은 session은 quant-only다.
- Open 뒤 같은 session provider call은 0회다.
- 다음 official session에 해당 market의 breaker, consecutive failures와 call history를 reset한다.
- Reset은 v16 official calendar session identity로 수행하고 wall clock/date guess를 사용하지 않는다.
- Circuit open은 kill/position liquidation이 아니며 v19 paper execution은 quant-only decisions로 계속된다.

V20은 threshold, window, reset timing, half-open probe와 retry를 추가하지 않는다.

## Router Shadow와 Challenger

Lifecycle이 `router_shadow`이면 router result와 virtual decision/economics를 독립 shadow namespace에 기록하되 external primary action을 만들지 않는다. `router_challenger`이면 comparison epoch에 binding된 router mirror plan으로 v19 paper execution을 수행한다.

`router_primary` 전이는 PRD 03의 actual mirror winner evidence만 허용한다. Router score가 높거나 circuit failure가 적다는 이유만으로 primary가 되지 않는다.

## Decision Mapping과 Idempotency

PRD 01의 `v20.decision-mapping.1`을 사용한다. Selected candidate identity, v13 selection evidence, fallback mode, policy/model/prompt/schema hash와 circuit head를 source refs에 binding한다.

Semantic key는 market/account/arm/session/plan/cutoff, complete candidate batch, router policy, model/prompt/schema/context와 circuit-before hash를 포함한다. Exact retry는 stored call/result/mapping을 반환하고 provider를 호출하지 않는다. Same key response bytes나 candidate batch 변경은 conflict다.

## Failure 계약

| Code | 조건 | Mutation |
| --- | --- | ---: |
| `ROUTER_CANDIDATE_BATCH_INVALID` | incomplete/cross-market/cross-cutoff batch | 0 |
| `ROUTER_POLICY_UNREGISTERED` | v13 6개 밖 threshold | 0 |
| `ROUTER_IDENTITY_MISMATCH` | model/prompt/schema/context/manifest drift | fail closed |
| `ROUTER_RECORDED_RESPONSE_MISMATCH` | recorded request/raw hash mismatch | 0 |
| `ROUTER_REPLAY_PROVIDER_CALL` | replay가 provider port 호출 | 0 |
| `ROUTER_CIRCUIT_STATE_MISMATCH` | event/projection/session 불일치 | 0 |
| `ROUTER_CIRCUIT_OPEN` | same-session provider invocation 시도 | call 0, quant-only |
| `ADAPTER_IDEMPOTENCY_CONFLICT` | 같은 semantic key의 다른 candidate/response | 0 |

## CLI

```bash
uv run python -m src.v20.cli run-router --plan-id sha256:... --response recorded-codex.json --database data/paper/v17/paper.sqlite3
uv run python -m src.v20.cli prd02-acceptance
```

V20 CLI에는 credential, vendor SDK 또는 network provider 선택지가 없다. Runtime composition은 typed provider port를 주입할 수 있지만 canonical/PRD acceptance와 `run-router` command는 caller-supplied recorded response만 허용한다.

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `recorded_mixed_route` | valid raw response | actual v13 mixed result |
| `all_registered_router_policies` | v13 allowed grid 순회 | 6 frozen policy executions |
| `router_recorded_replay_recall` | replay provider trap | call 0, same result hash |
| `router_partial_item_bad` | one item score/schema invalid | that symbol quant-only |
| `router_envelope_bad` | duplicate/cutoff/hash mismatch | market/cutoff quant-only |
| `router_overflow_truncation` | candidate count exceeds budget | truncate 0, quant-only |
| `router_unproven_veto` | source artifact 제거 | veto ignored per v13 |
| `router_quant_weight_drift` | quant score에 0.80 적용 | scoring failure |
| `router_circuit_open` | v13 failure boundary 도달 | remaining session calls 0 |
| `router_circuit_same_session_reset` | same-session reset 시도 | state failure |
| `router_circuit_cross_market` | KR events로 US projection 변경 | isolation failure |
| `router_next_session_reset` | exact next official session | mixed mode eligible |
| `router_retry_response_drift` | same key raw bytes 변경 | conflict, DB pre-hash |

## 완료 조건

- Recorded raw response가 실제 v13 validation/scoring/fallback code를 통과한다.
- Replay는 provider를 재호출하지 않고 동일 result/circuit hashes를 만든다.
- Symbol/market fallback scope와 circuit reset이 v13과 정확히 같다.
- Router output이 v19 neutral envelope로 deterministic하게 mapping된다.

## 비목표

- 새 router weight, threshold, retry, fallback 또는 circuit policy
- 실제 credential/network integration acceptance
- Router qualification, winner, promotion와 rollback 판정
- Human approval 발급·철회
- V18 adaptive policy activation
