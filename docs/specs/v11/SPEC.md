# Trading Oracle v11 SPEC: Paper Execution And Ledger
> **상태**: 📝 초안

v11은 [v10](../v10/SPEC.md)의 point-in-time market artifact를 virtual order, fill, cash, position, cost, exposure, reconciliation event로 변환하는 paper-only 실행 계약이다. 실계좌 주문과 `data/portfolio.json` 변경은 범위 밖이다.

## 0. 구현 완결성 계약

- v11은 구현 완료된 v10 artifact와 v11 로컬 `execution_decision` fixtures만 입력으로 사용한다.
- 전략 엔진, LLM, 통계 검증, 운영 승격 모듈이 없어도 sizing, risk, intent, partial fill, cost, ledger, replay, execution halt를 end-to-end 실행해야 한다.
- `uv run python -m src.v11.cli acceptance`가 v10 canonical fixtures와 v11 로컬 fixtures를 읽어 canonical JSON 보고서를 출력하고 exit 0이어야 한다.
- 로컬 fixture는 deterministic score, symbol, side, cutoff, decision_ready_at을 가진 실행 제안을 제공하며 미래 버전 artifact를 흉내 내거나 import하지 않는다.
- v12 이후 디렉터리를 삭제하거나 아직 구현하지 않아도 v11 acceptance는 동일하게 통과해야 한다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v11 구현은 단독으로 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Account, Risk, Reservation](prds/prd01-account-risk-reservation.md) | Account, sizing, reservation, risk, daily-loss halt | account·risk·reservation artifacts |
| PRD 02 | [Execution, Cost, Short](prds/prd02-execution-cost-short.md) | Decision timing, liquidity, fill, cost, short | intent·fill·cost·short artifacts |
| PRD 03 | [Ledger, Replay, Execution Halt](prds/prd03-ledger-replay-execution-halt.md) | Identity, event chain, replay, reconciliation, halt | ledger·replay·halt artifacts |
| PRD 04 | [Acceptance And Paper Boundary](prds/prd04-acceptance-paper-boundary.md) | Local fixture orchestration and no-live guard | canonical acceptance report |

PRD 01→04 순서로 구현한다. V11 completion은 이 네 PRD와 v10만 사용하며 PRD 04는 risk·fill·ledger 판정을 복제하지 않는다.

## 1. 계좌와 자본

| Market | Currency | Initial NAV | Position limit | Gross limit | Net limit |
| --- | --- | ---: | ---: | ---: | ---: |
| KR | KRW | 100,000,000 | 10 | 20% | -10% to +10% |
| US | USD | 100,000 | 10 | 20% | -10% to +10% |

KR과 US는 독립 virtual account다. 성과와 risk는 현지통화 NAV로 계산하며 FX 수익을 섞지 않는다. 통합 화면이 생겨도 원장과 verdict의 기준통화는 바뀌지 않는다.

## 2. Position Sizing

1. 신규 포지션 목표 명목금액은 해당 시장 전일 종가 NAV의 2%다.
2. 수량 산정가격은 intent를 만들기 전에 이용 가능한 가장 최근 complete 1분봉 종가다. 목표금액을 이 causal reference price로 나눈 뒤 정수 주식으로 내림한다.
3. fractional share와 목표금액 초과 반올림은 허용하지 않는다.
4. 잔여금액은 현금으로 유지한다.
5. 기존 포지션을 포함해 최대 10개, gross 20%, net ±10%를 모두 만족해야 한다.
6. sector gross는 6% 이하로 유지한다.
7. 신규 후보와 기존 포지션의 20거래일 수익률 절대 상관계수 `|rho|`가 0.7을 초과하면 신규 진입을 차단한다.
8. 빈 slot보다 로컬 `execution_decision`이 많으면 fixture의 `deterministic_score` 내림차순, canonical symbol 오름차순, decision ID 오름차순으로 검사하고 모든 제약을 통과한 제안부터 채운다.

상관계수는 cutoff 이전 adjusted daily close 21개로 만든 유한한 일별수익률 20쌍을 사용한다. 기존 포지션이 없으면 correlation gate는 통과한다. 기존 포지션이 하나라도 있을 때 paired return 부족, missing 값, zero variance, 비유한 결과가 있으면 신규 후보를 fail closed 한다.

### Cash, short collateral, reservation

- Margin과 leverage는 허용하지 않는다.
- Long intent는 목표 명목금액과 예상 비용을 available cash에서 예약한다.
- Short 매도대금은 신규 주문의 available cash로 재사용하지 않는다.
- Short intent는 목표 gross notional과 예상 비용을 collateral reservation으로 잡는다.
- 같은 cutoff의 후보는 확정 정렬 순서대로 하나씩 예약한다. 앞선 intent가 예약한 cash, gross, net, sector, slot은 뒤 후보의 risk 입력에 즉시 반영한다.
- 취소·거부·미체결 잔량의 reservation은 대응 event가 원장에 기록된 뒤에만 해제한다.

