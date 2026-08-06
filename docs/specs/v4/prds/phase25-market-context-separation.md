# PRD: Phase 25 시장 컨텍스트 분리
> **상태**: ✅ 완료
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

기존 시장 컨텍스트는 KR과 US를 한 묶음으로 다룬다. `collect_market_data()`는 KOSPI와 KOSDAQ, NASDAQ, S&P 500을 함께 수집하지만 레짐은 KOSPI를 우선 사용하고, 미국 종목 분석에도 KOSPI 기반 bear 레짐이 직접 들어간 사례가 있다. 스냅샷에는 미국 대형주 시가총액이 KRW 억 단위처럼 보이는 값으로 남아 LLM이 직접 오류 가능성을 지적한다.

Phase 22 측정 계약은 market, calendar, timezone, benchmark context가 없으면 benchmark excess return을 `insufficient_context`로 둔다. Phase 25는 그 context를 시장별로 분리해 이후 snapshot, backfill, attribution, replay, calibration이 같은 시장 계약을 쓰게 한다.

## 목표

1. KR과 US 시장 식별자, exchange, calendar, timezone, session close를 명시한다.
2. benchmark mapping을 `KOSPI`는 `KS11`, `KOSDAQ`과 `KOSDAQ GLOBAL`은 `KQ11`, `NASDAQ`은 `IXIC`, `NYSE`는 `US500`으로 고정한다.
3. quote currency, base reporting currency, mixed portfolio FX normalization 경계를 분리한다.
4. ex-ante decision regime과 ex-post analysis regime을 별도 필드로 둔다.
5. KOSPI regime을 US 종목의 직접 regime으로 쓰는 경로를 차단한다.
6. 깨진 pykrx API를 기준 출처로 지정하지 않는다.

## 시장 식별자

| market | exchanges | ticker 예 | quote currency | base reporting currency | timezone | 정규 session close |
| --- | --- | --- | --- | --- | --- | --- |
| `KR` | `KOSPI`, `KOSDAQ`, `KOSDAQ GLOBAL` | `005930`, `035720` | `KRW` | `KRW` | `Asia/Seoul` | 한국거래소 calendar의 정규장 close, 보통 `15:30` |
| `US` | `NASDAQ`, `NYSE` | `MSFT`, `JPM` | `USD` | `KRW` | `America/New_York` | 미국 거래소 calendar의 정규장 close, 보통 `16:00` |

`market`은 국가권역이고 `exchange`는 benchmark, calendar, regime source를 고르는 키다. `KR`, `US`, `ALL` 같은 추천 요청 범위는 입력 universe 선택에만 쓰고, 개별 recommendation outcome은 항상 한 종목의 `market`과 `exchange`로 평가한다.

## Benchmark mapping

| exchange | benchmark_id | benchmark 이름 | excess return 가능 조건 | regime source |
| --- | --- | --- | --- | --- |
| `KOSPI` | `KS11` | KOSPI | entry와 target exit session의 `KS11` close가 모두 있음 | `KS11` |
| `KOSDAQ` | `KQ11` | KOSDAQ | entry와 target exit session의 `KQ11` close가 모두 있음 | `KQ11` |
| `KOSDAQ GLOBAL` | `KQ11` | KOSDAQ | entry와 target exit session의 `KQ11` close가 모두 있음 | `KQ11` |
| `NASDAQ` | `IXIC` | NASDAQ Composite | entry와 target exit session의 `IXIC` close가 모두 있음 | `IXIC` |
| `NYSE` | `US500` | S&P 500 | entry와 target exit session의 `US500` close가 모두 있음 | `US500` |

지원하지 않는 `exchange`이거나 target session의 benchmark close가 없으면 `gross_benchmark_excess_return_N`은 `insufficient_context`다. 이때 종목 entry와 exit 가격이 Phase 22 조건을 충족하면 `gross_absolute_return_N`은 별도 필드로 저장한다. benchmark 결측을 다른 시장 지수로 대체하지 않는다.

## Calendar, timezone, cutoff

| 필드 | 계약 |
| --- | --- |
| `calendar_id` | `KRX`, `NASDAQ`, `NYSE` 중 하나다. `KOSDAQ GLOBAL`은 `KRX` calendar를 쓴다. |
| `calendar_version` | holiday와 early close를 포함한 versioned artifact 식별자다. |
| `timezone` | market별 IANA timezone이다. 로컬 시스템 timezone 추정값을 쓰지 않는다. |
| `session_date` | 해당 exchange calendar의 거래일이다. |
| `regular_close_at` | early close를 반영한 ISO 8601 timestamp다. |
| `decision_data_cutoff_at` | 추천이 생성될 때 사용할 수 있었던 가장 늦은 source as-of다. `emitted_at`보다 미래일 수 없다. |
| `target_session_close_at` | Phase 22 N-session exit의 benchmark와 종목 종가 기준 timestamp다. |

