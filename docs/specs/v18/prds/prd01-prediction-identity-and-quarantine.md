# PRD: v18 PRD 01 Prediction Identity And Quarantine
> **상태**: 📋 구현 예정
> 상위 SPEC: [v18 SPEC](../SPEC.md)

## 의존성

- [v16 SPEC](../../v16/SPEC.md)의 `RuntimeIdentity`, calendar·price lineage
- [v17 SPEC](../../v17/SPEC.md)의 SQLite transaction과 migration contract
- v18 local normalized recommendation·legacy snapshot fixtures

## 목표

Advisory recommendation을 immutable canonical prediction으로 등록하고 identity가 불완전한 legacy snapshot은 승격 불가능한 quarantine ledger에 분리한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v18/models.py` | `PredictionRecord`, `LegacyQuarantineRecord`, typed failure |
| `src/v18/predictions.py` | Strict parse, prediction identity와 semantic key |
| `src/v18/quarantine.py` | Legacy provenance·rejection record 생성 |
| `src/v18/repository.py` | Immutable row/event와 duplicate transaction |
| `src/v18/migrations/002_measurement.sql` | Global head `001`→`002`; prediction·quarantine·idempotency table |

## Prediction Schema

Schema `v18.prediction.1`은 recommendation ID, official prediction session, horizon, action, adjusted reference price, perspective scores, source payload hash, explicit `recorded_as_of`를 요구한다. Namespace와 lineage는 market, currency, account, arm, symbol, runtime/config/source-policy/calendar/price-adjustment version을 모두 가진다.

Unknown field, float money, non-canonical decimal, local timestamp, `KR/USD`, `US/KRW`, 빈 account·arm·symbol은 등록 전에 거부한다. `prediction_id`는 receipt metadata를 제외한 strict identity body의 canonical SHA-256다.

## Immutable 등록 계약

등록 transaction은 semantic key 조회, canonical request hash 비교, identity 검증, `prediction.registered` measurement event append, `predictions` row insert, hash 확인을 함께 commit한다.

| Existing state | Incoming request | Result |
| --- | --- | --- |
| 없음 | valid body | `REGISTERED`, row/event 1개 |
| 같은 semantic key | 같은 request hash | stored ID/result, write 0건 |
| 같은 semantic key | 다른 request hash | `PREDICTION_IDENTITY_CONFLICT`, write 0건 |
| 같은 recommendation ID | 다른 namespace/body | `PREDICTION_IDENTITY_CONFLICT`, write 0건 |

Prediction row와 registration event는 update/delete API를 갖지 않는다. Correction은 새 recommendation ID와 prediction ID로만 가능하다.

## Legacy Quarantine 계약

Legacy snapshot은 source bytes hash, root-relative source label, observed schema hint, rejection code 목록, caller-supplied `as_of`로 `v18.legacy-quarantine.1` record를 만든다. Content에서 누락된 market, account, arm, horizon, version 또는 cutoff를 추정하지 않는다.

Quarantine ID는 provenance body hash이며 duplicate bytes/provenance는 no-op이다. Quarantined record는 terminal이고 prediction ID를 부여받지 않으며 evaluate, cohort, candidate foreign key가 참조할 수 없다.

## 상태와 Failure 계약

| Code | 조건 | Write |
| --- | --- | ---: |
| `PREDICTION_SCHEMA_INVALID` | 누락·unknown field·canonical type 위반 | 0 |
| `PREDICTION_IDENTITY_CONFLICT` | semantic identity 재사용과 다른 body | 0 |
| `PREDICTION_NAMESPACE_INVALID` | market/currency/account/arm 조합 위반 | 0 |
| `PREDICTION_LINEAGE_UNKNOWN` | unknown runtime/config/policy/calendar/price version | 0 |
| `LEGACY_SNAPSHOT_QUARANTINED` | legacy input을 prediction 등록 API에 전달 | quarantine만 |
| `INELIGIBLE_QUARANTINE_RECORD` | quarantine record를 평가·cohort로 승격 | 0 |
| `IMMUTABLE_PREDICTION` | registered body update/delete 시도 | 0 |

## CLI

```bash
uv run python -m src.v18.cli register-prediction --input prediction.json --database data/paper/v17/paper.sqlite3
uv run python -m src.v18.cli quarantine-legacy --input legacy.json --as-of 2026-01-05T21:00:00Z --database data/paper/v17/paper.sqlite3
uv run python -m src.v18.cli prd01-acceptance
```

## Acceptance와 Mutation

| Probe | Mutation | Required result |
| --- | --- | --- |
| `canonical_prediction` | valid KR·US prediction 등록 | deterministic IDs와 `REGISTERED` |
| `duplicate_retry` | 같은 request 10회 | row/event count 불변 |
| `identity_conflict` | action, horizon 또는 symbol 변경 | conflict, state hash 불변 |
| `namespace_swap` | KR/USD 또는 account/arm 교차 | namespace failure |
| `legacy_direct_import` | identity 누락 snapshot 등록 | quarantine, prediction 0개 |
| `quarantine_promotion` | quarantine ID를 prediction처럼 참조 | ineligible failure |
| `prediction_update` | SQL/API body 변경 시도 | immutable failure 또는 reconciliation failure |

## 완료 조건

- 모든 accepted prediction이 완전한 immutable identity와 source lineage를 가진다.
- Duplicate retry와 conflict가 transaction 표면에서 명확히 구분된다.
- Legacy snapshot은 quarantine 밖으로 이동하지 않으며 outcome 입력이 되지 않는다.
- Account projection과 `data/portfolio.json`을 읽거나 쓰지 않는다.

## 비목표

- Legacy field 추론·migration·repair
- Outcome maturity·return 계산
- Weight candidate 또는 active policy mutation
- Recommendation producer adapter