## 3. 유동성 제한

- cutoff 이전 완결 1분봉 20개의 중앙 거래대금을 계산한다.
- 주문 목표 명목금액은 그 중앙값의 5% 이하로 축소한다.
- 미래인 목표 1분봉의 거래량을 주문 수량 결정에 사용하지 않는다.
- fill simulation에서는 목표 1분 실제 거래량의 최대 5%까지만 체결한다.
- 1분 종료 시 미체결 잔량은 취소하고 다음 분으로 이월하지 않는다.
- 0주가 되면 주문을 만들지 않고 명시적 `NO_ORDER_LIQUIDITY` 결과를 남긴다.

## 4. 결정 시각과 체결 시각

### 즉시 결정 경로

로컬 deterministic fixture는 완결 5분봉과 v10의 10초 watermark 뒤에 `execution_decision`을 만든다. 모든 신규 진입은 `decision_ready_at` 이후 최초 1분 경계를 목표 체결 시점으로 사용한다. 아직 complete인지 알 수 없는 5분봉의 즉시 다음 시가를 소급 체결가격으로 사용하지 않는다.

### 지연 결정 경로

1. 5분 구간 종료 10초 후 v10 watermark가 닫힌다.
2. 로컬 delayed-decision fixture는 watermark 뒤 최대 20초 안의 `decision_ready_at`을 제공한다.
3. 즉시·지연 경로 모두 결정 완료 후 최초 1분 경계를 목표 체결 시점으로 사용한다.
4. 목표 1분 경계 전에 주문 intent가 확정되지 않으면 해당 신호를 stale로 취소한다.
5. 지연된 intent를 다음 1분 또는 다음 5분으로 순연하지 않는다.

## 5. Fill과 비용

Baseline fill은 목표 1분봉 시가 reference와 시장별 execution-cost bucket을 사용한다. 비용은 다음을 분리해서 기록한다.

- commission과 broker fee
- KR 세금 또는 시장별 법정 비용
- half-spread 및 slippage
- participation·가격·변동성 bucket 조정
- short borrow fee와 locate 관련 비용

Cost bucket은 point-in-time bid/ask 또는 paper order snapshot을 가격·변동성·participation별로 실측한다. 표본 부족 bucket은 사전 정의한 보수적 상위 분위수를 사용한다. 활성 run 안에서는 cost model version을 동결한다. 새 cost model은 v11 로컬 `cost_policy_approval`에 이전·신규 hash, effective session, reviewer가 모두 있어야 다음 run부터 적용한다.

`2× execution-cost stress`는 spread, slippage, participation impact, borrow·locate처럼 모델링된 가변 실행비용만 2배로 한다. 법정 세금과 계약상 고정 commission은 baseline 실액을 유지한다.

## 6. Short Execution

Short 후보는 시장별 공식 공매도 규제와 실행 제약을 모두 통과해야 한다.

- US: locate, ETB, borrow fee, SSR 및 당시 유효한 공식 주문 제약
- KR: 공매도 가능 종목, 차입 가능성, 호가 제한 및 당시 유효한 공식 규칙
- eligibility는 일일 ETB·borrow fee·locate snapshot과 규제 artifact hash에 묶는다.
- snapshot 누락 또는 규칙 판정 불가는 fail closed다.
- 연율 borrow fee는 달력일 기준으로 일할 계산한다.
- recall 또는 ETB 해제 시 다음 거래 가능한 1분 경계에 강제청산한다.

규제 규칙을 단순 고정 상수로 두지 않는다. 공식 규칙의 effective period를 보존해 과거 replay에 당시 규칙을 적용한다.

## 7. 장마감 규칙

- 공식 정규장 종료 20분 전부터 신규 진입을 금지한다.
- 이는 최소 15분 보유 뒤 종료 5분 전 청산할 수 있게 한다.
- 종료 5분 전 대기 신규 주문을 취소하고 청산 intent를 만든다. 모든 intraday 포지션은 그 뒤 최초 거래 가능한 1분 경계에서 청산한다.
- 조기폐장도 공식 종료시각을 기준으로 같은 20분·5분 규칙을 적용한다.
- overnight position은 허용하지 않는다.

## 8. Append-only Event Ledger

최소 event 흐름은 다음과 같다.

```text
signal_observed -> order_intended -> risk_checked -> order_accepted
-> fill_partial|fill_complete|order_cancelled -> position_updated
-> cost_accrued -> reconciled -> session_closed
```

각 event는 `event_id`, `event_index`, `event_type`, `entity_id`, `occurred_at`, `recorded_at`, `payload_hash`, `previous_event_hash`, `event_hash`, `experiment_manifest_hash`를 가진다.

