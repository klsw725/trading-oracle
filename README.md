# 🔮 Trading Oracle — 다관점 투자 판정 에이전트

5개 독립 투자 관점(이광수 철학, 포렌식 감사관, 퀀트 시그널, 매크로 인과, 가치 투자)이 병렬 판정하고, 합의도 시스템(MAXS-lite)으로 종합하여 행동 지침을 제공합니다.

## 핵심 기능

- **다관점 분석**: 5개 관점이 동일 데이터를 독립적으로 판정 → 합의/분기 결과 제시
- **추천 파이프라인**: `KR/US/ALL` 시장 semantics, 넓은 universe 확보, diversified selection 후 BUY 합의 종목 반환
- **포지션 사이징**: BUY/SELL 합의 시 포트폴리오 상태 반영한 구체적 매매 전략 자동 계산 (분할 매수, 합의 강도별 매도 비율, 현금 하한·집중도 제약)
- **포트폴리오 관리**: 매수/매도(분할 매도 지원), 현금, 추적 손절매
- **성과 추적**: 일별 스냅샷 자동 저장, 적중률 리포트, 적응형 관점 가중치
- **시장 레짐 감지**: 코스피 EMA+모멘텀 기반 bull/bear/sideways 자동 분류
- **일간 변동 리포트**: 어제 vs 오늘 추천 비교 (판정 전환 + 관점별 변동)
- **인과 그래프**: LLM 기반 한국 주식 시장 인과 관계 957트리플 구축
- **웹 검색 보강**: DuckDuckGo로 최신 뉴스/공시/수급 수집 → LLM 프롬프트에 자동 삽입 (OUROBOROS Triple-Gate 검증)
- **시그널 엔진 v2**: ATR 기반 변동성 정규화 임계값 + 레짐 필터
- **백테스트**: 시그널 기반 전략 백테스트 (CAGR, MDD, 샤프 비율) + 파라미터 그리드 서치 최적화
- **환율 팩터**: 다통화(USD/JPY/CNY/EUR-KRW) 수집, 환율 레짐 감지, 수출/내수 분류, 포지션 사이징 ±15% 조정
- **상관 리스크**: 포지션 간 상관계수 기반 진입 차단(ρ>0.7), 섹터 집중도 경고, 분산도 점수
- **매크로 정량 시계열**: 14개 매크로 변수 (금리, 환율 5통화, 원자재, 지수) 자동 수집 + parquet 캐시
- **Granger 인과 검증**: 인과 그래프 트리플을 실제 시계열 데이터로 통계 검증 (p-value, lag 태깅)
- **숙의 합의**: 분기/약한 합의 시 소수 측에 다수 근거 제시 → 재판정 → 합의 수렴
- **자가 학습**: 적중 패턴 분석 → 레짐별 가중치 자동 조정 → 프롬프트 자가 튜닝 제안
- **한국 + 미국 시장**: 티커 포맷 자동 판별 (숫자=KR, 알파벳=US)

## 빠른 시작

```bash
# 의존성 설치
uv sync

# 포트폴리오 등록
uv run main.py cash 10000000
uv run main.py add 005930 55000 10 --reason "반도체 수출 증가"

# 다관점 분석
uv run main.py

# JSON 출력 (shacs-bot 연동)
uv run scripts/daily.py --json

# 종목 추천 (기본: KR = KOSPI + KOSDAQ)
uv run scripts/recommend.py --json

# 미국 전체 추천 (US = NASDAQ + NYSE)
uv run scripts/recommend.py --market US --json

# 전체 시장 추천 (ALL = KR + US)
uv run scripts/recommend.py --market ALL --json

# 백테스트 (6개월, 시그널 기반)
uv run scripts/backtest.py --period 6m --tickers 005930,000660,005380

# 환율 ON/OFF 비교
uv run scripts/backtest.py --period 6m --compare

# 파라미터 최적화
uv run scripts/backtest.py --period 6m --optimize

# 미국 종목 분석
uv run scripts/daily.py -t AAPL MSFT --json
```

## 프로젝트 구조

