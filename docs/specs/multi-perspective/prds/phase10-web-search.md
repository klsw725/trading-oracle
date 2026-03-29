# PRD: Phase 10 — 웹 검색 보강 (DuckDuckGo + OUROBOROS 검증)

> **SPEC 참조**: [SPEC.md](../SPEC.md)
> **상태**: ✅ 완료 (M1~M5 구현)
> **우선순위**: P0 — LLM 관점의 정확도를 구조적으로 개선하는 핵심 경로
> **선행 조건**: Phase 1 (다관점 시스템) 완료
> **의존성**: `ddgs` (구 `duckduckgo-search`) — API 키 불필요, MIT 라이선스
> **참고**: OUROBOROS 프레임워크의 Triple-Gate, Sector MESH, Dilution Dragnet 설계를 차용

---

## 문제

현재 LLM 관점(이광수, 포렌식, 매크로, 가치)은 프롬프트에 OHLCV + PER/PBR만 제공받고, 나머지는 **LLM의 학습 데이터(과거 지식)**에 의존하여 판단한다.

### 문제의 구체적 양상

| 관점 | 현재 동작 | 문제 |
|------|----------|------|
| 포렌식 (ouroboros) | "유상증자 이력 확인하세요" → LLM이 추측 | 학습 컷오프 이후 공시를 모름. **할루시네이션 리스크** |
| 매크로 (macro) | "금리 방향"을 학습 지식으로 판단 | 어제 FOMC 결정을 반영 못 함 |
| 이광수 (kwangsoo) | 차트 패턴 + 학습 지식 | 최근 뉴스 모멘텀(실적 서프라이즈 등) 미반영 |
| 가치 (value) | PER/PBR은 있으나 컨센서스 없음 | 업종 평균 PER을 LLM이 "추정" (부정확) |

**백테스트 결과**: 시그널 단독으로는 미장에서 엣지 없음 확인. LLM 관점의 정확도가 시스템 전체 성능의 병목.

---

## 솔루션 개요

DuckDuckGo 검색(`ddgs` 패키지)으로 **종목별 최신 뉴스/정보를 수집**하여 각 관점의 LLM 프롬프트에 삽입.

### 아키텍처

```
analyze_ticker()
  ├─ fetch_ohlcv()           ← 기존
  ├─ compute_signals()       ← 기존
  ├─ fetch_fundamentals()    ← 기존
  └─ search_ticker_context() ← 신규 (Phase 10)
        ├─ 뉴스 검색 (ddgs.news)
        ├─ 웹 검색 (ddgs.text) — 공시, 수급, 섹터 정보
        └─ 결과 요약 → PerspectiveInput.web_context

run_all_perspectives()
  ├─ kwangsoo: user_prompt += web_context.news
  ├─ ouroboros: user_prompt += web_context.disclosure + web_context.news
  ├─ macro: user_prompt += web_context.macro + web_context.sector
  ├─ value: user_prompt += web_context.consensus
  └─ quant: 변화 없음 (순수 계산)
```

### 설계 원칙

1. **실패 허용**: 검색 실패 시 현재 동작과 동일 (web_context 없이 진행). 검색은 **보강**이지 필수가 아님.
2. **비용 0**: DuckDuckGo는 API 키 불필요, 무료. 단, rate limit 존재 (과도한 호출 시 차단).
3. **토큰 절약**: 검색 결과를 그대로 프롬프트에 넣지 않음. 제목+스니펫만 사용, 최대 10건.
4. **캐시**: 같은 종목을 같은 날 재검색하지 않음 (일일 TTL).
5. **언어 적응**: 한국 종목은 한국어, 미국 종목은 영어로 검색.

---

## 마일스톤

### M1: 검색 인프라 + OUROBOROS 검증 엔진 (`src/data/web_search.py`)

신규 모듈 생성. OUROBOROS 프레임워크의 Sector MESH, Triple-Gate 검증, Dilution Dragnet을 통합.

#### 핵심 함수