entry와 exit session 계산은 Phase 22를 따른다. 추천 당일 최신 종가를 entry로 쓰지 않고, 추천 이후 다음 동일 시장 정규 session 종가를 entry로 쓴다. 조기 폐장일은 calendar가 제공하는 실제 close timestamp를 쓴다.

## Currency와 FX normalization

| 영역 | KR 종목 | US 종목 | 실패 처리 |
| --- | --- | --- | --- |
| quote price | `KRW` | `USD` | quote currency가 없으면 가격 context `blocked` |
| gross absolute return | quote currency 기준 비율 | quote currency 기준 비율 | FX가 없어도 계산 가능 |
| benchmark excess return | KRW 지수 비율 | USD 지수 비율 | benchmark context가 없으면 `insufficient_context` |
| portfolio market value | `KRW` | `USD` 가격에 USD/KRW 적용 | FX 결측 또는 stale이면 mixed portfolio exposure `degraded` |
| base reporting | `KRW` | `KRW` 환산값 병기 | stale FX로 비중, 총자산, concentration 산출 금지 |

수익률은 같은 quote currency 안의 비율이라 FX 없이 계산한다. 혼합 포트폴리오의 금액, 비중, 집중도, 현금 대비 exposure는 base reporting currency인 KRW로 정규화해야 한다. USD/KRW는 `fx_pair="USD_KRW"`, `fx_rate`, `fx_as_of`, `fx_source`, `fx_freshness_state`를 함께 저장한다.

FX freshness는 다음과 같다.

| 상태 | 조건 | 사용 가능 범위 |
| --- | --- | --- |
| `fresh` | `fx_as_of`가 decision session cutoff 안에 있고 source provenance가 있음 | portfolio normalization 가능 |
| `stale` | `fx_as_of`가 cutoff보다 오래됐거나 TTL 초과 | 종목 quote return은 가능, mixed portfolio value는 `degraded` |
| `missing` | USD/KRW 값을 얻지 못함 | 종목 quote return은 가능, mixed portfolio value는 `degraded` |

## Regime 계약

| 필드 | 의미 | 소비자 |
| --- | --- | --- |
| `decision_regime` | 추천 당시 사용할 수 있었던 benchmark series로 계산한 ex-ante regime | 관점, 합의, 신호 필터 |
| `decision_regime_source` | `KS11`, `KQ11`, `IXIC`, `US500` 중 exchange mapping 결과 | provenance와 차단 검사 |
| `decision_regime_as_of` | regime 계산에 쓰인 마지막 close timestamp | stale state 검사 |
| `analysis_regime` | entry 이후 target exit까지 실제 benchmark path로 분류한 ex-post regime | 성과 attribution과 리포트 |
| `cross_market_context` | 다른 시장 지수, FX, 금리, 원자재 같은 보조 매크로 값 | macro 관점 보조 설명 |

`decision_regime`은 반드시 해당 종목 exchange의 `regime_source`로 계산한다. `NASDAQ` 종목에는 `IXIC`, `NYSE` 종목에는 `US500`을 쓴다. KOSPI bear는 US 종목의 직접 decision regime이 될 수 없다. 필요하면 `cross_market_context.kr.KS11.regime="bear"`처럼 보조 정보로만 남긴다.

`analysis_regime`은 사후 성과를 설명하기 위한 값이다. 추천 당시 의사결정에는 쓰지 않는다. Phase 27 replay와 Phase 28 calibration은 `decision_regime`별 성과와 `analysis_regime`별 성과를 분리해 집계한다.

## Source와 freshness

| 데이터 | 기준 출처 | 보조 출처 | freshness 필드 | 금지 |
| --- | --- | --- | --- | --- |
| 종목 OHLCV와 현재가 | Toss Open API | pykrx, FinanceDataReader, yfinance | `price_as_of`, `price_source`, `price_freshness_state` | 출처 없는 최신가 대체 |
| 국내 지수 OHLCV | Toss Open API | FinanceDataReader `KS11`, `KQ11` | `benchmark_as_of`, `benchmark_source` | pykrx `get_index_ohlcv()` 기준 지정 |
| 미국 지수 OHLCV | FinanceDataReader | vendor adapter | `benchmark_as_of`, `benchmark_source` | KOSPI 지수 대체 |
| 시가총액 | Toss Open API | FinanceDataReader listing, yfinance | `market_cap_as_of`, `market_cap_currency`, `market_cap_unit` | pykrx `get_market_cap()` 기준 지정 |
| PER, PBR, 배당 | 네이버 금융, yfinance | 로컬 TTL 캐시 | `fundamental_as_of`, `fundamental_source` | pykrx `get_market_fundamental()` 기준 지정 |
| USD/KRW | Toss Open API | FinanceDataReader 과거 시계열 | `fx_as_of`, `fx_source` | 출처 없는 고정 환율 |