```
trading-oracle/
├── main.py                          # CLI (다관점 분석, 포트폴리오, 초기화)
├── config.yaml                      # 설정 (LLM provider, 시그널 파라미터)
├── SKILL.md                         # shacs-bot 스킬 정의
│
├── scripts/                         # 기능별 진입점
│   ├── daily.py                     # 일일 다관점 분석
│   ├── recommend.py                 # 추천 파이프라인 (KR/US/ALL + diversified selection)
│   ├── screen.py                    # 주도주 스크리닝
│   ├── portfolio.py                 # 포트폴리오 CRUD
│   ├── perspective.py               # 단일 관점 분석
│   ├── performance.py               # 성과 리포트
│   ├── backtest.py                  # 시그널 백테스트
│   ├── verify_causal.py             # 인과 그래프 Granger 검증
│   └── build_causal.py              # 인과 그래프 구축
│
├── src/
│   ├── common.py                    # 공유 유틸리티
│   ├── data/
│   │   ├── market.py                # OHLCV, 지수, 시총 (pykrx + FDR)
│   │   ├── fundamentals.py          # PER/PBR (네이버 + yfinance)
│   │   ├── web_search.py            # DuckDuckGo 웹 검색 + OUROBOROS 검증
│   │   └── macro.py                 # 매크로 시계열 (금리, 환율, 원자재)
│   ├── signals/
│   │   ├── technical.py             # 6-시그널 앙상블 보팅 (v2: ATR 임계값)
│   │   └── forex.py                 # 환율 팩터 (베타, 시그널, 레짐)
│   ├── perspectives/                # 5개 투자 관점
│   │   ├── base.py                  # ABC + 공유 LLM 호출
│   │   ├── kwangsoo.py              # 이광수 + systrader79 철학
│   │   ├── ouroboros.py             # 포렌식 감사관
│   │   ├── quant_perspective.py     # 퀀트 (코드 verdict + LLM reasoning)
│   │   ├── macro.py                 # 매크로 인과 체인
│   │   └── value.py                 # 가치 투자
│   ├── consensus/
│   │   ├── voter.py                 # 5관점 병렬 호출
│   │   ├── scorer.py                # 합의도 계산 (가중 투표 지원)
│   │   └── deliberator.py           # 숙의 합의 (분기 시 재판정)
│   ├── causal/
│   │   ├── builder.py               # 토픽 확장 + 트리플 추출
│   │   ├── graph.py                 # networkx 그래프 관리
│   │   └── verifier.py              # Granger 인과추론 검증
│   ├── performance/
│   │   ├── tracker.py               # 스냅샷, 적중 평가, 가중치
│   │   ├── pattern_analyzer.py      # 적중 패턴 분석 (레짐별 성적표)
│   │   └── prompt_tuner.py          # 프롬프트 자가 튜닝
│   ├── screener/
│   │   └── leading.py               # 주도주 스크리닝
│   ├── backtest/
│   │   ├── engine.py                # 시그널 백테스트 엔진 + 그리드 서치
│   │   └── metrics.py               # 성과 지표 (CAGR, MDD, 샤프, 승률)
│   ├── portfolio/
│   │   ├── tracker.py               # 포지션, 손절매
│   │   ├── sizer.py                 # 포지션 사이징 (포트폴리오 체크 + BUY/SELL 전략)
│   │   └── correlation.py           # 상관 리스크 + 섹터 분류
│   ├── agent/
│   │   ├── oracle.py                # Anthropic API (SSE 파싱)
│   │   ├── codex.py                 # OpenAI Codex (OAuth)
│   │   └── prompts.py               # 레거시 단일 프롬프트
│   └── output/
│       └── formatter.py             # Rich 터미널 출력
│
├── data/
│   ├── portfolio.json               # 포트폴리오 상태
│   ├── causal_graph.json            # 인과 그래프 (957 트리플)
│   └── snapshots/                   # 일별 추천 스냅샷
│
└── docs/
    └── specs/
        ├── multi-perspective/       # v1 (Phase 1~10)
        ├── v2/                      # v2 (Phase 11~13)
        └── v3/                      # v3 (Phase 14~19)
```

## 사용자 요청별 명령 매핑

| 사용자 요청 | 명령 |
|-------------|------|
| "뭐 살까?" | `uv run scripts/recommend.py --json` |
| "전체 시장에서 뭐 살까?" | `uv run scripts/recommend.py --market ALL --json` |
| "오늘 주식 분석해줘" | `uv run scripts/daily.py --json` |
| "삼성전자 어때?" | `uv run scripts/daily.py -t 005930 --json` |
| "AAPL 분석해줘" | `uv run scripts/daily.py -t AAPL --json` |
| "주도주 뭐 있어?" | `uv run scripts/screen.py --json` |
| "삼성전자 20만원에 10주 샀어" | `uv run scripts/portfolio.py add 005930 200000 10 --json` |
| "삼성전자 5주만 팔아" | `uv run scripts/portfolio.py remove 005930 --shares 5 --json` |
| "포트폴리오 보여줘" | `uv run scripts/portfolio.py show --json` |
| "추천 성과 보여줘" | `uv run scripts/performance.py report --json` |
| "적중 패턴 분석" | `uv run scripts/performance.py patterns --json` |
| "인과 그래프 검증" | `uv run scripts/verify_causal.py --json` |
| "백테스트 해봐" | `uv run scripts/backtest.py --period 6m` |
| "환율 효과 비교" | `uv run scripts/backtest.py --period 6m --compare` |
| "파라미터 최적화" | `uv run scripts/backtest.py --period 6m --optimize` |
| "전체 명령 가이드" | `uv run main.py guide` |
| "데이터 초기화" | `uv run main.py reset --all --json` |