```python
def search_ticker_context(ticker: str, name: str, sector: str = "", is_us: bool = False) -> dict:
    """종목 관련 웹 컨텍스트 수집 (OUROBOROS 강화).

    Returns:
        {
            "news": [{"title": "...", "snippet": "...", "date": "...", "url": "..."}],
            "forensic": {
                "dilution": [{"title": "...", "snippet": "..."}],
                "insider": [{"title": "...", "snippet": "..."}],
                "short_interest": [{"title": "...", "snippet": "..."}],
            },
            "flow": [{"title": "...", "snippet": "..."}],
            "sector_deep": [{"title": "...", "snippet": "..."}],
            "consensus": [{"title": "...", "snippet": "..."}],
            "searched_at": "2026-03-29T10:00:00",
            "gate_stats": {"total": 22, "passed": 18, "rejected": 4},
        }
    """
```

#### 검색 쿼리 설계 (기본 + OUROBOROS 강화)

**기본 쿼리 (전 종목 공통)**:

| 카테고리 | 한국 종목 쿼리 | 미국 종목 쿼리 | 방식 |
|---------|-------------|-------------|-----|
| **뉴스** | `"{종목명}" 주식` | `"{ticker}" stock` | `news(max=7, timelimit="w")` |
| **수급** | `"{종목명}" 외국인 OR 기관 수급` | `"{ticker}" institutional ownership 13F` | `text(max=5)` |
| **컨센서스** | `"{종목명}" 목표주가 컨센서스` | `"{ticker}" price target analyst consensus` | `text(max=5)` |

**포렌식 쿼리 (OUROBOROS Dilution Dragnet 차용)**:

| 카테고리 | 한국 종목 쿼리 | 미국 종목 쿼리 |
|---------|-------------|-------------|
| **희석 리스크** | `"{종목명}" 유상증자 OR 전환사채 OR CB OR BW OR 신주인수권` | `"{ticker}" ATM offering OR convertible note OR PIPE OR warrant OR dilution` |
| **내부자** | `"{종목명}" 대주주 OR 임원 매도 OR 매수 OR 지분 변동` | `"{ticker}" insider trading Form 4 purchase sale` |
| **공매도** | `"{종목명}" 공매도 OR 대차잔고` | `"{ticker}" short interest cost to borrow` |

**섹터 특화 쿼리 (OUROBOROS Sector MESH 차용)**:

```python
SECTOR_MESH = {
    "반도체": [
        "{name} HBM AI server demand",
        "{name} 메모리 가격 전망 디램 낸드",
    ],
    "바이오": [
        "{name} 임상 FDA 승인 결과",
        "{name} 파이프라인 특허 만료",
    ],
    "자동차": [
        "{name} 전기차 판매량 수주",
        "{name} 배터리 공급망",
    ],
    "방산": [
        "{name} 수주 잔고 계약",
        "{name} 국방 예산 NATO",
    ],
    "금융": [
        "{name} NIM 순이자마진 금리",
        "{name} 부실채권 건전성",
    ],
    "플랫폼": [
        "{name} MAU 광고 매출",
        "{name} AI 도입 비용 마진",
    ],
    # 미국 섹터 (영어)
    "TECH": [
        "{ticker} AI revenue cloud growth",
        "{ticker} margin pressure competition",
    ],
    "EV": [
        "{ticker} delivery numbers production",
        "{ticker} battery supply chain cost",
    ],
    "SAAS": [
        "{ticker} ARR NRR churn rate",
        "{ticker} AI integration margin impact",
    ],
    "PHARMA": [
        "{ticker} FDA approval clinical trial",
        "{ticker} patent cliff generic competition",
    ],
    "FINTECH": [
        "{ticker} delinquency rate loan loss",
        "{ticker} regulation compliance cost",
    ],
}
```

섹터 감지: `get_ticker_name()` 결과 + 종목명 키워드 매칭으로 섹터 자동 판별.

#### Triple-Gate 검증 (OUROBOROS 차용)

모든 검색 결과는 3중 필터를 거침:

```python
def _triple_gate(result: dict, query_type: str) -> bool:
    """OUROBOROS Triple-Gate: 시간/맥락/이상치 검증.
    
    Returns True if result passes all gates.
    """
    # Gate 1: Time Gate — 오래된 결과 폐기
    date = result.get("date", "")
    if query_type == "news" and _days_old(date) > 14:
        return False  # 2주 이상 뉴스 폐기
    if query_type in ("forensic", "flow") and _days_old(date) > 90:
        return False  # 90일 이상 공시/수급 폐기

    # Gate 2: Context Gate — 맥락 오인 방지
    title = result.get("title", "")
    snippet = result.get("snippet", "")
    # "52주 최저", "역대 최고" 등 맥락 오인 필터
    if _is_misleading_context(title + snippet):
        return False

    # Gate 3: Relevance Gate — 종목 무관 결과 필터
    # 종목명/티커가 제목이나 스니펫에 없으면 폐기
    if not _contains_target(title + snippet, ticker, name):
        return False

    return True
```