pykrx OHLCV fallback은 종목 가격 보조 소스일 수 있지만, `get_index_ohlcv()`, `get_market_cap()`, `get_market_fundamental()`은 알려진 깨진 API이므로 Phase 25 기준 출처가 아니다.

## Market-cap unit validation

| market | 허용 currency | 허용 unit | 정합성 검사 | 실패 상태 |
| --- | --- | --- | --- | --- |
| `KR` | `KRW` | `KRW`, `KRW_100M` | price, shares_outstanding, market_cap이 같은 currency로 맞음 | valuation feature `blocked` |
| `US` | `USD` | `USD`, `USD_M`, `USD_B` | USD quote price와 shares_outstanding으로 재계산한 값과 맞음 | valuation feature `blocked` |

US 종목의 시가총액이 `KRW_100M`처럼 들어오거나 Microsoft, JPM, AMGN 같은 대형주의 USD 가격과 발행주식수 규모에 맞지 않으면 valuation feature를 `blocked`로 둔다. 이 상태는 종목 가격 return이나 benchmark excess return을 막지 않는다. 다만 market-cap 기반 가치평가, concentration, size bucket은 계산하지 않는다.

## 상태 경계

| 상태 | 조건 | 허용 출력 | 차단 출력 |
| --- | --- | --- | --- |
| `matured` | market, exchange, calendar, benchmark, price, corporate action provenance가 충분함 | Phase 22 gross absolute, gross benchmark excess | 없음 |
| `insufficient_context` | market 식별 실패, exchange 미지원, benchmark mapping 부재, target benchmark close 결측 | gross absolute return 별도 저장 가능 | gross benchmark excess return |
| `degraded` | 보조 context가 결측 또는 stale이지만 Phase 22 primary context는 충분함 | quote return, benchmark excess, degradation reason | mixed portfolio value, freshness가 필요한 비중 |
| `blocked` | 단위 오염, 직접 regime 오용, quote currency 불명, 출처 금지 API 사용처럼 특정 feature 신뢰가 깨짐 | 영향을 받지 않는 별도 feature | 오염된 feature와 그 파생값 |

`degraded`와 `blocked`는 전체 recommendation을 자동 실패로 만들지 않는다. 영향을 받는 필드만 닫고, 닫힌 이유를 구조화해 Phase 23 snapshot과 Phase 26 attribution에 넘긴다.

## Market context schema

```json
{
  "schema_version": "v4.market_context.phase25.1",
  "ticker": "MSFT",
  "market": "US",
  "exchange": "NASDAQ",
  "calendar_id": "NASDAQ",
  "calendar_version": "exchange-calendars-2026.08",
  "timezone": "America/New_York",
  "quote_currency": "USD",
  "base_reporting_currency": "KRW",
  "benchmark_id": "IXIC",
  "benchmark_source": "FinanceDataReader",
  "benchmark_as_of": "2026-06-10T16:00:00-04:00",
  "decision_data_cutoff_at": "2026-06-02T16:00:00-04:00",
  "target_session_close_at": "2026-06-10T16:00:00-04:00",
  "decision_regime": "bull",
  "decision_regime_source": "IXIC",
  "decision_regime_as_of": "2026-06-02T16:00:00-04:00",
  "analysis_regime": "sideways",
  "analysis_regime_source": "IXIC",
  "fx_pair": "USD_KRW",
  "fx_rate": 1380.25,
  "fx_as_of": "2026-06-02T15:30:00+09:00",
  "fx_freshness_state": "fresh",
  "market_cap_currency": "USD",
  "market_cap_unit": "USD_B",
  "market_cap_validation_state": "valid",
  "context_state": "matured",
  "blocked_fields": [],
  "degraded_fields": [],
  "provenance_hashes": {
    "benchmark": "sha256:benchmark-fixture",
    "calendar": "sha256:calendar-fixture",
    "fx": "sha256:fx-fixture"
  }
}
```

## Fixture matrix

### F1. KOSPI happy path