## 종목 추천 파이프라인

- 기본 `--market` 값은 `KR`
- 시장 의미:
  - `KR` = `KOSPI + KOSDAQ`
  - `US` = `NASDAQ + NYSE`
  - `ALL` = `KR + US`
- `--top`은 초기 스크리닝 후보 수가 아니라 **최종 분석 대상 수**
- 추천 흐름:
  - 시장 선택
  - 시장별 넓은 universe 확보
  - score 계산
  - diversified selection으로 `top_n` 압축
  - 시그널 필터(Bull 4/6+)
  - 다관점 분석
  - BUY 합의 종목 반환
- 추천 결과에는 다음 메타데이터가 포함될 수 있음:
  - `universe_size`
  - `universe_breakdown`
  - `portfolio_sizing` (현재 현금, 현금 하한, 가용 현금)
  - `selection_constraints`
  - 각 종목의 `market`, `sector`, `selected_by`

## 5개 투자 관점

| 관점 | 역할 | 판정 기준 |
|------|------|----------|
| **이광수 (kwangsoo)** | 프로세스 중심 투자 | 추적 손절매, 주도주, 모멘텀, 자금관리 2% 룰 |
| **포렌식 (ouroboros)** | 숨겨진 리스크 감사 | 희석 리스크, 내부자 거래, 기관 수급 |
| **퀀트 (quant)** | 기계적 시그널 판정 | 6-시그널 앙상블 (모멘텀, EMA, RSI, MACD, BB) |
| **매크로 (macro)** | 인과 체인 분석 | 금리, 환율, 섹터 사이클, 인과 그래프 참조 |
| **가치 (value)** | 절대/상대 밸류에이션 | PER, PBR, 배당수익률, PEG |

## 합의도 시스템

```
5/5 동일 → 만장일치 (very high confidence)
4/5 동일 → 강한 합의 (high)
3/5 동일 → 약한 합의 (moderate)
동률     → 분기 — 양측 근거 제시, 사용자 선택
2개 이하 → 판정 보류
```

스냅샷 5개 이상 축적 시 **적응형 가중치** 활성화 — 적중률 높은 관점에 더 높은 가중치 부여.

분기/약한 합의 시 **숙의 합의** 자동 발동 — 소수 측에 다수 근거를 제시하고 재판정. 수렴하면 합의로 승격.

## 인과 검증

인과 그래프의 트리플을 실제 시계열 데이터로 Granger Causality Test 검증:

```bash
# 검증 실행 (1,500 트리플 중 매핑 가능한 쌍 검증)
uv run scripts/verify_causal.py

# 검증된 트리플 상세
uv run scripts/verify_causal.py --detail

# 기존 결과 조회
uv run scripts/verify_causal.py --info
```

검증 통과 트리플은 매크로 관점 프롬프트에 `lag`와 `p-value`와 함께 "데이터 검증됨" 라벨로 우선 주입됩니다.

## 웹 검색

DuckDuckGo 기반 무료 웹 검색으로 LLM에 최신 정보 제공. OUROBOROS 프레임워크의 Triple-Gate 검증 적용.

`config.yaml`:
```yaml
web_search:
  enabled: true           # false로 끄면 기존 동작
  max_news: 7
  cache_ttl_hours: 12
```

`--no-search` 플래그로 CLI에서도 비활성화 가능.

## LLM 설정

`config.yaml`:
```yaml
llm:
  provider: codex    # anthropic 또는 codex
  model: gpt-5.4     # provider에 맞는 모델명
  max_tokens: 4096
```

- **Anthropic**: `ANTHROPIC_API_KEY` 환경변수 설정
- **Codex**: `uv run main.py codex-login`으로 OAuth 로그인

## 요구 사항

- Python 3.14+
- `uv` (패키지 매니저)
- LLM API 접근 (Anthropic 또는 OpenAI Codex)
