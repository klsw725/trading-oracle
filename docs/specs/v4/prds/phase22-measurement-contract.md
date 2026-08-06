# PRD: Phase 22 측정 계약
> **상태**: 📝 초안
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

초기 성과 추적은 추천 당시 가격과 실행 시점의 최신 종가를 비교한다. 그래서 5일과 20일 평가가 같은 최신 가격을 소비할 수 있고, 스냅샷 날짜 이후 N번째 거래일 성과라는 뜻을 보장하지 못한다. v4 이후 모든 성과, attribution, replay, calibration은 이 문서의 측정 계약을 먼저 따라야 한다.

## 목표

1. 추천 시점, 진입 시점, 청산 시점을 시장별 거래 session 기준으로 고정한다.
2. 기본 horizon을 `[5, 20]`으로 두고, 설정으로 추가되는 horizon은 양의 정수 N만 허용한다.
3. 주 지표는 거래비용을 뺀 gross benchmark excess return으로 삼고, gross absolute return을 함께 저장한다.
4. 실행 품질 보조 지표만 versioned-cost-model의 수수료, 세금, 슬리피지를 반영한 net execution return으로 계산한다.
5. 종목 가격, benchmark, corporate action, calendar, timezone provenance가 없으면 성공처럼 보이는 숫자를 만들지 않는다.

## 측정 단위

### Recommendation event

각 추천은 최소한 다음 값을 가진다.

| 필드 | 의미 | 필수 provenance |
| --- | --- | --- |
| `recommendation_id` | snapshot 안에서 추천을 식별하는 안정 ID | snapshot id, ticker, action, emitted_at hash |
| `emitted_at` | 추천이 사용자에게 노출된 timestamp | ISO 8601, timezone 포함 |
| `market` | `KR`, `US` 중 하나 | ticker resolver, exchange calendar version |
| `exchange` | `KOSPI`, `KOSDAQ`, `NASDAQ`, `NYSE` 등 | market context adapter |
| `ticker` | 거래 대상 | source ticker, normalized ticker |
| `action` | `BUY`, `SELL`, `HOLD`, `BLOCKED` 등 | consensus output provenance |
| `horizons` | 기본 `[5, 20]`과 추가 양의 정수 N | config version, parser version |

`horizons`에 `0`, 음수, 정수가 아닌 값이 들어오면 측정 대상이 아니다. 해당 추천은 Phase 23 snapshot validation에서 구조 오류로 남기고 Phase 22 결과를 만들지 않는다.

### Entry rule

진입가는 추천 이후 **다음 동일 시장 정규 거래 session의 종가**다. 추천일 당일 최신 종가나 조회 시점 최신 종가는 entry가 아니다.

| 상황 | entry session |
| --- | --- |
| KR 장중 추천 | 추천일 이후 첫 KR 정규 거래일 종가 |
| KR 장마감 후 추천 | 추천일 이후 첫 KR 정규 거래일 종가 |
| US 장중 추천 | 추천일 이후 첫 US 정규 거래일 종가 |
| US 장마감 후 추천 | 추천일 이후 첫 US 정규 거래일 종가 |
| 추천 직후 휴장 기간 | 휴장 종료 뒤 첫 동일 시장 정규 거래일 종가 |

entry timestamp는 `entry_session_close_at`으로 저장한다. 예를 들어 `2026-06-02T10:30:00+09:00` KR 추천은 `2026-06-03T15:30:00+09:00` 종가가 entry다. `2026-06-02T17:10:00-04:00` US after-close 추천은 `2026-06-03T16:00:00-04:00` 종가가 entry다.

### Exit rule

N-session exit는 entry 체결 session 이후 N번째 동일 시장 정규 거래 session의 종가다. entry session 자체는 1번째 exit session으로 세지 않는다.

공식 정의는 다음과 같다.

```text
entry_session = first_regular_session_after(emitted_at, market_calendar)
exit_session_N = nth_regular_session_after(entry_session, N, same_market_calendar)
exit_close_at_N = market_close_timestamp(exit_session_N, market_timezone)
```

예를 들어 entry가 화요일이면 N=5 exit는 수, 목, 금, 다음 월, 다음 화 중 다섯 번째 session인 다음 화요일 종가다. 중간 휴장은 session 수에 포함하지 않는다.

## 시장 calendar와 timezone

| market | timezone | session 기준 | 기본 benchmark |
| --- | --- | --- | --- |
| `KR` | `Asia/Seoul` | 한국거래소 정규장 close | KOSPI 종목은 `KS11`, KOSDAQ 종목은 `KQ11` |
| `US` | `America/New_York` | 미국 거래소 정규장 close | NASDAQ 종목은 `IXIC`, NYSE 종목은 `US500` |