```json
{
  "fixture_id": "kospi_context_matured",
  "ticker": "005930",
  "market": "KR",
  "exchange": "KOSPI",
  "calendar_id": "KRX",
  "timezone": "Asia/Seoul",
  "quote_currency": "KRW",
  "base_reporting_currency": "KRW",
  "benchmark_id": "KS11",
  "decision_regime_source": "KS11",
  "decision_regime": "sideways",
  "analysis_regime_source": "KS11",
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "benchmark_entry_close": 2500.0,
  "benchmark_exit_close": 2575.0,
  "instrument_entry_close": 100000.0,
  "instrument_exit_close": 106000.0,
  "gross_absolute_return_5": 0.06,
  "gross_benchmark_excess_return_5": 0.03,
  "context_state": "matured"
}
```

판정: Phase 22 F1과 같은 의미다. benchmark는 `KS11`이고 excess return은 `0.06 - 0.03 = 0.03`이다.

### F2. KOSDAQ happy path

```json
{
  "fixture_id": "kosdaq_context_matured",
  "ticker": "035720",
  "market": "KR",
  "exchange": "KOSDAQ",
  "calendar_id": "KRX",
  "timezone": "Asia/Seoul",
  "quote_currency": "KRW",
  "base_reporting_currency": "KRW",
  "benchmark_id": "KQ11",
  "decision_regime_source": "KQ11",
  "decision_regime": "bull",
  "analysis_regime_source": "KQ11",
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "benchmark_entry_close": 800.0,
  "benchmark_exit_close": 760.0,
  "instrument_entry_close": 50000.0,
  "instrument_exit_close": 52500.0,
  "gross_absolute_return_5": 0.05,
  "gross_benchmark_excess_return_5": 0.10,
  "context_state": "matured"
}
```

판정: KOSDAQ과 KOSDAQ GLOBAL은 모두 `KQ11`을 쓴다. benchmark가 `-0.05`라서 excess return은 `0.05 - (-0.05) = 0.10`이다.

### F3. NASDAQ happy path

```json
{
  "fixture_id": "nasdaq_context_matured",
  "ticker": "MSFT",
  "market": "US",
  "exchange": "NASDAQ",
  "calendar_id": "NASDAQ",
  "timezone": "America/New_York",
  "quote_currency": "USD",
  "base_reporting_currency": "KRW",
  "benchmark_id": "IXIC",
  "decision_regime_source": "IXIC",
  "decision_regime": "bull",
  "cross_market_context": {"KR": {"KS11": {"regime": "bear", "usage": "macro_context_only"}}},
  "fx_pair": "USD_KRW",
  "fx_rate": 1380.25,
  "fx_freshness_state": "fresh",
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "benchmark_entry_close": 17000.0,
  "benchmark_exit_close": 17170.0,
  "instrument_entry_close": 200.0,
  "instrument_exit_close": 190.0,
  "gross_absolute_return_5": -0.05,
  "gross_benchmark_excess_return_5": -0.06,
  "context_state": "matured"
}
```

판정: Phase 22 F2와 같은 의미다. KOSPI bear는 보조 매크로 context일 뿐이며 MSFT의 decision regime은 `IXIC`에서 온다.

### F4. NYSE happy path

```json
{
  "fixture_id": "nyse_context_matured",
  "ticker": "JPM",
  "market": "US",
  "exchange": "NYSE",
  "calendar_id": "NYSE",
  "timezone": "America/New_York",
  "quote_currency": "USD",
  "base_reporting_currency": "KRW",
  "benchmark_id": "US500",
  "decision_regime_source": "US500",
  "decision_regime": "bull",
  "analysis_regime_source": "US500",
  "fx_pair": "USD_KRW",
  "fx_rate": 1380.25,
  "fx_freshness_state": "fresh",
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "benchmark_entry_close": 6000.0,
  "benchmark_exit_close": 6060.0,
  "instrument_entry_close": 350.0,
  "instrument_exit_close": 367.5,
  "gross_absolute_return_5": 0.05,
  "gross_benchmark_excess_return_5": 0.04,
  "context_state": "matured"
}
```

판정: NYSE 종목은 S&P 500 proxy인 `US500`을 쓴다. NASDAQ Composite로 대체하지 않는다.

### F5. Unknown market failure

```json
{
  "fixture_id": "unknown_market_insufficient_context",
  "ticker": "7203.T",
  "market": "JP",
  "exchange": "TSE",
  "benchmark_id": null,
  "instrument_entry_close": 3000.0,
  "instrument_exit_close": 3150.0,
  "gross_absolute_return_5": 0.05,
  "gross_benchmark_excess_return_5": "insufficient_context",
  "context_state": "insufficient_context",
  "reason": "unsupported_market"
}
```

