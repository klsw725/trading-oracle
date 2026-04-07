# AGENTS.md — Trading Oracle

> 코드를 읽으면 알 수 있는 것은 여기 적지 않는다. 여기에는 지뢰만 있다.

## 응답 언어

- 사용자에게는 항상 한국어로 답변할 것. 코드, 커밋 메시지, 식별자, 설정 키 이름은 기존 프로젝트 관례를 따른다.

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

## Codex provider 지뢰

- **Codex Responses API는 모델 제한 있음**. ChatGPT 계정 기반이라 `gpt-4.1-mini` 등 일부 모델은 400 에러. 기본값 `gpt-5.1-codex` 사용.
- **OAuth 토큰 경로**: `~/.trading-oracle/auth/codex.json`. 없으면 `~/.shacs-bot/auth/codex.json`에서 자동 복사. 둘 다 없으면 `uv run main.py codex-login` 필요.
- **`config.yaml`의 `llm.provider`가 `codex`일 때 `llm.model`은 Codex 모델명으로 변경 필요**. anthropic 모델명 그대로 두면 Codex API가 400 반환.

## 상태 파일

- **`data/portfolio.json`에 numpy 타입이 섞임**. pykrx/FDR이 반환하는 int64/float64가 포지션에 저장됨. `json.dumps` 시 `_NumEncoder` 없으면 `TypeError: Object of type int64 is not JSON serializable`. tracker.py와 main.py 양쪽에 별도 인코더 존재 — 통일되지 않음.
- **`PORTFOLIO_PATH`는 상대 경로 `Path("data/portfolio.json")`**. 프로젝트 루트가 아닌 다른 디렉토리에서 실행하면 파일을 못 찾거나 엉뚱한 곳에 생성. shacs-bot에서 호출 시 `cd` 필수.

## 코딩 행동 지침

> 속도보다 신중함에 비중을 둡니다. 사소한 작업은 상황에 맞게 판단하십시오.

### 1. 코딩 전에 생각하라

**가정하지 말 것. 혼란을 숨기지 말 것. 트레이드오프를 드러낼 것.**

- 자신의 가정을 명시적으로 밝혀라. 확실하지 않다면 질문하라.
- 해석이 여러 가지라면 모두 제시하라 — 임의로 하나를 선택하지 마라.
- 더 단순한 접근 방식이 있다면 반드시 언급하라. 필요하면 합리적으로 반박하라.
- 무엇인가 불분명하다면 멈춰라. 무엇이 헷갈리는지 명확히 말하고 질문하라.

### 2. 단순함 우선

**문제를 해결하는 최소한의 코드만 작성하라. 추측성 구현 금지.**

- 요청되지 않은 기능은 추가하지 마라.
- 단일 용도의 코드를 위해 불필요한 추상화를 만들지 마라.
- 요청되지 않은 "유연성"이나 "설정 가능성"을 추가하지 마라.
- 발생할 수 없는 시나리오를 위한 에러 처리를 만들지 마라.
- 200줄을 썼는데 50줄로 가능하다면 다시 작성하라.

> "시니어 엔지니어가 이 코드를 과도하게 복잡하다고 말할까?" — 그렇다면 단순화하라.

### 3. 외과적 변경

**정말 필요한 부분만 수정하라. 자신의 변경으로 생긴 것만 정리하라.**

- 주변 코드, 주석, 포맷을 "개선"하지 마라.
- 고장 나지 않은 것을 리팩토링하지 마라.
- 본인이 선호하는 스타일이 있더라도 기존 스타일에 맞춰라.
- 관련 없는 데드 코드가 보이면 언급만 하고 삭제하지 마라.
- 본인의 변경으로 사용되지 않게 된 import/변수/함수는 제거하라.
- 기존에 존재하던 데드 코드는 요청받지 않았다면 제거하지 마라.

> 모든 변경된 라인은 사용자의 요청과 직접적으로 연결되어야 한다.

### 4. 목표 중심 실행

**성공 기준을 정의하고, 검증될 때까지 반복하라.**

작업을 검증 가능한 목표로 변환하라:
- "유효성 검증 추가" → "잘못된 입력에 대한 테스트를 작성하고 통과시키기"
- "버그 수정" → "버그를 재현하는 테스트를 작성하고 통과시키기"
- "X 리팩토링" → "리팩토링 전후 테스트가 모두 통과하는지 확인하기"

## 작업 기록

- 작업 완료 후, 자신의 변경이 사용자 문서/README/스펙/PRD/CLI 사용법/설정 가이드에 영향을 주면 관련 문서를 같은 작업 안에서 함께 업데이트할 것.
- 작업 완료 후 docs/ 폴더에 변경 사항을 요약하여 마크다운 파일로 기록할 것
- 위 작업 기록 문서는 로컬 작업 추적용이다. git에 추가하거나 커밋하지 말 것. `git add -f` 사용 금지.
- 파일명 형식: YYYY-MM-DD-HH-mm-작업내용.md (예: 2026-02-03-20-04-평가파이프라인-수정.md)
- 사용자가 입력한 프롬프트도 함께 기록하여 재현 가능하도록 관리할 것