주문 intent ID는 `market`, `account_arm`, `cutoff`, `candidate_id`, `router_decision_id` 또는 deterministic decision ID, `strategy_id`, `strategy_version`, `symbol`, `side`, `action`의 canonical hash다. 원장은 이를 unique key로 사용하고 동일 intent의 중복 전달을 no-op 처리한다. Broker order ID나 프로세스 메모리 lock만으로 idempotency를 보장해서는 안 된다.

## 9. Replay와 재시작

1. 상태 JSON을 source of truth로 사용하지 않는다.
2. 장중 재시작은 마지막 검증 checkpoint 이후 event를 replay한다.
3. virtual cash, position, open intent, fill, cost를 source snapshot과 대조한다.
4. 완전히 일치할 때만 신규 주문을 재개한다.
5. 불일치, hash chain break, event gap, 중복 semantic event는 v11 `execution_halt`를 발동해 대기 intent를 취소하고 신규 intent를 차단한다.
6. numpy scalar가 artifact에 들어오더라도 canonical boundary에서 표준 int 또는 decimal string으로 변환되어야 한다.

## 10. Risk Gate 순서

```text
eligibility -> market session -> data freshness -> borrow/regulation
-> position count -> single-name size -> sector -> correlation
-> gross/net -> liquidity -> daily_loss_halt -> execution_halt -> intent creation
```

경고가 blocker를 덮어쓸 수 없다. 하나의 gate가 실패하면 이후 gate를 성공으로 추정하지 않고 이유 코드와 입력 hash를 기록한다.

Gross, net, sector, correlation, slot, cash, collateral 한도는 intent 예약 전 hard gate다. 정상적인 가격 변동으로 기존 포지션이 한도를 넘으면 즉시 강제 리밸런싱하지 않고 신규·교체 진입을 차단한 채 `exposure_drift`를 기록한다. 승인되지 않은 fill, reservation 누락, 계산 불일치로 한도를 넘으면 v11 `execution_halt`를 발동한다. `daily_loss_halt`와 장마감·recall 강제청산은 이 drift 보유 예외보다 우선한다.

### v11 local daily-loss halt

각 virtual account는 전일 종가 NAV 대비 2% 손실에서 `daily_loss_halt`를 발동한다. 매 1분 실현·미실현 손익과 commission, tax, spread, slippage, borrow 비용을 모두 반영한다. 발동 시 대기 intent를 취소하고 신규 intent를 막으며 신뢰 가능한 다음 1분 경계에서 해당 account 포지션을 전량 청산한다. 같은 세션에는 재개하지 않고 다음 공식 정규장에 자동 초기화한다. 이 로컬 halt는 외부 운영 모듈 없이 v11 acceptance에서 실행 가능해야 한다.

## 11. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `fractional_quantity` | 소수점 주식 수량 입력 | quantity failure |
| `future_volume` | 목표 1분 거래량으로 주문 수량 결정 | lookahead failure |
| `overfill` | 실제 1분 거래량 5% 초과 fill | participation failure |
| `carry_remainder` | 잔량을 다음 분으로 이월 | stale execution failure |
| `duplicate_intent` | 동일 intent 재전달 | 두 번째 전달 no-op |
| `strategy_collision` | 같은 symbol·cutoff의 다른 전략 intent를 같은 ID로 생성 | identity failure |
| `unreserved_batch` | 동시 intent가 같은 cash·gross를 중복 사용 | reservation failure |
| `ledger_break` | previous hash 변경 | reconciliation failure, execution halt |
| `missing_borrow` | snapshot 없이 short 허용 | short eligibility failure |
| `late_entry` | 종료 20분 안에 신규 진입 | market-close risk failure |
| `overnight` | 공식 session close까지 미청산 | forced-liquidation failure |
| `correlation_unknown` | paired return 부족 또는 zero variance인데 진입 허용 | correlation gate failure |

## 12. Acceptance Criteria

- 두 시장의 virtual cash와 성과가 통화별로 분리된다.
- 직전 complete 1분봉 종가를 사용한 2% 정수 주식 sizing, cash·short collateral reservation, 시장별 10종목, gross 20%, net ±10%, sector 6%, correlation 0.7이 함께 적용된다.
- 주문 수량과 부분체결이 각각 과거 중앙 거래대금과 실제 목표 분 거래량의 5%를 넘지 않는다.
- 로컬 즉시·최대 20초 지연 `execution_decision`은 10초 watermark 뒤 각자의 `decision_ready_at` 이후 최초 1분 경계에서만 체결 가능하다.
- 시장별 short 규제, borrow 비용, recall 강제청산을 replay할 수 있다.
- append-only ledger와 결정론적 intent ID로 재시작·중복 전달을 재현한다.
- 2% `daily_loss_halt`가 비용 포함 mark-to-market, 주문 취소, 다음 1분 전량청산, 다음 장 초기화를 수행한다.
- 로컬 즉시·지연 `execution_decision` fixture만으로 후속 전략·router 없이 전체 실행 경로를 검증한다.
- 실계좌 주문, credential, raw account ID, `data/portfolio.json` 변경은 발생하지 않는다.
