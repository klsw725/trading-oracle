# PRD: v18 PRD 04 Measurement Acceptance
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v18 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-prediction-identity-and-quarantine.md)
- [PRD 02](prd02-horizon-outcome-evaluation.md)
- [PRD 03](prd03-adaptive-policy-candidates.md)
- v16 canonical calendar/price identity, v17 temp SQLite와 v18 local immutable fixtures

## 목표

Immutable prediction부터 exact-session outcome와 bounded inactive candidate까지 leakage·immaturity·duplicate·reevaluation mutation을 임시 SQLite의 standalone offline acceptance로 증명한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v18/acceptance.py` | Version scenario, exact mutation inventory와 report assembly |
| `src/v18/faults.py` | Registration·evaluation·candidate transaction fault injection |
| `src/v18/boundaries.py` | Network·portfolio·account projection·later import guard |
| `src/v18/fixtures.py` | Prediction·calendar·price·cohort fixture inventory |
| `src/v18/cli.py` | PRD 04와 version acceptance entrypoint |

## Acceptance Database

각 scenario는 OS temp root의 독립 v17 global head `001` SQLite fixture에서 시작해 v18 global migration `002`를 적용하고 head `002`를 확인한다. `schema_migrations`와 `PRAGMA user_version`은 같은 global head를 가리켜야 한다. Scenario 간 database와 in-memory cache를 공유하지 않는다. Fixture inventory는 상대경로와 SHA-256를 고정하고 mutation은 temp copy에만 적용한다.

Acceptance는 v16/v17 CLI를 재실행하지 않고 public typed fixture를 직접 소비한다. `src.v19` directory가 없어도 import·runtime error 없이 완료되어야 한다.

## 필수 시나리오

- KR/US, account, arm별 prediction 등록과 duplicate retry/conflict
- Identity가 완전하지 않은 legacy snapshot quarantine과 승격 차단
- Weekend, holiday, early close를 포함한 N=1·N>1 exact target
- Target close 직전/정각 `as_of`, missing·duplicate·wrong-version adjusted price
- BUY/HOLD/SELL neutral-band outcome와 integer rounding edge
- Eligible/ineligible cohort의 inclusion·exclusion evidence와 duplicate 차단
- Deterministic bounded candidate, effective session과 full state transition/rollback
- Registration, evaluation, cohort freeze, candidate transition 각 commit point crash rollback
- Process-equivalent reopen 뒤 duplicate result, state와 hash 일치

## 정확한 Mutation Inventory

| ID | Expected code/result | State invariant |
| --- | --- | --- |
| `prediction_duplicate_retry` | stored result | row/event count 불변 |
| `prediction_identity_conflict` | `PREDICTION_IDENTITY_CONFLICT` | DB hash 불변 |
| `legacy_missing_identity` | `LEGACY_SNAPSHOT_QUARANTINED` | prediction 0개 |
| `quarantine_promotion` | `INELIGIBLE_QUARANTINE_RECORD` | outcome/cohort 0개 |
| `weekend_horizon` | exact target 유지 | wrong target kill |
| `early_close_horizon` | exact target 유지 | wrong target kill |
| `immature_as_of` | `OUTCOME_IMMATURE` | evaluation 0개 |
| `calendar_version_drift` | `CALENDAR_IDENTITY_MISMATCH` | state 불변 |
| `raw_price_substitution` | `PRICE_ADJUSTMENT_MISMATCH` | state 불변 |
| `missing_target_price` | `TARGET_PRICE_MISSING` | state 불변 |
| `duplicate_target_price` | `TARGET_PRICE_AMBIGUOUS` | state 불변 |
| `cross_market_price` | `NAMESPACE_MISMATCH` | state 불변 |
| `immature_cohort_member` | `COHORT_MEMBER_INELIGIBLE` | member 미포함 |
| `duplicate_cohort_member` | `COHORT_DUPLICATE_MEMBER` | manifest 미생성 |
| `leakage_future_input` | `MEASUREMENT_LEAKAGE` | candidate 미생성 |
| `candidate_bound_escape` | `CANDIDATE_WEIGHT_BOUNDS` | candidate 미생성 |
| `candidate_effective_past` | `CANDIDATE_EFFECTIVE_SESSION_INVALID` | state 불변 |
| `active_weight_overwrite` | `ACTIVE_POLICY_MUTATION_FORBIDDEN` | config hash 불변 |
| `evaluation_payload_conflict` | `EVALUATION_IMMUTABLE` | outcome hash 불변 |
| `rollback_deletes_history` | `CANDIDATE_HISTORY_IMMUTABLE` | full history 유지 |
| `portfolio_mutation` | mutation 0건 | 존재·bytes·hash 불변 |
| `network_attempt` | call 0건 | acceptance PASS |
| `later_version_import` | import 0건 | acceptance PASS |

Mutation ID set은 [v18 SPEC](../SPEC.md)의 Failure와 Mutation 표와 정확히 같아야 한다. 누락, duplicate, skip, unexpected success는 acceptance failure다.

## Transaction Fault 계약

Fault는 semantic-key insert, immutable row insert, event append, state projection, final invariant 직후의 명명된 checkpoint에서 deterministic exception을 낸다. Connection close/reopen 뒤 pre-command table counts와 canonical hashes가 모두 같아야 한다. Timing, signal, random kill을 사용하지 않는다.

## Hard Boundary

- Socket, DNS, HTTP 호출을 trap하고 0건을 요구한다.
- `src.v19` 이후 import를 trap하고 0건을 요구한다.
- `data/portfolio.json`과 tracked config의 시작·종료 존재·bytes·hash가 같다.
- v17 account balances, positions, reservations의 시작·종료 hash가 같다.
- Broker, credential, live destination와 active-policy writer 객체 생성은 0건이다.

## Report 계약

Schema `v18.acceptance.1`은 version, status, prediction/outcome/candidate schema versions, checks, mutations, boundaries, table hashes와 report hash를 가진다. Array는 ID 오름차순이고 temp path, wall-clock timestamp, SQLite rowid와 random value를 포함하지 않는다.

기대한 fail-closed는 mutation `PASS`다. 모든 check·mutation·boundary가 PASS이고 fixture와 temp cleanup이 확인될 때만 top-level PASS와 exit 0이다.

## CLI

```bash
uv run python -m src.v18.cli prd04-acceptance
uv run python -m src.v18.cli acceptance
```

## Acceptance Criteria

- Canonical command를 두 번 실행한 stdout bytes가 같다.
- 23개 mutation ID가 정확한 expected code/result로 kill된다.
- Crash checkpoint마다 reopen 후 pre-command state가 보존된다.
- Prediction, outcome, cohort와 candidate hash가 fixture로 재현된다.
- Network, later import, portfolio, account projection, active policy mutation이 모두 0건이다.
- Temp cleanup 뒤 tracked worktree와 fixture inventory hash가 같다.

## 완료 조건

- `uv run python -m src.v18.cli acceptance`가 offline fixture만으로 exit 0이다.
- v19 이후 producer·execution module 없이 전체 measurement contract를 실제 SQLite 표면에서 검증한다.
- Advisory horizon outcome과 inactive policy candidate까지만 만들고 paper P&L·promotion은 만들지 않는다.

## 비목표

- Live market/vendor smoke test
- Paper order/fill/account return acceptance
- Candidate activation, strategy 또는 multi-arm promotion
- 실제 power-loss·multi-process·multi-host certification
