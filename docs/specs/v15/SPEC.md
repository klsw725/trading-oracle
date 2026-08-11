# Trading Oracle v15 SPEC: Paper Operations, Promotion And Rollback
> **상태**: 📝 초안

v15는 [v10](../v10/SPEC.md)부터 [v14](../v14/SPEC.md)까지의 산출물을 paper research 운영으로 활성화하는 마지막 계약이다. 이 문서의 `paper`, `primary`, `challenger`, `automation`은 모두 virtual ledger 범위이며 실계좌 주문 권한을 뜻하지 않는다.

## 0. 구현 완결성 계약

- v15는 구현 완료된 v10~v14 artifact만 의존하며 정의되지 않은 후속 버전이나 live broker 기능을 요구하지 않는다.
- 승인, ORB 자동 승격, 14개 shadow activation, router challenger, mirror comparison, loss·operation kill switch, rollback, recovery를 paper namespace에서 end-to-end 실행해야 한다.
- `uv run python -m src.v15.cli acceptance`가 이전 버전 canonical fixtures와 v15 로컬 multi-session operation fixtures를 읽어 canonical JSON 보고서를 출력하고 exit 0이어야 한다.
- Acceptance는 정상 승격, 표본 보류, router 승리, 운영 rollback·재개, 성과 rollback·폐기, arm·market·global kill scope, 다음 장 reset을 모두 실행한다.
- 실계좌 destination, credential, raw account ID, `data/portfolio.json` mutation 없이 v15 자체가 최종 runnable paper system을 구성해야 한다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v15 구현은 단독으로 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Approval, Promotion, Activation](prds/prd01-approval-promotion-activation.md) | Approval and lifecycle gates | promotion·activation events |
| PRD 02 | [Mirror Challenger Comparison](prds/prd02-mirror-challenger-comparison.md) | ORB/router mirror and paired winner | mirror ledgers and winner artifact |
| PRD 03 | [Kill Switch And Recovery](prds/prd03-kill-switch-recovery.md) | Loss·operation scope, flatten, reset | incident·liquidation·recovery events |
| PRD 04 | [Rollback, Report, Acceptance](prds/prd04-rollback-report-acceptance.md) | Operational/performance rollback, report, final CLI | final paper lifecycle report |

PRD 01→04 순서로 구현한다. PRD 04 acceptance가 통과하면 v10~v15만으로 final runnable paper system이 완성된다.

## 1. 구현과 활성화 순서

```text
data/calendar/universe
-> event ledger/replay/risk/execution
-> 15-minute ORB paper
-> remaining 14 strategies shadow
-> mixed router shadow
-> mixed router paper challenger
```

후속 단계를 먼저 구현해도 앞 단계 acceptance가 통과하기 전 활성화할 수 없다. Router부터 시작하거나 15개 전략을 한 번에 paper 주문 경로에 올리지 않는다.

## 2. 승인 정책

정상적인 일일 universe와 변경 없는 정책의 일상 run은 자동 승인한다. 다음은 자동 승인을 중단하고 운영자 수동 승인을 요구한다.

### Data exceptions

- source fallback 또는 source incident
- 원천 봉 누락, timestamp 오류, supersede 충돌
- corporate action 불일치
- ETB, borrow, locate, 규제 snapshot 이상
- hash, signature, replay, reconciliation 불일치

### Policy changes

- selector 또는 universe policy version 변경
- strategy, parameter, risk, cost model version 변경
- router weight, prompt, Codex model, output schema 변경

승인은 정확한 manifest hash, effective session, 변경 이유, reviewer identity를 가진다. 과거 approval을 새 hash에 재사용하지 않는다.

수동 승인은 변경 적용의 필요조건일 뿐 [v14](../v14/SPEC.md)의 새 experiment version과 전체 validation·holdout gate를 대체하지 않는다. Manifest hash가 바뀌는 변경은 승인만으로 기존 paper version에 적용할 수 없다.

## 3. ORB 승격

15분 ORB가 [v14](../v14/SPEC.md)의 validation과 untouched holdout gate를 통과하면 다음 정규장부터 해당 시장 ORB paper arm으로 자동 승격한다. 별도 승격 승인으로 결과를 재해석하지 않지만, holdout 개봉 자체는 v14의 수동 승인을 먼저 요구한다.

ORB paper는 [v11](../v11/SPEC.md)의 독립 KRW·USD account, risk, fill, cost, ledger를 사용한다. 한 시장의 pass가 다른 시장을 승격하지 않는다.

## 4. Shadow 전략과 Router 승격

- 나머지 14개 전략은 ORB paper가 20 공식 거래세션, 완료 거래 30건, critical ledger·replay·risk incident 0건을 충족한 뒤 shadow로 활성화한다.
- Mixed router도 development, validation, untouched holdout, 최소 표본을 독립 통과해야 한다.
- ORB가 paper 상태이고 router 자체 gate가 통과한 시장에서만 router를 paper challenger로 자동 승격한다.
- Shadow 결과만으로 offline gate를 생략하지 않는다.

