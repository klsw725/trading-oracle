# AGENTS.md — Trading Oracle

> 코드를 읽으면 알 수 있는 것은 여기 적지 않는다. 여기에는 지뢰만 있다.

## 툴링

- **`uv` 전용**. `pip install` 절대 금지. 의존성: `uv sync`, 실행: `uv run main.py`. `.python-version`은 3.14.2.
- **린터/포매터/테스트 없음**. pyproject.toml에 ruff/pytest 설정 없음. 존재하지 않는 인프라를 찾거나 실행하려 하지 말 것.
- **`setuptools<81` 필수**. pykrx가 `pkg_resources`에 의존. setuptools 81+에서는 import 시 즉시 크래시. pyproject.toml에 핀돼 있으니 건드리지 말 것.

## 데이터 소스 지뢰

- **pykrx `get_market_fundamental()`과 `get_market_cap()`은 깨져 있음**. 현재 pandas와 컬럼명 불일치로 KeyError 발생. `fetch_fundamentals()`는 market.py에 남아 있지만 main.py에서 호출하지 않음. 펀더멘털은 `src/data/fundamentals.py`의 네이버 스크래핑으로, 시총은 `fdr.StockListing('KRX')`로 대체해서 사용 중.
- **pykrx `get_index_ohlcv()`도 깨져 있음**. 지수 OHLCV는 `FinanceDataReader.DataReader('KS11', ...)` 사용. pykrx의 지수 API 호출하면 KeyError.
- **pykrx OHLCV 컬럼은 6개**. `['시가','고가','저가','종가','거래량','등락률']` → rename to `['open','high','low','close','volume','change_pct']`. 7개로 가정하면 ValueError.
- **네이버 금융 PER/PBR은 `em` 태그의 `id` 속성으로 추출**. `id="_per"`, `id="_pbr"`. 네이버가 HTML 구조를 바꾸면 즉시 깨짐. regex가 아닌 id 기반 파싱.

## Anthropic SDK 지뢰

- **`client.messages.create()`가 `str`을 반환함**. 이 환경에서 Anthropic SDK가 파싱된 Message 객체 대신 raw SSE 스트림 문자열을 반환. `oracle.py`의 `_parse_sse_response()`가 `text_delta` 이벤트를 추출해서 텍스트로 조립함. `response.content[0].text` 접근 전 반드시 `isinstance(response, str)` 체크 필요.

## argparse 지뢰

- **help 문자열에 `%` 리터럴 쓰면 크래시**. Python 3.14의 argparse가 help 문자열을 `%` 포맷팅함. `"기본: -10%"` → ValueError. `"기본 매수가의 90%%"` 처럼 이스케이프 필수.

## 상태 파일

- **`data/portfolio.json`에 numpy 타입이 섞임**. pykrx/FDR이 반환하는 int64/float64가 포지션에 저장됨. `json.dumps` 시 `_NumEncoder` 없으면 `TypeError: Object of type int64 is not JSON serializable`. tracker.py와 main.py 양쪽에 별도 인코더 존재 — 통일되지 않음.
- **`PORTFOLIO_PATH`는 상대 경로 `Path("data/portfolio.json")`**. 프로젝트 루트가 아닌 다른 디렉토리에서 실행하면 파일을 못 찾거나 엉뚱한 곳에 생성. shacs-bot에서 호출 시 `cd` 필수.