- [ ] `ddgs` 패키지 의존성 추가 (`pyproject.toml`)
- [ ] `search_ticker_context()` 구현 (기본 + 포렌식 + 섹터 MESH)
- [ ] `SECTOR_MESH` 사전 구현 (한국 6섹터 + 미국 5섹터)
- [ ] `_triple_gate()` 검증 로직 구현
- [ ] 일일 캐시 (`data/web_cache.json`, 날짜별 TTL)
- [ ] rate limit 보호 (검색 간 0.5초 sleep, 3회 연속 실패 시 스킵)
- [ ] 실패 시 빈 dict 반환 (예외 전파 안 함)
- [ ] `gate_stats` 반환 (통과/거부 건수 — 검색 품질 모니터링용)

**검증**: 삼성전자, AAPL 검색 → Triple-Gate 통과율 70%+ 확인. 최근 7일 뉴스 포함 확인.

### M2: PerspectiveInput 확장

`PerspectiveInput`에 `web_context` 필드 추가.

```python
@dataclass
class PerspectiveInput:
    ticker: str
    name: str
    ohlcv: pd.DataFrame
    signals: dict
    fundamentals: dict
    position: dict | None
    market_context: dict
    config: dict
    web_context: dict = field(default_factory=dict)  # 신규
```

- [ ] `PerspectiveInput`에 `web_context` 필드 추가
- [ ] `analyze_ticker()`에서 `search_ticker_context()` 호출 후 결과 포함
- [ ] `run_multi_perspective()`에서 `web_context` 전달 경로 확인

**검증**: `PerspectiveInput.web_context`에 검색 결과가 정상 전달되는지 확인.

### M3: 관점 프롬프트 연동

4개 관점의 `_build_user_prompt()`에 `web_context` 삽입.

#### 이광수 관점 (`kwangsoo.py`)
```
### 최근 뉴스
- [2026-03-28] 삼성전자, HBM 수주 확대… AI 반도체 수혜
- [2026-03-27] 외국인 5거래일 연속 순매수
```
→ 뉴스 모멘텀을 추적 손절매/주도주 판단에 반영.

#### 포렌식 감사관 (`ouroboros.py`) — OUROBOROS 강화

```
### 희석 리스크 스캔 (웹 검색 기반 — 추측 아님)
- "유상증자" 검색: 0건 → ✅ 클린
- "전환사채/CB" 검색: 0건 → ✅ 클린
- "신주인수권/워런트" 검색: 0건 → ✅ 클린

### 내부자 거래 (웹 검색)
- [2026-03-20] 삼성전자 부회장, 주식 10만주 매수 (장내)
- 최근 90일 임원 매도 건수: 0건

### 기관/외국인 수급 (웹 검색)
- 외국인 5거래일 연속 순매수 (약 3,200억원)
- 국민연금 보유비율 변동 없음

### 공매도/대차 (웹 검색)
- 공매도 잔고 비율: 0.3% (낮음)

### 최근 뉴스 (리스크 확인용)
- [2026-03-28] 삼성전자, HBM 수주 확대… AI 반도체 수혜
- [2026-03-25] 삼성전자 사외이사 3명 사임
```

→ 추측 대신 **실제 공시/수급/공매도 데이터** 기반 판정.
→ OUROBOROS의 "Dilution Dragnet" + "Devil's Advocate"를 검색 데이터로 구동.
→ 각 희석 카테고리별 검색 건수를 ✅/⚠️로 명시하여 **투명성 보장**.

#### 매크로 인과 (`macro.py`)
```
### 매크로 최신 동향
- [2026-03-28] 미 연준 금리 동결, 6월 인하 시사
- [2026-03-27] 디램 고정거래가 4개월 연속 상승
### 섹터 동향
- 반도체 섹터: AI 투자 확대 → HBM 수요 증가 추세
```
→ **학습 컷오프 이후** 매크로 이벤트 반영.

