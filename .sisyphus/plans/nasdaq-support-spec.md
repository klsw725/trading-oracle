# 나스닥(미국 시장) 지원 — 스펙

## 설계: B안 — 티커 포맷 자동 판별

한국 종목: 6자리 숫자 (`005930`), 미국 종목: 알파벳 (`AAPL`, `MSFT`).
`is_us_ticker(ticker)` 유틸리티 하나로 전체 파이프라인 분기.

## 변경 파일

### 1. `pyproject.toml` — yfinance 의존성 추가

### 2. `src/data/market.py` — US 시장 데이터 함수 추가
- `is_us_ticker(ticker)`: 알파벳이면 US
- `fetch_ohlcv()`: US 티커 → `fdr.DataReader(ticker, start)`
- `get_ticker_name()`: US 티커 → `fdr.StockListing('NASDAQ')` + `fdr.StockListing('NYSE')` 캐싱
- `fetch_market_cap()`: US 티커 → yfinance `info['marketCap']`

### 3. `src/data/fundamentals.py` — yfinance 기반 US 펀더멘털
- `fetch_us_fundamentals(ticker)`: yfinance로 PER/PBR/배당수익률
- `fetch_naver_fundamentals()`, `fetch_fundamentals_cached()`: US 티커면 자동으로 yfinance 경로

### 4. `src/common.py` — 시장 데이터 수집 확장
- `collect_market_data()`: 포트폴리오/워치리스트에 US 티커가 있으면 나스닥/S&P500 지수도 수집
- `analyze_ticker()`: US 티커 시 펀더멘털 경로 분기 (이미 fundamentals.py에서 처리)

### 5. `src/screener/leading.py` — US 스크리닝 지원
- `screen_leading_stocks(market="NASDAQ")` 추가

### 6. `src/agent/prompts.py` — US 지수 표시
- 나스닥/S&P500 지수가 market_data에 있으면 프롬프트에 포함

### 변경하지 않는 것
- `src/signals/technical.py` — OHLCV 기반이므로 시장 무관
- `src/consensus/` — 시장 무관
- `src/perspectives/` — 시장 무관 (입력 데이터가 동일 포맷이면)
- `src/portfolio/tracker.py` — 티커만 저장하므로 시장 무관

## 성공 기준
1. `uv run main.py -t AAPL MSFT` → 미국 종목 분석 정상 작동
2. `uv run main.py add AAPL 200 10` → 포트폴리오에 추가
3. 한국+미국 혼합 포트폴리오 분석 가능
4. US 펀더멘털(PER/PBR) yfinance에서 정상 수집
