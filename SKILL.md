---
name: trading-oracle
description: "다관점 한국+미국 주식 투자 조언 에이전트. 5개 관점(이광수/포렌식/퀀트/매크로/가치) + 합의도 시스템. 포트폴리오 관리 + 추천 파이프라인 + 주도주 스크리닝."
metadata: {"shacs-bot":{"emoji":"🔮","requires":{"bins":["uv"],"env":[]}}}
---

# Trading Oracle — 다관점 투자 판정

5개 독립 관점(이광수 철학, 포렌식 감사관, 퀀트 시그널, 매크로 인과, 가치 투자)이 병렬 판정 → 합의도 시스템(MAXS-lite)으로 종합.

모든 명령은 이 스킬의 디렉터리에서 실행. `--json` 플래그로 구조화된 JSON 출력.

---

## ⚡ 워크플로우 (처음 사용자를 위한 순서 가이드)

### 1단계: 초기 설정 (1회)

```bash
# 의존성 설치
uv sync

# LLM 로그인 (Codex 사용 시)
uv run main.py codex-login

# 보유 현금 설정
uv run scripts/portfolio.py cash 10000000 --json

# 보유 종목 등록 (있으면)
uv run scripts/portfolio.py add 005930 55000 10 --reason "반도체" --json
```

### 2단계: 매일 아침 루틴

```bash
# 다관점 분석 실행 (스냅샷 자동 저장됨)
uv run scripts/daily.py --json
```
> **매일 실행이 중요합니다.** 실행할 때마다 스냅샷이 축적되고, 5개 이상 쌓이면 적응형 가중치가 활성화되며, 30개 이상이면 자가 학습(레짐별 가중치)이 작동합니다.
> 
> 출력에는 환율 레짐(원화 강세/약세), 종목별 FX 시그널, 포트폴리오 상관 리스크 경고가 포함됩니다.

### 3단계: 종목 추천 (필요 시)

```bash
# "뭐 살까?" — KR 기본 추천 (`KR = KOSPI + KOSDAQ`)
uv run scripts/recommend.py --json
```

```bash
# 미국 전체 추천 (`US = NASDAQ + NYSE`)
uv run scripts/recommend.py --market US --json

# 전체 시장 추천 (`ALL = KR + US`)
uv run scripts/recommend.py --market ALL --json
```

### 4단계: 성과 확인 (주간)

```bash
# 추천 적중률 리포트
uv run scripts/performance.py report --json

# 관점별 × 레짐별 성적표 (스냅샷 30개+ 이후)
uv run scripts/performance.py patterns --json
```

### 5단계: 인과 그래프 갱신 (분기 1회)

```bash
# 인과 그래프 재구축 (~$5, 90일 경과 시 시스템이 경고)
uv run scripts/build_causal.py build --fresh --json

# Granger 인과 검증 (구축 후 1회)
uv run scripts/verify_causal.py --json
```

### 6단계: 데이터 이상 시 초기화

```bash
# 오염 데이터 초기화 (포트폴리오 제외)
uv run main.py reset --all --json
```

---

## 일일 분석 (핵심 명령)

다관점 분석 (5개 관점 + 합의도):
```bash
uv run scripts/daily.py --json
```

특정 종목 분석:
```bash
uv run scripts/daily.py -t 005930 --json
```

주도주 스크리닝 포함:
```bash
uv run scripts/daily.py --screen --json
```

시그널만 (LLM 없이):
```bash
uv run scripts/daily.py --no-llm --json
```

스킬 호출자용 prompt package 출력:
```bash
uv run scripts/daily.py --json --llm-mode prompt-ready
```

적응형 가중치 비활성화 (동등 가중치):
```bash
uv run scripts/daily.py --no-weights --json
```

웹 검색 비활성화 (LLM 학습 데이터만):
```bash
uv run scripts/daily.py --no-search --json
```

기존 단일 관점 분석 (레거시):
```bash
uv run scripts/daily.py --legacy --json
```

## 포트폴리오 관리

매수 기록:
```bash
uv run scripts/portfolio.py add <종목코드> <매수가> <수량> --reason "매수 이유" --json
```

매도 기록 (전량):
```bash
uv run scripts/portfolio.py remove <종목코드> --price <매도가> --reason "매도 이유" --json
```

분할 매도 (일부 수량):
```bash
uv run scripts/portfolio.py remove <종목코드> --price <매도가> --shares <수량> --json
```

현금 설정:
```bash
uv run scripts/portfolio.py cash <금액> --json
```

포트폴리오 조회:
```bash
uv run scripts/portfolio.py show --json
```