calendar는 시장별 정규 session만 제공해야 한다. 조기 폐장일은 해당 calendar가 제공하는 실제 close timestamp를 사용한다. calendar version, timezone database version, source adapter version이 결과 provenance에 남아야 한다.

시장이나 exchange를 식별할 수 없거나 benchmark mapping이 없으면 benchmark excess return은 `insufficient_context`다. 이때 종목 entry와 exit가 신뢰 가능하면 gross absolute return은 별도 필드에 남길 수 있지만, primary metric은 비워 둔다.

## 상태 전이

| 상태 | 조건 | 숫자 산출 |
| --- | --- | --- |
| `pending` | entry session 또는 target exit session이 아직 닫히지 않음 | 없음 |
| `pending` | target exit session은 닫혔지만 종목 종가가 누락됐고 5-session grace 안에 있음 | 없음 |
| `matured` | entry, exit, benchmark, corporate action provenance가 모두 충분함 | gross와 net 산출 |
| `insufficient_data` | 종목 가격, total-return series, split, dividend, halt, delisting provenance가 부족함 | primary 숫자 없음 |
| `insufficient_context` | market, calendar, timezone, benchmark mapping, benchmark 가격 context가 부족함 | benchmark excess 없음 |

`pending`은 성공이나 실패가 아니다. 최신 종가로 임시 평가하지 않고, target exit session 기준 결과가 완성될 때까지 기다린다.

## 종목 가격 결측과 five-session grace

target exit session에 시장은 열렸지만 종목 종가가 없으면 최대 5개 동일 시장 session 동안 `pending`을 유지한다. 그 안에 공식 종가나 공식 terminal settlement가 확인되면 `actual_exit_session`과 `price_lag_sessions`를 기록하고 계산한다. 5개 session이 지나도 가격이 없으면 `insufficient_data`다.

grace는 horizon을 늘리는 장치가 아니다. 결과 label은 계속 원래의 `N=5` 또는 `N=20`이며, 보고서에는 target session과 actual exit session을 함께 표시한다. 6번째 session 이후에 나온 가격이나 실행 시점 최신 종가는 N-session 결과로 쓰지 않는다.

## 거래정지와 상장폐지

거래정지, 관리종목, 상장폐지는 다음 규칙으로 처리한다.

1. target exit session 이전 또는 grace 안에 공식 cash settlement, 합병 교환비율, 상장폐지 정산가가 확인되면 terminal return을 계산한다.
2. 마지막 거래 가격만 있고 공식 terminal provenance가 없으면 `insufficient_data`다.
3. 거래정지 중 target exit session이 지났고 grace 5-session도 지났으면 공식 terminal 정보가 없는 한 `insufficient_data`다.
4. terminal return을 만들 때도 corporate action 정규화 정책과 같은 provenance 요구를 적용한다.

## Corporate action과 total-return 정책

가격 series는 split과 dividend를 반영한 total-return series를 우선 사용한다. total-return series가 없으면 다음 순서로 허용한다.

1. split-adjusted OHLCV와 신뢰 가능한 cash dividend event를 결합한다.
2. split-adjusted OHLCV만 있고 측정 window 안에 dividend event가 없다는 provenance가 있으면 price-return으로 계산하고 `return_basis="split_adjusted_price"`를 남긴다.
3. split, dividend, rights offering, merger 같은 corporate action의 존재 여부를 확인할 수 없으면 `insufficient_data`다.

액면분할, 병합, 배당락, 상장폐지 정산이 window 안에 있었는데 출처와 as-of가 없으면 임의 보정하지 않는다.

## 지표와 공식

모든 수익률은 소수로 저장하고 표시할 때만 percent로 변환한다.

```text
instrument_gross_return_N = instrument_total_return_close(exit_N) / instrument_total_return_close(entry) - 1
benchmark_gross_return_N = benchmark_total_return_close(exit_N) / benchmark_total_return_close(entry) - 1
direction_multiplier = BUY: 1, SELL: -1, HOLD: 0, BLOCKED: 0
directional_gross_return_N = direction_multiplier * instrument_gross_return_N
directional_benchmark_return_N = direction_multiplier * benchmark_gross_return_N
gross_benchmark_excess_return_N = directional_gross_return_N - directional_benchmark_return_N
gross_absolute_return_N = instrument_gross_return_N
```

Primary decision-quality metric은 `gross_benchmark_excess_return_N`이다. `gross_absolute_return_N`은 시장 방향과 무관한 종목 자체 가격 변화를 보여 주는 보조 gross 지표다.