#### 가치 투자 (`value.py`)
```
### 밸류에이션 참고
- 삼성전자 컨센서스 목표주가: 200,000원 (현재가 대비 +11%)
- 업종 평균 PER: 15.2 (검색 결과 기반)
```
→ LLM이 "추정"하던 업종 평균을 **실제 데이터**로 교체.

- [ ] 4개 관점 `_build_user_prompt()`에 web_context 삽입 로직
- [ ] `web_context`가 비어있으면 해당 섹션 생략 (기존 동작 유지)
- [ ] 프롬프트 토큰 제한: 뉴스는 최대 7건, 각 제목+스니펫 100자 제한

**검증**: 실제 `daily.py` 실행하여 프롬프트에 최신 뉴스가 삽입되는지 확인. LLM 응답에서 뉴스 내용을 인용하는지 확인.

### M4: 매크로 글로벌 검색

종목별 검색과 별도로, **시장 전체** 매크로 컨텍스트를 1회 검색.

```python
def search_market_context(include_us: bool = False) -> dict:
    """시장 전체 매크로 컨텍스트.

    Returns:
        {
            "kr_macro": [...],  # "한국 주식시장 전망" 뉴스
            "us_macro": [...],  # "US stock market outlook" 뉴스
            "rates": [...],     # 금리 관련
            "fx": [...],        # 환율 관련
        }
    """
```

- [ ] `search_market_context()` 구현
- [ ] `collect_market_data()`에 통합 (market_data에 `web_macro` 필드 추가)
- [ ] 매크로 관점에 시장 전체 컨텍스트도 전달

**검증**: 시장 레짐 판정과 웹 매크로 뉴스가 일관되는지 확인.

### M5: config 옵션 + 문서

- [ ] `config.yaml`에 웹 검색 관련 설정 추가
  ```yaml
  web_search:
    enabled: true           # false로 끄면 기존 동작
    max_news: 7             # 뉴스 최대 건수
    max_text: 5             # 텍스트 검색 최대 건수
    cache_ttl_hours: 12     # 캐시 TTL (시간)
    rate_limit_sec: 0.5     # 검색 간 대기 시간
  ```
- [ ] `--no-search` CLI 옵션 추가 (main.py, daily.py)
- [ ] SPEC.md, SKILL.md 갱신
- [ ] docs/ 작업 기록

---

## 영향 범위

### 직접 변경

| 파일 | 변경 내용 |
|------|----------|
| `pyproject.toml` | `ddgs` 의존성 추가 |
| `src/data/web_search.py` | **신규** — 검색 + 캐시 |
| `src/perspectives/base.py` | `PerspectiveInput.web_context` 필드 추가 |
| `src/perspectives/kwangsoo.py` | user_prompt에 뉴스 삽입 |
| `src/perspectives/ouroboros.py` | user_prompt에 공시+수급 삽입 |
| `src/perspectives/macro.py` | user_prompt에 매크로+섹터 삽입 |
| `src/perspectives/value.py` | user_prompt에 컨센서스 삽입 |
| `src/common.py` | `analyze_ticker()`에 웹 검색 추가, `collect_market_data()`에 매크로 검색 |
| `config.yaml` | `web_search` 섹션 추가 |
| `main.py` / `scripts/daily.py` | `--no-search` 옵션 |

### 변경 불필요

| 파일 | 이유 |
|------|------|
| `src/signals/technical.py` | 시그널 계산은 OHLCV만 사용 |
| `src/consensus/scorer.py` | PerspectiveResult만 소비 |
| `src/consensus/voter.py` | PerspectiveInput 전달만 |
| `src/performance/tracker.py` | 스냅샷은 verdict만 저장 |
| `scripts/backtest.py` | 시그널 백테스트는 웹 검색 불필요 |

---

## 검색 쿼리 상세 설계

### 한국 종목 (예: 삼성전자 005930)