거래 내역:
```bash
uv run scripts/portfolio.py history --json
```

## 종목 추천 (Recommendation Pipeline)

BUY 합의 종목 자동 추천:
```bash
uv run scripts/recommend.py --json
```

- 기본 `--market`은 `KR`
- 시장 의미:
  - `KR` = `KOSPI + KOSDAQ`
  - `US` = `NASDAQ + NYSE`
  - `ALL` = `KR + US`
- `--top`은 초기 후보 수가 아니라 **최종 분석 대상 수**
- 내부 흐름:
  - 시장별 넓은 universe 확보
  - score 계산
  - diversified selection
  - 시그널 필터
  - 다관점 분석
  - BUY 합의 종목 반환

미국 시장:
```bash
uv run scripts/recommend.py --market US --json
```

전체 시장:
```bash
uv run scripts/recommend.py --market ALL --json
```

최종 분석 대상 수 조정:
```bash
uv run scripts/recommend.py --top 10 --json
```

시그널만 (LLM 없이, 빠름):
```bash
uv run scripts/recommend.py --no-llm --json
```

스킬 호출자용 prompt package 출력:
```bash
uv run scripts/recommend.py --json --llm-mode prompt-ready
```

추천 결과에는 `universe_size`, `universe_breakdown`, `selection_constraints` 메타데이터와 종목별 `market`, `sector`, `selected_by` 정보가 포함될 수 있습니다.

## 주도주 스크리닝

```bash
uv run scripts/screen.py --json
```

상위 N개:
```bash
uv run scripts/screen.py --top 10 --json
```

## 단일 관점 분석

이광수 관점:
```bash
uv run scripts/perspective.py --kwangsoo -t 005930 --json
```

퀀트 관점:
```bash
uv run scripts/perspective.py --quant -t 005930 --json
```

사용 가능 관점: `--kwangsoo`, `--ouroboros`, `--quant`, `--macro`, `--value`

스킬 호출자용 단일 관점 payload:
```bash
uv run scripts/perspective.py --macro -t 005930 --json --llm-mode prompt-ready
```

## 인과 그래프 + Granger 검증

인과 그래프 구축 (1회성, ~$5):
```bash
uv run scripts/build_causal.py build --json
```

소규모 테스트:
```bash
uv run scripts/build_causal.py build --max-topics 20 --json
```

기존 그래프에 도메인 추가:
```bash
uv run scripts/build_causal.py update 2차전지 AI --json
```

그래프 정보 조회:
```bash
uv run scripts/build_causal.py info --json
```

Granger 인과 검증 (인과 그래프 트리플을 실제 시계열 데이터로 통계 검증):
```bash
uv run scripts/verify_causal.py --json
```

검증된 트리플 상세 보기:
```bash
uv run scripts/verify_causal.py --detail
```

기존 검증 결과 조회:
```bash
uv run scripts/verify_causal.py --info
```

> 인과 검증은 Phase 11(매크로 시계열)의 데이터를 사용합니다. 검증된 트리플은 매크로 관점 프롬프트에 "데이터 검증됨 (p-value, lag)" 라벨로 우선 주입됩니다.

## 사용자 요청별 매핑

| 사용자 요청 | 실행 명령 |
|-------------|-----------|
| "뭐 살까?" | `uv run scripts/recommend.py --json` |
| "미국주식 뭐 살까?" | `uv run scripts/recommend.py --market US --json` |
| "전체 시장에서 뭐 살까?" | `uv run scripts/recommend.py --market ALL --json` |
| "오늘 주식 분석해줘" | `uv run scripts/daily.py --json` |
| "삼성전자 어때?" | `uv run scripts/daily.py -t 005930 --json` |
| "주도주 뭐 있어?" | `uv run scripts/screen.py --json` |
| "삼성전자 20만원에 10주 샀어" | `uv run scripts/portfolio.py add 005930 200000 10 --json` |
| "SK하이닉스 팔았어" | `uv run scripts/portfolio.py remove 000660 --json` |
| "삼성전자 5주만 팔아" | `uv run scripts/portfolio.py remove 005930 --shares 5 --json` |
| "애플 분석해줘" | `uv run scripts/daily.py -t AAPL --json` |
| "AAPL 200달러에 10주 샀어" | `uv run scripts/portfolio.py add AAPL 200 10 --json` |
| "현금 천만원 있어" | `uv run scripts/portfolio.py cash 10000000 --json` |
| "내 포트폴리오 보여줘" | `uv run scripts/portfolio.py show --json` |
| "거래 내역" | `uv run scripts/portfolio.py history --json` |
| "이광수 관점으로만 봐줘" | `uv run scripts/perspective.py --kwangsoo -t 005930 --json` |
| "매크로 관점에서 반도체는?" | `uv run scripts/perspective.py --macro -t 005930 000660 --json` |
| "인과 그래프 만들어줘" | `uv run scripts/build_causal.py build --json` |
| "인과 그래프 정보" | `uv run scripts/build_causal.py info --json` |
| "인과 그래프 검증" | `uv run scripts/verify_causal.py --json` |
| "적중 패턴 분석" | `uv run scripts/performance.py patterns --json` |
| "백테스트 해봐" | `uv run scripts/backtest.py --period 6m` |
| "환율 효과 비교" | `uv run scripts/backtest.py --period 6m --compare` |
| "파라미터 최적화" | `uv run scripts/backtest.py --period 6m --optimize` |
| "전체 명령 가이드" | `uv run main.py guide` |
| "가중치 없이 분석해줘" | `uv run scripts/daily.py --no-weights --json` |
| "추천 성과 보여줘" | `uv run scripts/performance.py report --json` |
| "어제 추천 결과는?" | `uv run scripts/performance.py detail 2026-03-27 --json` |
| "스냅샷 목록" | `uv run scripts/performance.py list --json` |
| "데이터 초기화" | `uv run main.py reset --all --json` |
| "스냅샷 초기화" | `uv run main.py reset --snapshots --json` |
| "인과 그래프 초기화" | `uv run main.py reset --causal --json` |