판정: 지원 시장이 아니므로 excess return은 만들지 않는다. 종목 quote return은 별도 보조값으로 남길 수 있다.

### F6. Missing benchmark at target session

```json
{
  "fixture_id": "missing_target_benchmark_insufficient_context",
  "ticker": "005930",
  "market": "KR",
  "exchange": "KOSPI",
  "benchmark_id": "KS11",
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "benchmark_entry_close": 2500.0,
  "benchmark_exit_close": null,
  "instrument_entry_close": 100000.0,
  "instrument_exit_close": 106000.0,
  "gross_absolute_return_5": 0.06,
  "gross_benchmark_excess_return_5": "insufficient_context",
  "context_state": "insufficient_context",
  "reason": "benchmark_missing_at_target_session"
}
```

판정: market과 exchange는 식별됐지만 target session의 benchmark close가 없다. 최신 `KS11`이나 `KQ11` 값으로 대체하지 않는다.

### F7. US market-cap KRW contamination

```json
{
  "fixture_id": "us_market_cap_krw_contamination_blocked",
  "ticker": "MSFT",
  "market": "US",
  "exchange": "NASDAQ",
  "quote_currency": "USD",
  "price": 492.81,
  "market_cap_value": 36593,
  "market_cap_currency": "KRW",
  "market_cap_unit": "KRW_100M",
  "benchmark_id": "IXIC",
  "gross_absolute_return_5": -0.05,
  "gross_benchmark_excess_return_5": -0.06,
  "context_state": "blocked",
  "blocked_fields": ["market_cap", "valuation_by_market_cap", "size_bucket"],
  "reason": "us_market_cap_currency_unit_mismatch"
}
```

판정: 시가총액 관련 feature만 차단한다. 가격 return과 benchmark excess return은 별도 provenance가 충분하면 유지한다.

### F8. KOSPI bear incorrectly applied to US

```json
{
  "fixture_id": "kospi_bear_direct_us_regime_blocked",
  "ticker": "JPM",
  "market": "US",
  "exchange": "NYSE",
  "benchmark_id": "US500",
  "decision_regime": "bear",
  "decision_regime_source": "KS11",
  "expected_decision_regime_source": "US500",
  "context_state": "blocked",
  "blocked_fields": ["decision_regime", "regime_filtered_signal", "regime_weight"],
  "reason": "cross_market_regime_used_as_direct_regime"
}
```

판정: US 종목의 직접 regime source가 `KS11`이면 차단한다. `KS11`은 `cross_market_context`로만 허용된다.

### F9. Stale or missing FX

```json
{
  "fixture_id": "stale_or_missing_fx_degraded",
  "ticker": "AMGN",
  "market": "US",
  "exchange": "NASDAQ",
  "quote_currency": "USD",
  "base_reporting_currency": "KRW",
  "benchmark_id": "IXIC",
  "fx_pair": "USD_KRW",
  "fx_rate": null,
  "fx_as_of": null,
  "fx_freshness_state": "missing",
  "gross_absolute_return_5": 0.04,
  "gross_benchmark_excess_return_5": 0.01,
  "context_state": "degraded",
  "degraded_fields": ["portfolio_market_value_krw", "position_weight", "concentration_check"],
  "reason": "fx_missing_for_base_reporting"
}
```

판정: quote 기준 수익률과 benchmark excess return은 계산 가능하다. KRW 환산 포트폴리오 값과 비중은 stale 또는 missing FX로 만들지 않는다.

## Acceptance criteria

1. 모든 v4 recommendation은 `market`, `exchange`, `calendar_id`, `timezone`, `quote_currency`, `base_reporting_currency`, `benchmark_id`, `decision_regime_source`를 가진다.
2. benchmark mapping은 `KOSPI→KS11`, `KOSDAQ→KQ11`, `KOSDAQ GLOBAL→KQ11`, `NASDAQ→IXIC`, `NYSE→US500`만 허용한다.
3. unknown market과 target benchmark 결측은 `gross_benchmark_excess_return_N="insufficient_context"`로 남기고 `gross_absolute_return_N`은 분리한다.
4. US 종목의 직접 decision regime source는 `IXIC` 또는 `US500`이어야 한다.
5. US market-cap KRW contamination은 market-cap 파생 feature를 `blocked`로 닫는다.
6. stale 또는 missing USD/KRW는 mixed portfolio normalization만 `degraded`로 닫고 quote return은 유지한다.
7. pykrx `get_index_ohlcv()`, `get_market_cap()`, `get_market_fundamental()`은 기준 출처가 아니다.
8. Phase 22의 entry, exit, state, gross absolute, gross benchmark excess 의미를 바꾸지 않는다.