## 5. Mirror Account 비교

Router challenger 시작일을 `comparison_epoch_start`로 고정하고 ORB baseline과 router challenger에 동일 initial NAV의 새 독립 mirror ledger를 동시에 만든다. 기존 ORB 운영 ledger는 역사 보존용이며 paired verdict에 섞지 않는다. 두 mirror는 동일 market data, universe, risk, cost model을 사용한다.

| Arm | Role |
| --- | --- |
| ORB baseline | 15분 ORB 기준군 |
| Mixed router challenger | 80:20 router 실험군 |

두 arm은 slot과 포지션을 공유하지 않는다. 하나의 계좌에서 주문 경쟁을 시키지 않는다. 각 정책의 실제 decision latency와 execution boundary는 해당 계약대로 비용에 반영한다.

Paper verdict를 내리기 전에 시장별 각 arm이 다음을 모두 충족해야 한다.

- 독립 거래일 60일
- 완료 거래 300건

## 6. Paper 승자 판정

Mixed router가 ORB보다 우수하려면 다음을 모두 만족한다.

1. 동일 거래일 paired 순비용 초과수익의 block-bootstrap 95% CI lower bound가 0보다 크다.
2. Router의 2× execution-cost stress 순수익이 0보다 크다.
3. 중대 ledger, replay, risk, attribution 오류가 0건이다.

누적수익, win rate, Sharpe만으로 승자를 선언하지 않는다. 통과하면 router를 primary paper arm으로 승격하고 ORB는 외부 primary action을 만들지 않는 mirror baseline으로 계속 운영한다. ORB mirror는 동일 데이터로 virtual signal, intent, fill, 비용, NAV를 계속 생성해 rolling paired comparator 역할을 유지한다.

Paired series는 comparison epoch 이후 두 arm의 공통 공식 거래일 전체를 포함한다. 한쪽 또는 양쪽의 no-trade day와 arm-level loss kill day도 0 또는 실제 일별 수익으로 포함하며 임의 삭제하지 않는다. 최소 표본 충족 뒤 매 공식 거래일 종료 시 v14의 5일 block·10,000 resample·고정 seed 규칙으로 평가한다.

## 7. Router Rollback

### 즉시 운영 rollback

중대 ledger, replay, reconciliation, risk invariant 오류가 발생하면 router primary를 즉시 중단하고 ORB primary로 되돌린다. 원인 수정이 code, config, prompt, model, schema, cost, strategy, risk 또는 manifest hash를 바꾸지 않는 외부 운영 복구일 때만 deterministic replay 검증과 수동 승인 뒤 같은 router version을 재개할 수 있다. Manifest가 바뀌면 새 version으로 v14 전체 gate를 다시 통과해야 한다.

### 성과 rollback

최근 20개 공통 공식 거래일 window 안에서 ORB mirror와 router primary가 각각 완료 거래 100건 이상을 가질 때 rolling paired 비교를 실행한다. 그 window의 router 초과수익 95% CI upper bound가 0 이하이면 ORB primary로 rollback한다. 어느 arm이든 100건 미만이면 성과 verdict를 보류한다. 해당 router version은 종료하며 재승격할 수 없다. 새 version이 전체 v14 gate를 다시 통과해야 한다.

## 8. 일일 손실 Kill Switch

각 market·arm virtual account는 자신의 전일 종가 NAV 대비 2% 손실 한도를 가진다. 매 1분 mark-to-market NAV에 다음을 모두 반영한다.

- 실현 손익
- 미실현 손익
- commission, tax, spread, slippage
- borrow와 기타 체결비용

한 arm이 2%에 도달하면 해당 market·arm만 loss kill switch를 발동한다. 다른 arm이나 시장을 자동 중단하지 않고 FX 환산 통합 손실을 사용하지 않는다. Primary arm이 loss kill로 중단돼도 같은 날 ORB mirror를 primary로 전환하거나 신규 진입을 재개하지 않는다.

## 9. 운영 Kill Switch

다음 중 하나면 손실 수준과 무관하게 해당 범위 kill switch를 발동한다.

- stale 또는 불완전한 current data
- hash chain, manifest, signature 불일치
- ledger와 source position·cash reconciliation 불일치
- source incident 또는 잘못된 fallback
- calendar, regulation, borrow 상태를 신뢰할 수 없음
- 중복 주문 또는 idempotency invariant 위반

### Trigger scope

| Trigger | Scope |
| --- | --- |
| 한 symbol의 개별 1분봉 누락·stale, corporate action·borrow eligibility 이상 | 해당 symbol·cutoff eligibility 차단, 대체 종목 없음 |
| 한 arm의 ledger·reservation·position reconciliation 불일치 | 해당 market·arm kill |
| 시장 calendar, shared source stream, market-wide universe, 규제 snapshot 무결성 실패 | 해당 시장의 모든 arm kill |
| manifest, code, policy identity 또는 공통 hash chain 신뢰 실패 | 전체 paper system kill |

