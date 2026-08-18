# PRD: v19 PRD 04 Session Close And Restart Acceptance
> **상태**: 📋 구현 예정
> 상위 SPEC: [v19 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-session-plan-and-lease.md)
- [PRD 02](prd02-decision-envelope-and-intake.md)
- [PRD 03](prd03-risk-intent-and-paper-fill.md)
- v16 calendar/mark fixture, v17 temp paper account, v18 global migration `002` asset과 v19 local immutable fixtures

## 목표

Marks, session close, v17/v19 reconciliation, run outcome registration과 every-step restart를 실행해 decision-to-paper pipeline의 standalone offline acceptance를 증명한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v19/marks.py` | Strict official close mark set과 hash |
| `src/v19/session_close.py` | Close precondition, close record와 run outcome |
| `src/v19/reconciliation.py` | Plan부터 v17 account projection까지 reference/economics 검증 |
| `src/v19/restart.py` | SQLite durable heads와 step receipt 기반 resume |
| `src/v19/acceptance.py` | Exact mutation inventory와 report assembly |
| `src/v19/boundaries.py` | Network·live·portfolio·later import guard |
| `src/v19/cli.py` | PRD 04와 version acceptance entrypoint |

## Close Mark 계약

`v19.close-mark.1`은 plan/session namespace, symbol, official close, positive adjusted minor-unit price, currency, price version와 source hash를 가진다. Opening position, filled position과 close policy가 요구하는 모든 symbol에 exact-session mark 하나가 있어야 한다.

Missing, duplicate, stale, cross-session, wrong market/currency/version mark는 close를 막는다. Nearest prior mark, fill price 또는 zero로 fallback하지 않는다.

## Close Preconditions와 Record

Close는 current lease, `AWAITING_CLOSE`, sealed intake, 모든 trade decision terminal, execution cutoff 경과, complete marks, v17 reconciliation PASS를 요구한다.

`v19.session-close.1`은 opening/closing account hash, mark set hash, decision/risk/intent/fill counts, v17 event/projection head, v19 execution head, close policy와 explicit `as_of`를 가진다. Exact retry는 stored close를 반환하고 다른 body는 `SESSION_CLOSE_IMMUTABLE`이다.

## Reconciliation 계약

다음 graph를 양방향으로 검증한다.

1. Plan↔run↔lease generation↔step receipts
2. Intake batch↔every decision receipt
3. Trade decision↔risk result↔reservation↔intent↔fill
4. Fill economics↔v17 cash/position/reservation events↔projection
5. Held/filled symbols↔mark set↔close record
6. Close record↔reconciliation receipt↔run outcome

Orphan, duplicate, broken hash/reference, quantity/cash mismatch와 stale checkpoint는 `SESSION_RECONCILIATION_FAILED`다. Auto repair, delete, projection overwrite와 JSON restore는 없다. Failure 뒤 close/outcome mutation을 차단한다.

## Run Outcome 계약

`v19.run-outcome.1`은 run ID, `COMPLETED|MISSED|FAILED`, step receipt hashes, accepted/blocked/no-trade/filled counts, close/reconciliation hashes, terminal reason과 explicit `as_of`를 가진다. Run terminal transition과 outcome insert는 한 transaction이다.

Outcome는 session operation result다. Recommendation의 N-session correctness, paper P&L ranking, adaptive weight와 strategy/arm promotion을 계산하거나 v18 table에 등록하지 않는다.

## Restart E2E

Baseline은 uninterrupted plan→intake→risk/fill→marks→close→outcome run이다. 별도 scenario는 각 named step commit 직후 connection을 닫고 새 owner/as-of로 reopen한다. Active lease는 `LEASE_HELD`, expired lease는 generation takeover 후 last receipt 다음부터 resume한다.

각 restart scenario의 terminal account projection, v17 event head, v19 execution head, close, outcome와 report hashes가 baseline과 같아야 한다. Decision, reservation, intent, fill과 account economic event count도 같다.

## 정확한 Mutation Inventory

| ID | Expected code/result | State invariant |
| --- | --- | --- |
| `session_plan_duplicate` | stored plan | row count 불변 |
| `session_plan_conflict` | `SESSION_PLAN_CONFLICT` | plan hash 불변 |
| `lease_contention` | one owner/`LEASE_HELD` | active lease 1개 |
| `stale_lease_generation` | `STALE_LEASE` | step write 0건 |
| `decision_cutoff_missed` | policy terminal result | execution 0건 |
| `execution_cutoff_missed` | `EXECUTION_CUTOFF_MISSED` | intent 0건 |
| `resume_completed_step` | stored receipt | duplicates 0건 |
| `decision_duplicate_retry` | stored receipts | rows 불변 |
| `decision_identity_conflict` | `DECISION_IDENTITY_CONFLICT` | batch rollback |
| `cross_namespace_decision` | `DECISION_NAMESPACE_MISMATCH` | batch rollback |
| `stale_decision_watermark` | `DECISION_STALE` | intake 0건 |
| `producer_adapter_attempt` | `UNSUPPORTED_PRODUCER_INPUT` | imports/writes 0건 |
| `risk_gate_bypass` | `RISK_NOT_ACCEPTED` | account 불변 |
| `reservation_overcommit` | blocked/no reservation | account 불변 |
| `fill_policy_drift` | `FILL_POLICY_MISMATCH` | intent/fill 불변 |
| `execution_duplicate_retry` | stored fill | economics 불변 |
| `execution_payload_conflict` | `EXECUTION_IDEMPOTENCY_CONFLICT` | economics 불변 |
| `crash_after_reservation` | deterministic rollback | v17/v19 pre-hash |
| `crash_after_fill` | deterministic rollback | v17/v19 pre-hash |
| `missing_close_mark` | `CLOSE_MARK_INCOMPLETE` | close 0개 |
| `cross_session_mark` | `CLOSE_MARK_IDENTITY_MISMATCH` | close 0개 |
| `projection_drift_before_close` | reconciliation failure | close/outcome 0개 |
| `restart_after_each_step` | baseline terminal hashes | duplicate 0건 |
| `run_outcome_reevaluation` | `RUN_OUTCOME_IMMUTABLE` | outcome hash 불변 |
| `live_destination_attempt` | call/object 0건 | tracked state 불변 |
| `portfolio_mutation` | mutation 0건 | 존재·bytes·hash 불변 |
| `network_attempt` | call 0건 | acceptance PASS |
| `later_version_import` | import 0건 | acceptance PASS |

Mutation ID set은 [v19 SPEC](../SPEC.md)의 Failure와 Mutation 표와 정확히 같아야 한다. 누락, duplicate, skip 또는 unexpected success는 acceptance failure다.

## Acceptance Database와 Fault

각 scenario는 OS temp root의 독립 v17 global head `001` database에서 시작해 v18 migration `002`를 schema bootstrap으로 설치한 뒤 v19 migration `003`을 적용해 global head `003`을 만든다. V18 business API import/call과 measurement table read/write는 0건이어야 한다. Fixture inventory는 source hashes를 고정하고 mutation은 temp database/copy에만 적용한다.

Fault checkpoint는 lease/step receipt, reservation, intent, fill, v17 projection, mark, close와 outcome 직후다. Exception 뒤 connection close/reopen에서 transaction 전 counts·hash가 복원되어야 한다. Signal timing, sleep와 OS kill 확률을 사용하지 않는다.

## Hard Boundary

- Socket, DNS, HTTP와 vendor SDK 호출 0건
- Broker client, credential, live destination와 real order 객체 0건
- `src.v20` 이후 import 0건
- V12/V13 producer adapter import와 direct artifact consumption 0건
- `data/portfolio.json`, tracked config와 fixture의 존재·bytes·hash 불변
- V18 outcome/candidate table read/write 0건

## Report 계약

Schema `v19.acceptance.1`은 version, status, plan/run/decision/intent/fill/close/outcome schema versions, checks, mutations, boundaries, v17/v19 terminal hashes와 report hash를 가진다. Array는 ID 오름차순이고 temp path, wall-clock timestamp, owner token, rowid와 random value가 없다.

모든 check·28개 mutation·boundary가 PASS이고 fixture/portfolio/tracked state와 temp cleanup이 확인될 때만 top-level PASS와 exit 0이다. 같은 fixture의 두 실행은 byte-identical stdout을 만든다.

## CLI

```bash
uv run python -m src.v19.cli prd04-acceptance
uv run python -m src.v19.cli acceptance
```

## Acceptance Criteria

- Uninterrupted run과 every-step restart run의 terminal hashes와 row counts가 같다.
- Lease contention/expiry, cutoff와 missed policy가 explicit `as_of` 경계에서 정확하다.
- Producer-neutral intake부터 v17 account fill effect까지 semantic retry가 no-op이다.
- Fault checkpoint마다 v17/v19 write set이 전부 rollback된다.
- Missing/cross-session marks와 projection drift가 close/outcome 전에 fail closed 한다.
- Network, live object, producer adapter, v20 import, v18 mutation과 portfolio mutation이 0건이다.

## 완료 조건

- `uv run python -m src.v19.cli acceptance`가 network와 후속 adapter 없이 exit 0이다.
- Session close와 restart가 SQLite만으로 재현되고 duplicate economic effect가 없다.
- V19 outcome은 운영 결과로만 남고 advisory correctness·P&L qualification·promotion을 수행하지 않는다.

## 비목표

- Actual v12~v15 runtime adapter와 end-user scheduling
- Live broker/network smoke test
- Multi-host failover, daemon와 distributed lease
- Strategy/multi-arm promotion 또는 v18 learning activation