```python
queries = {
    # 기본
    "news": {"q": "삼성전자 주식", "method": "news", "max": 7, "timelimit": "w"},
    "flow": {"q": "삼성전자 외국인 OR 기관 순매수 OR 순매도 수급", "method": "text", "max": 5},
    "consensus": {"q": "삼성전자 목표주가 OR 컨센서스 OR 투자의견", "method": "text", "max": 5},
    # 포렌식 (OUROBOROS Dilution Dragnet)
    "dilution": {"q": "삼성전자 유상증자 OR 전환사채 OR CB OR BW OR 신주인수권 OR 분할", "method": "text", "max": 5},
    "insider": {"q": "삼성전자 대주주 OR 임원 매도 OR 매수 OR 지분 변동", "method": "text", "max": 5},
    "short": {"q": "삼성전자 공매도 OR 대차잔고", "method": "text", "max": 3},
    # 섹터 MESH (자동 감지)
    "sector_0": {"q": "삼성전자 HBM AI server demand", "method": "text", "max": 3},
    "sector_1": {"q": "삼성전자 메모리 가격 전망 디램 낸드", "method": "text", "max": 3},
}
# 종목당 총 8~10쿼리 × 0.5초 = 4~5초
```

### 미국 종목 (예: AAPL)

```python
queries = {
    # 기본
    "news": {"q": "AAPL Apple stock", "method": "news", "max": 7, "timelimit": "w"},
    "flow": {"q": "AAPL institutional ownership 13F hedge fund", "method": "text", "max": 5},
    "consensus": {"q": "AAPL price target analyst consensus", "method": "text", "max": 5},
    # 포렌식 (OUROBOROS)
    "dilution": {"q": "AAPL ATM offering OR convertible note OR PIPE OR warrant OR dilution", "method": "text", "max": 5},
    "insider": {"q": "AAPL insider trading Form 4 purchase sale SEC", "method": "text", "max": 5},
    "short": {"q": "AAPL short interest cost to borrow shares available", "method": "text", "max": 3},
    # 섹터 MESH (TECH)
    "sector_0": {"q": "AAPL AI revenue services growth", "method": "text", "max": 3},
    "sector_1": {"q": "AAPL margin pressure competition antitrust", "method": "text", "max": 3},
}
```

### 시장 매크로

```python
queries = {
    "kr_macro": {"q": "한국 주식시장 전망 금리 환율 코스피", "method": "news", "max": 5, "timelimit": "w"},
    "us_macro": {"q": "US stock market outlook Fed interest rate S&P500", "method": "news", "max": 5, "timelimit": "w"},
    "rates": {"q": "기준금리 FOMC 결정 최신", "method": "news", "max": 3, "timelimit": "w"},
    "fx": {"q": "원달러 환율 전망", "method": "news", "max": 3, "timelimit": "w"},
}
```

---

## 프롬프트 삽입 형식

각 관점에 삽입되는 웹 컨텍스트 포맷:

```
### 최근 뉴스 (웹 검색 {검색일})
- [{날짜}] {제목} — {스니펫 100자}
- [{날짜}] {제목} — {스니펫 100자}
...

### 공시/리스크 정보 (웹 검색)
- {제목} — {스니펫 100자}
- "유상증자" 검색 결과 {N}건 / "전환사채" 검색 결과 {N}건
...
```

**토큰 예산**: 관점당 웹 컨텍스트 최대 ~500 토큰. 7건 뉴스 × (제목 30자 + 스니펫 100자) ≈ 약 400 토큰.

---

## 캐시 설계

```json
// data/web_cache.json
{
  "005930": {
    "searched_at": "2026-03-29T09:00:00",
    "news": [...],
    "disclosure": [...],
    "flow": [...],
    "consensus": [...]
  },
  "_market": {
    "searched_at": "2026-03-29T09:00:00",
    "kr_macro": [...],
    "us_macro": [...]
  }
}
```

- TTL: 12시간 (config 조정 가능)
- 종목별 캐시 키: ticker
- 시장 매크로: `_market` 키

---

## Rate Limit 보호

DuckDuckGo는 공식 API가 아닌 스크래핑 기반. 과도한 호출 시 일시 차단 가능.

- 검색 간 `0.5초` sleep (config 조정 가능)
- 종목당 쿼리 수: 기본 3 + 포렌식 3 + 섹터 MESH 2 = **8~10쿼리**
- 5종목 분석 시: 종목당 10쿼리 × 5 + 시장 4쿼리 = **54쿼리 × 0.5초 = 27초**
- 실패 시 해당 카테고리만 빈 리스트, 전체 실패하지 않음
- **3회 연속 실패 시 나머지 쿼리 스킵** (차단 감지 → 캐시된 이전 결과 사용)
- 캐시 히트 시 검색 안 함 → 2회차 실행부터는 0초