개별 symbol data defect만으로 정상 symbol의 포지션까지 전량청산하지 않는다. 결함 범위를 증명할 수 없으면 한 단계 넓은 scope로 fail closed 한다.

## 10. Kill Switch 동작과 재개

발동 즉시:

1. 모든 대기 주문 intent를 취소한다.
2. 신규 진입을 차단한다.
3. 신뢰 가능한 다음 1분 경계에서 기존 포지션을 전량 청산한다.
4. 당일 재진입을 금지한다.
5. trigger, affected market·arm, input hash, 취소·청산 결과를 append-only event로 기록한다.

손실 kill switch는 다음 정규장에 해당 arm만 자동 초기화한다. Data, hash, reconciliation, source 등 운영 kill switch는 root cause 해소, replay 일치, 수동 승인 전까지 다음 거래일에도 유지한다. 운영 이상이 같은 날 해소돼도 당일 재진입하지 않는다. 시장 또는 전체 kill이 arm loss kill보다 우선한다.

## 11. LLM 운영 상태

[v13](../v13/SPEC.md)의 timeout, schema failure, batch overflow, abstain은 quant fallback으로 처리한다. 3회 연속 또는 최근 20회 중 20% 실패 circuit breaker가 열리면 남은 세션은 quant-only다. 이 상태는 손실 kill switch가 아니며 주문을 중단하지 않는다. 다만 LLM arm 상태, fallback rate, 원인 code를 성과와 운영 보고에서 분리해 보여야 한다.

Prompt injection artifact, provider auth failure, model version mismatch가 policy integrity를 훼손하면 단순 fallback이 아니라 운영 incident로 승격할 수 있다. manifest mismatch는 항상 운영 kill switch다.

## 12. 상태 모델

```text
foundation_candidate -> foundation_ready
orb_candidate -> orb_holdout_passed -> orb_paper
strategies_candidate -> strategies_shadow
router_candidate -> router_shadow -> router_challenger -> router_primary
router_primary -> router_operational_rollback -> router_primary
router_primary -> router_performance_rollback -> router_retired
any_active -> kill_switch_active -> next_session|manual_recovery
```

금지 전이:

- holdout을 통과하지 않은 ORB 또는 router의 paper 활성화
- router가 ORB보다 먼저 primary가 되는 전이
- 성과 rollback version의 재승격
- 운영 kill switch의 자동 재개
- paper 상태에서 live destination으로 전이

## 13. 운영 보고

시장·arm·session별로 최소 다음을 보고한다.

- manifest와 policy version
- data completeness, fallback, supersede, reconciliation 상태
- candidate, NO_TRADE, order, partial fill, cancellation 수
- gross, net, sector, correlation, position count
- 실현·미실현·비용별 P&L
- LLM timeout, abstain, schema failure, circuit breaker, quant fallback 비율
- kill switch trigger와 recovery 상태
- ORB와 router paired performance 및 sample sufficiency

정상 상태만 집계하고 degraded·fallback을 숨겨서는 안 된다.

## 14. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `policy_auto_approve` | model version 변경을 자동 승인 | approval failure |
| `router_early_promotion` | router holdout 없이 challenger 활성화 | promotion failure |
| `shared_account` | ORB와 router가 같은 slot 공유 | mirror isolation failure |
| `loss_realized_only` | 미실현·비용 제외 | daily-loss failure |
| `kill_no_flatten` | kill switch 뒤 포지션 유지 | termination failure |
| `operation_auto_reset` | reconciliation incident 다음 장 자동 재개 | recovery failure |
| `symbol_to_market_kill` | 격리 가능한 단일 symbol 누락으로 전체 시장 청산 | trigger-scope failure |
| `approval_bypass_gate` | 새 manifest를 승인만으로 paper 적용 | validation bypass failure |
| `mirror_no_fill` | 승격 뒤 ORB mirror NAV 갱신 중단 | comparator failure |
| `performance_repromote` | 성과 rollback version 재승격 | retired-version failure |
| `hidden_quant_fallback` | LLM 실패를 mixed 성공으로 집계 | observability failure |
| `live_destination` | paper state에서 broker live submit | hard boundary failure |

## 15. Acceptance Criteria

- 구현 순서는 data·ledger·ORB·14개 shadow·router로 고정된다.
- 정상 일일 run은 자동, data와 policy 변경은 수동 승인이다.
- ORB와 router가 각자의 v14 gate를 통과해야 paper에 자동 승격된다.
- ORB와 router는 독립 mirror account에서 60일·300거래 뒤 비교된다.
- Router 승리, 운영 rollback, 성과 rollback, version 폐기 규칙이 명확하다.
- Market·arm별 2% 일일 손실과 symbol·arm·market·global 운영 incident scope가 구분된다.
- 손실은 다음 장 자동 초기화하고 운영 이상은 수동 복구한다.
- 모든 단계가 virtual paper 범위이며 live order path는 존재하지 않는다.