HOLD와 BLOCKED는 Phase 26과 Phase 28에서 opportunity cost와 avoided loss로 평가한다. Phase 22는 해당 action에 대해 가격 path와 상태를 저장하되, `direction_multiplier=0`으로 임의 trading PnL을 만들지 않는다.

## Net execution 보조 지표

net execution metric은 실제 또는 paper execution 품질을 보기 위한 secondary metric이다. 주 지표를 대체하지 않는다.

```text
cost_rate_total = buy_fee_rate + buy_slippage_rate + sell_fee_rate + sell_tax_rate + sell_slippage_rate + market_specific_fees_rate
net_execution_return_N = directional_gross_return_N - cost_rate_total
net_execution_benchmark_excess_return_N = net_execution_return_N - directional_benchmark_return_N
```

`cost_model_version`은 결과마다 필수다. 예시는 다음과 같다.

| version | market | buy_fee | buy_slippage | sell_fee | sell_tax | sell_slippage | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `kr-equity-v2026.1` | KR | 0.015% | 0.050% | 0.015% | 0.180% | 0.050% | 0.000% |
| `us-equity-v2026.1` | US | 0.000% | 0.030% | 0.000% | 0.000% | 0.030% | 0.002946% |

비용 모델은 versioned artifact로 관리한다. 과거 결과를 다시 계산할 때는 당시 결과가 참조한 `cost_model_version`을 사용한다.

## 데이터와 provenance 경계

Phase 22 결과는 계산에 필요한 입력과 출처를 분리해 저장한다.

| 영역 | 저장해야 하는 값 | 저장하면 안 되는 값 |
| --- | --- | --- |
| price | source id, symbol, as-of, adjusted field name, raw content hash | API key, credential, 원문 payload 전체 |
| benchmark | benchmark id, source id, calendar alignment, as-of | 다른 시장 benchmark를 조용히 대체한 값 |
| calendar | market calendar version, timezone, close timestamp | 로컬 시스템 timezone 추정값 |
| corporate action | event type, ex-date, effective date, source id, as-of | 출처 없는 보정 계수 |
| cost model | version, market, fee components | broker secret, 계좌 식별자 |

기존 82개 snapshot은 당시 data cutoff, raw prompt, market context가 부족할 수 있다. 이 문서의 native v4 결과와 같은 canonical 성과로 섞지 않고, Phase 24의 legacy audit 경로에서 별도 eligibility를 판정한다.

## Fixture matrix

### F1. KR 장중 BUY, 5-session matured

입력:

```json
{
  "fixture": "kr_intraday_buy_5_session",
  "emitted_at": "2026-06-02T10:30:00+09:00",
  "market": "KR",
  "exchange": "KOSPI",
  "ticker": "005930",
  "action": "BUY",
  "benchmark": "KS11",
  "N": 5,
  "entry_session": "2026-06-03",
  "exit_session": "2026-06-10",
  "instrument_entry_tr_close": 100000.0,
  "instrument_exit_tr_close": 106000.0,
  "benchmark_entry_tr_close": 2500.0,
  "benchmark_exit_tr_close": 2575.0,
  "cost_model_version": "kr-equity-v2026.1"
}
```

계산:

```text
instrument_gross_return_5 = 106000 / 100000 - 1 = 0.060000 = 6.00%
benchmark_gross_return_5 = 2575 / 2500 - 1 = 0.030000 = 3.00%
gross_benchmark_excess_return_5 = 0.060000 - 0.030000 = 0.030000 = 3.00%
cost_rate_total = 0.00015 + 0.00050 + 0.00015 + 0.00180 + 0.00050 = 0.00310 = 0.31%
net_execution_return_5 = 0.060000 - 0.00310 = 0.056900 = 5.69%
net_execution_benchmark_excess_return_5 = 0.056900 - 0.030000 = 0.026900 = 2.69%
```

기대 상태: `matured`. 최신 종가 대체 없음. entry 이후 다섯 번째 KR session 종가를 사용한다.

### F2. US after-close BUY, 5-session matured

입력:

```json
{
  "fixture": "us_after_close_buy_5_session",
  "emitted_at": "2026-06-02T17:10:00-04:00",
  "market": "US",
  "exchange": "NASDAQ",
  "ticker": "AAPL",
  "action": "BUY",
  "benchmark": "IXIC",
  "N": 5,
  "entry_session": "2026-06-03",
  "exit_session": "2026-06-10",
  "instrument_entry_tr_close": 200.0,
  "instrument_exit_tr_close": 190.0,
  "benchmark_entry_tr_close": 17000.0,
  "benchmark_exit_tr_close": 17170.0,
  "cost_model_version": "us-equity-v2026.1"
}
```