## 백테스트

시그널 기반 전략 백테스트 (LLM 비용 $0):
```bash
uv run scripts/backtest.py --period 6m --tickers 005930,000660,005380
```

환율 팩터 ON/OFF 비교:
```bash
uv run scripts/backtest.py --period 6m --compare
```

파라미터 그리드 서치 (min_votes × stop_loss × position_size):
```bash
uv run scripts/backtest.py --period 6m --optimize
```

상관 리스크 비활성화 비교:
```bash
uv run scripts/backtest.py --period 6m --no-corr
```

JSON 출력:
```bash
uv run scripts/backtest.py --period 6m --json
```

> 백테스트는 6-시그널 앙상블 + 환율 팩터 + 상관 리스크 필터를 적용합니다. LLM 관점은 포함되지 않습니다.

## 추천 성과 추적

성과 리포트 (최근 30일):
```bash
uv run scripts/performance.py report --json
```

최근 60일:
```bash
uv run scripts/performance.py report --days 60 --json
```

스냅샷 목록:
```bash
uv run scripts/performance.py list --json
```

특정 날짜 상세:
```bash
uv run scripts/performance.py detail 2026-03-28 --json
```

> 스냅샷은 다관점 분석(`daily.py`) 실행 시 자동 저장됩니다.

## 종목 코드 참고

| 종목명 | 코드 |
|--------|------|
| 삼성전자 | 005930 |
| SK하이닉스 | 000660 |
| 현대차 | 005380 |
| 한화에어로스페이스 | 012450 |
| KB금융 | 105560 |
| 신한지주 | 055550 |
| LG에너지솔루션 | 373220 |
| 삼성바이오로직스 | 207940 |
| 두산에너빌리티 | 034020 |
| 기아 | 000270 |

## 미국 종목 코드 참고

| 종목명 | 코드 |
|--------|------|
| Apple | AAPL |
| Microsoft | MSFT |
| NVIDIA | NVDA |
| Tesla | TSLA |
| Amazon | AMZN |
| Alphabet (Google) | GOOGL |
| Meta | META |
| AMD | AMD |
| Netflix | NFLX |
| Broadcom | AVGO |

> 미국 종목은 알파벳 티커 (AAPL, MSFT 등), 한국 종목은 숫자 코드 (005930 등)로 자동 구분됩니다.

## 합의도 해석

- **만장일치** (very high): 5/5 동일 → 높은 확신
- **강한 합의** (high): 4/5 동일 → 소수 의견 참고
- **약한 합의** (moderate): 3/5 동일 → 신중하게
- **분기** (low): 관점 충돌 → 양측 근거 제시, 사용자 선택
- **판정 보류** (insufficient): 유효 관점 부족 → 데이터 확인 필요

## 핵심 투자 원칙 (사용자에게 전달 시)

- 오르는 주식은 팔지 마라 — 고점에서 10% 빠질 때 매도
- 손절매는 반드시 설정 — 매수 시 10% 손절 기본
- 주도주를 쫓아가라 — 발명하지 말고 시장이 선택한 종목
- 3~5종목 집중 — 종목 수 늘리면 관리 불가
- 현금은 기회의 실탄 — 변동성 장에서 현금 비중 유지
