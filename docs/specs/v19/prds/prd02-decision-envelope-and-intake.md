# PRD: v19 PRD 02 Decision Envelope And Intake
> **상태**: 📋 구현 예정
> 상위 SPEC: [v19 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-session-plan-and-lease.md)의 active run, lease와 decision cutoff
- [v16 SPEC](../../v16/SPEC.md)의 runtime/data identity
- v19 local producer-neutral decision fixtures

## 목표

어떤 producer도 동일하게 제출할 수 있는 strict `DecisionEnvelope`와 all-or-nothing batch intake를 정의하고 producer-specific adapter 없이 immutable receipt를 만든다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v19/decision_models.py` | Envelope·batch·receipt strict schemas |
| `src/v19/decisions.py` | Canonical envelope ID와 lineage validation |
| `src/v19/intake.py` | Lease/cutoff/batch validation과 atomic intake |
| `src/v19/receipts.py` | Semantic duplicate/conflict와 immutable result |
| `src/v19/canonical.py` | Canonical JSON bytes와 SHA-256 |

## DecisionEnvelope Schema

`v19.decision-envelope.1`의 필수 필드는 envelope/decision/plan IDs, namespace/session, symbol, sector, action, target quantity, reference price, cutoff, watermark, decision-ready time, deterministic score, v11-compatible gate inputs, source evidence hashes, producer contract name/version이다.

`BUY`, `SELL`, `NO_TRADE`만 허용한다. `NO_TRADE` quantity는 0이고 trade action은 positive integer quantity와 minor-unit price를 요구한다. Float, NaN, local timestamp, unknown field와 raw producer payload는 거부한다.

Producer label은 provenance일 뿐 import/dispatch key가 아니다. Envelope body의 의미는 producer와 무관하게 동일하다.

## Batch Identity

`v19.decision-batch.1`은 plan ID, namespace/session, explicit batch cutoff, ordered envelopes와 batch hash를 가진다. Canonical order는 market, symbol, decision ID다. Duplicate decision/envelope ID와 같은 symbol의 상충 trade action은 batch failure다.

빈 batch는 versioned plan이 명시적으로 허용할 때만 valid no-trade session이다. Partial success와 best-effort filtering은 없다.

## Intake 순서

1. Current run/lease generation과 `RUNNING` state 확인
2. Plan, namespace, session과 runtime/config identity 확인
3. Decision cutoff, watermark와 ready time 확인
4. Envelope·batch canonical hash와 duplicate/conflict 확인
5. Batch completeness와 deterministic order 확인
6. 모든 immutable receipts와 `intake.sealed` step을 한 transaction으로 commit

Accepted trade는 `ACCEPTED_FOR_RISK`, valid no-trade는 `RECORDED_NO_TRADE`다. Receipt schema `v19.intake-receipt.1`은 decision/envelope/batch IDs, result, evidence hash와 semantic key를 가진다.

## Idempotency와 Failure 계약

| Code/result | 조건 | Write |
| --- | --- | ---: |
| stored receipt | 같은 batch semantic key와 request hash | 0 |
| `DECISION_IDENTITY_CONFLICT` | 같은 decision/envelope identity의 다른 body | 0 |
| `DECISION_NAMESPACE_MISMATCH` | plan과 market/currency/account/arm/session 다름 | 0 |
| `DECISION_STALE` | watermark 또는 readiness가 cutoff 뒤 | 0 |
| `DECISION_LINEAGE_MISMATCH` | runtime/config/source evidence 불일치 | 0 |
| `DECISION_BATCH_INVALID` | duplicate, conflict, order, completeness 위반 | 0 |
| `UNSUPPORTED_PRODUCER_INPUT` | envelope가 아닌 v12/v13 artifact 직접 전달 | 0 |
| `LEASE_REQUIRED` | current run lease 없이 intake | 0 |

한 envelope 실패는 batch 전체를 rollback한다. Unknown producer version을 자동 mapping하거나 legacy field를 추정하지 않는다.

## Producer Boundary

V19 public API는 typed `DecisionEnvelope` 또는 strict schema JSON bytes만 받는다. `src.v12`, `src.v13`, v14/v15 artifacts를 import하는 adapter module, duck-typing path와 producer-specific conditional은 없다. V20이 이 boundary 밖에서 실제 runtime output을 변환한다.

## CLI

```bash
uv run python -m src.v19.cli run-session --plan-id sha256:... --decisions decision-batch.json --as-of 2026-01-05T05:00:00Z --database data/paper/v17/paper.sqlite3
uv run python -m src.v19.cli prd02-acceptance
```

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `neutral_producers` | 서로 다른 producer label의 같은 normalized meaning | 동일 intake semantics |
| `batch_shuffle` | envelope input order 변경 | 같은 canonical batch/hash |
| `batch_atomicity` | 마지막 envelope invalid | receipt 0개 |
| `duplicate_retry` | reopen 전후 batch 반복 | stored receipts, row 불변 |
| `identity_conflict` | same ID action/quantity 변경 | conflict, DB hash 불변 |
| `stale_or_cross_namespace` | cutoff/watermark/namespace 변경 | fail closed |
| `direct_producer_artifact` | v12/v13-shaped JSON 전달 | unsupported input |

## 완료 조건

- Producer 종류와 무관한 단일 strict envelope contract가 존재한다.
- Batch intake가 cutoff·namespace·lineage를 검증하고 all-or-nothing commit한다.
- Retry는 no-op이고 의미 충돌은 state 불변 실패다.
- V12/V13 adapter나 multi-arm routing을 import·구현하지 않는다.

## 비목표

- V12 candidate bundle, V13 router, V14/V15 artifact adapter
- LLM, strategy 또는 recommendation 생성
- Multi-arm selection·promotion
- Risk sizing, reservation, intent와 fill