계산:

```text
instrument_gross_return_5 = 190 / 200 - 1 = -0.050000 = -5.00%
benchmark_gross_return_5 = 17170 / 17000 - 1 = 0.010000 = 1.00%
gross_benchmark_excess_return_5 = -0.050000 - 0.010000 = -0.060000 = -6.00%
cost_rate_total = 0.00030 + 0.00030 + 0.00002946 = 0.00062946 = 0.062946%
net_execution_return_5 = -0.050000 - 0.00062946 = -0.05062946 = -5.062946%
net_execution_benchmark_excess_return_5 = -0.05062946 - 0.010000 = -0.06062946 = -6.062946%
```

기대 상태: `matured`. US 장마감 후 추천은 추천일 종가를 entry로 쓰지 않고 다음 US 정규 session 종가를 entry로 쓴다.

### F3. 휴장과 20-session 미성숙

입력:

```json
{
  "fixture": "kr_holiday_immature_20_session",
  "emitted_at": "2026-09-24T11:00:00+09:00",
  "market": "KR",
  "exchange": "KOSPI",
  "ticker": "005930",
  "action": "BUY",
  "benchmark": "KS11",
  "N": 20,
  "entry_session": "2026-09-28",
  "known_closed_sessions_after_entry": 7
}
```

기대 상태: `pending`. 휴장 기간은 session 수에 포함하지 않는다. entry 이후 20번째 KR session이 아직 닫히지 않았으므로 최신 종가로 20-session 결과를 만들지 않는다.

### F4. 종목 가격 누락과 five-session grace 초과

입력:

```json
{
  "fixture": "kr_halt_missing_price_grace_expired",
  "emitted_at": "2026-06-02T10:30:00+09:00",
  "market": "KR",
  "exchange": "KOSDAQ",
  "ticker": "123456",
  "action": "BUY",
  "benchmark": "KQ11",
  "N": 5,
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "missing_price_sessions": ["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-15", "2026-06-16", "2026-06-17"],
  "official_terminal_provenance": null
}
```

기대 상태: `insufficient_data`. target exit session부터 5개 grace session 안에 종가나 공식 terminal settlement가 없었다. `2026-06-17` 이후 가격이 나와도 원래 5-session 결과로 쓰지 않는다.

### F5. 상장폐지 terminal settlement 확인

입력:

```json
{
  "fixture": "us_delisting_terminal_settlement",
  "emitted_at": "2026-06-02T11:00:00-04:00",
  "market": "US",
  "exchange": "NYSE",
  "ticker": "XYZ",
  "action": "BUY",
  "benchmark": "US500",
  "N": 5,
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "instrument_entry_tr_close": 10.0,
  "official_cash_settlement": 6.0,
  "settlement_source": "exchange_notice_hash:abc123",
  "settlement_as_of": "2026-06-09T18:00:00-04:00"
}
```

기대 상태: benchmark와 corporate action provenance도 충분하면 `matured`다. 공식 정산가가 있으므로 terminal return을 만들 수 있다. 정산 provenance가 없으면 같은 사례는 `insufficient_data`다.

### F6. Corporate action provenance 누락

입력:

```json
{
  "fixture": "missing_corporate_action_provenance",
  "emitted_at": "2026-06-02T10:30:00+09:00",
  "market": "KR",
  "exchange": "KOSPI",
  "ticker": "999999",
  "action": "BUY",
  "benchmark": "KS11",
  "N": 5,
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "observed_split_like_price_gap": true,
  "corporate_action_source": null
}
```

기대 상태: `insufficient_data`. split 또는 배당 가능성이 있는데 provenance가 없으므로 split-adjusted price나 total-return series를 추정하지 않는다.

## Acceptance criteria

1. 모든 Phase 22 산출물은 entry, target exit, actual exit, state, benchmark, return_basis, cost_model_version을 저장한다.
2. `gross_benchmark_excess_return_N`이 primary metric이고 `gross_absolute_return_N`이 함께 표시된다.
3. `net_execution_return_N`은 secondary metric으로만 표시되며 cost model version 없이는 산출하지 않는다.
4. `pending`, `matured`, `insufficient_data`, `insufficient_context`가 서로 배타적으로 판정된다.
5. 최신 종가를 N-session 결과로 대체하는 stale state가 검증에서 실패한다.
6. 기존 초기 성과 결과는 이 계약과 다르므로 native v4 canonical 성과로 승격하지 않는다.