---

## 비용

- DuckDuckGo 검색: **$0** (무료)
- LLM 토큰 증가: 관점당 ~500 토큰 × 4개 관점 = ~2,000 토큰 추가
  - Sonnet 기준: ~$0.006/실행 추가 (월 $0.18)
  - Codex 기준: 무시 가능

---

## 리스크

| 리스크 | 확률 | 영향 | 대응 |
|--------|------|------|------|
| DuckDuckGo 차단 (rate limit) | 중 | 검색 실패 → 기존 동작 | sleep + 실패 허용 + 3회 연속 실패 시 스킵 |
| 검색 결과 품질 낮음 (무관 뉴스) | 중 | 프롬프트 노이즈 | **Triple-Gate 검증** (시간/맥락/관련성) |
| `ddgs` 패키지 업데이트 깨짐 | 저 | import 실패 | 버전 핀 + 실패 허용 |
| LLM이 검색 결과를 할루시네이션에 활용 | 저 | 잘못된 분석 | "아래 검색 결과만 참조" 프롬프트 지시 |
| 포렌식 쿼리에서 거짓 양성 (dilution) | 중 | 과도한 리스크 경고 | 검색 건수만 보고 + LLM이 맥락 판단 |
| 섹터 오분류 | 저 | 무관한 MESH 쿼리 | 기본 쿼리는 항상 실행, MESH는 보조 |

---

## 검증 프로토콜

### 정성적 검증 (M3 완료 후)

1. 삼성전자 + AAPL 다관점 분석 실행 (`daily.py`)
2. 각 관점 응답에서 **웹 검색 결과를 인용**하는지 확인
3. 포렌식 관점이 "추측"이 아닌 "검색 결과 기반"으로 판정하는지 확인
4. 매크로 관점이 최근 금리 결정을 반영하는지 확인

### 정량적 검증 (스냅샷 축적 후)

1. 웹 검색 ON/OFF 두 버전으로 동일 종목 분석
2. 30일 후 `performance.py report`로 적중률 비교
3. 목표: 웹 검색 ON이 OFF 대비 **합의 적중률 5%p+ 개선**

---

## 일정 (예상)

| 마일스톤 | 예상 작업량 | 누적 |
|---------|-----------|------|
| M1 (검색 인프라) | 40분 | 40분 |
| M2 (PerspectiveInput 확장) | 15분 | 55분 |
| M3 (관점 프롬프트 연동) | 40분 | 1시간 35분 |
| M4 (매크로 글로벌 검색) | 20분 | 1시간 55분 |
| M5 (config + 문서) | 15분 | 2시간 10분 |

---

## OUROBOROS 통합 요약

Phase 10은 OUROBOROS 프레임워크의 다음 요소를 차용:

| OUROBOROS 기능 | Phase 10 적용 | 적용 위치 |
|---|---|---|
| **Triple-Gate** (시간/맥락/이상치) | `_triple_gate()` 함수 — 검색 결과 품질 필터 | M1 |
| **Sector MESH** (10개 섹터 키워드) | `SECTOR_MESH` 사전 — 섹터 감지 후 특화 쿼리 | M1 |
| **Dilution Dragnet** (희석 전수조사) | 포렌식 쿼리 3종 (희석/내부자/공매도) | M1, M3 |
| **Devil's Advocate** (기관 매도 역설계) | 검색 데이터 기반 역설계 (추측 제거) | M3 |
| **Smart Money Filter** | 기관 수급 검색 + 공매도 데이터 | M1, M3 |

**포팅하지 않은 것**: 2단계 인터랙션 (자동화와 불일치), Google site: 연산자 (DuckDuckGo 제한), 수십 회 반복 검색 (rate limit 위험).

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-29 | 백테스트 기반 분석 → 웹 검색 보강 필요성 확인. PRD 작성. |
| 2026-03-29 | OUROBOROS 프레임워크 분석 → Sector MESH, Triple-Gate, Dilution Dragnet 통합하여 PRD 강화. |
