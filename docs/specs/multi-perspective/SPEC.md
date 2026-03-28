# Trading Oracle — Feature Specification

## PRD 연결

| Phase | PRD | 상태 | 설명 |
|-------|-----|------|------|
| Phase 1 | [phase1-perspectives.md](prds/phase1-perspectives.md) | 🟡 미착수 | 5개 투자 관점 + 합의도 시스템 (MAXS-lite) |
| Phase 2 | [phase2-scripts.md](prds/phase2-scripts.md) | 🟡 미착수 | scripts/ 분리 + shacs-bot 연동 |
| Phase 3 | [phase3-causal-graph.md](prds/phase3-causal-graph.md) | 🟡 미착수 | 인과 그래프 (DEMOCRITUS-lite) |

> 각 PRD는 마일스톤, 검증 기준, 진행 로그를 포함한다. 구현 착수 시 PRD의 마일스톤을 체크리스트로 사용한다.

---

## 개요

**Trading Oracle**은 한국 주식 시장 투자자를 위한 다관점 일일 투자 조언 에이전트이다. 매일 실행하면 보유 포트폴리오와 시장 데이터를 기반으로 "오늘 무엇을 얼마에 사거나 팔면 되는지" 구체적 행동 지침을 제공한다.

**핵심 차별점**: 단일 관점이 아닌 5개 독립 투자 관점(이광수 철학, 포렌식 감사관, 퀀트 시그널, 매크로 인과, 가치 투자)이 병렬로 판정하고, 합의/분기 결과를 사용자에게 제시하여 최종 결정은 사용자가 내린다.

---

## 1. 사용자 시나리오

### 1-1. 매일 아침 투자 조언 (핵심 시나리오)

**사용자**: 직장인 투자자. 3~5개 종목 보유. 매일 아침 출근 전 5분간 조언 확인.

**플로우**:
1. shacs-bot(Telegram/Slack)에 "오늘 주식 분석해줘" 입력
2. 시스템이 보유 포트폴리오의 현재가 + 시그널 수집
3. 5개 관점이 각 종목에 대해 독립 판정
4. 합의 결과 + 구체적 행동(보유/매도/매수 + 가격) 제시
5. 관점이 분기하면 양측 근거를 보여주고 사용자가 선택

**기대 출력 예시**:
```
📊 삼성전자 (005930) — 179,700원
  🔴 이광수: 매도 — 손절가 이탈
  🔴 퀀트: 매도 — Bear 6/6
  🟡 포렌식: 관망 — 희석 리스크 없음
  🟢 매크로: 관심 — 반도체 가격 상승 중
  🔴 가치: 매도 — PER 27 고평가
  합의도: 4/5 매도 (high confidence)
```

### 1-2. 포트폴리오 등록/관리

**플로우**:
1. "삼성전자 20만원에 10주 샀어" → 매수 기록
2. "현금 천만원" → 현금 설정
3. "SK하이닉스 팔았어" → 매도 기록 + 거래 히스토리 저장
4. "포트폴리오 보여줘" → 현재가 반영 요약 + 손절매 상태

### 1-3. 주도주 탐색

**플로우**:
1. "주도주 뭐 있어?" → 시총 상위 종목 모멘텀+밸류에이션 스크리닝
2. 상위 후보 종목 리스트 + 점수 제공
3. 원하면 특정 종목 다관점 심층 분석

### 1-4. 특정 관점 심층 분석

**플로우**:
1. "매크로 관점에서 반도체 섹터는?" → 매크로 관점만 단독 호출
2. 인과 체인 기반 설명 제공

### 1-5. 인과 그래프 구축 (1회성) → [PRD Phase 3](prds/phase3-causal-graph.md)

**플로우**:
1. "인과 그래프 만들어줘" → LLM으로 한국 주식 시장 도메인 토픽 확장
2. 인과 진술 추출 → 트리플 변환 → 그래프 저장
3. 이후 매일 분석 시 배경 지식으로 참조

---

## 2. 시스템 아키텍처

### 2-1. 계층 구조

```
┌─────────────────────────────────────────────────────┐
│ Interface Layer                                      │
│  shacs-bot SKILL.md → scripts/*.py → --json 출력     │
├─────────────────────────────────────────────────────┤
│ Consensus Layer (MAXS-lite)                          │
│  5개 관점 병렬 LLM 호출 → 판정 파싱 → 합의도 계산     │
├─────────────────────────────────────────────────────┤
│ Perspective Layer                                    │
│  이광수 | 포렌식 | 퀀트 | 매크로 | 가치               │
│  각 관점 = 시스템 프롬프트 + 판정 파서                 │
├─────────────────────────────────────────────────────┤
│ Signal Layer                                         │
│  6-signal 앙상블 (Momentum, EMA, RSI, MACD, BB)      │
│  + PER/PBR/배당 (네이버 금융)                         │
│  + 코스피/코스닥 지수 (FinanceDataReader)              │
├─────────────────────────────────────────────────────┤
│ Data Layer                                           │
│  pykrx (OHLCV) + FDR (지수) + 네이버 (펀더멘털)       │
├─────────────────────────────────────────────────────┤
│ Knowledge Layer (DEMOCRITUS-lite)                    │
│  인과 그래프 (1회 구축, 분기 갱신)                     │
│  networkx + sentence-transformers                    │
├─────────────────────────────────────────────────────┤
│ State Layer                                          │
│  portfolio.json + causal_graph.json                  │
└─────────────────────────────────────────────────────┘
```

### 2-2. 디렉터리 구조

```
trading-oracle/
├── SKILL.md                         # shacs-bot 스킬 정의
├── main.py                          # 기존 CLI (하위 호환)
├── config.yaml                      # 설정
│
├── scripts/                         # 상황별 진입점 → PRD Phase 2
│   ├── daily.py                     # 매일: 포트폴리오 + 다관점 분석
│   ├── screen.py                    # 주도주 스크리닝
│   ├── portfolio.py                 # 포트폴리오 CRUD
│   ├── build_causal.py              # 1회성: 인과 그래프 구축
│   └── perspective.py               # 단일 관점 분석
│
├── src/
│   ├── data/
│   │   ├── market.py                # pykrx + FDR 시장 데이터
│   │   └── fundamentals.py          # 네이버 금융 PER/PBR 스크래핑
│   ├── signals/
│   │   └── technical.py             # 6-시그널 앙상블 보팅
│   ├── screener/
│   │   └── leading.py               # 주도주 스크리닝
│   ├── portfolio/
│   │   └── tracker.py               # 포지션 추적, 추적 손절매
│   ├── perspectives/                # 5개 관점 (플러그인 구조) → PRD Phase 1
│   │   ├── base.py                  # 공통 인터페이스
│   │   ├── kwangsoo.py              # 이광수 철학
│   │   ├── ouroboros.py             # 포렌식 감사관
│   │   ├── quant_perspective.py     # 퀀트 기계적 판정
│   │   ├── macro.py                 # 매크로 인과 체인
│   │   └── value.py                 # 가치 투자
│   ├── consensus/                   # MAXS-lite → PRD Phase 1
│   │   ├── voter.py                 # 다관점 병렬 호출
│   │   └── scorer.py                # 합의도 계산
│   ├── causal/                      # DEMOCRITUS-lite → PRD Phase 3
│   │   ├── builder.py               # 토픽 확장 + 인과 진술 생성
│   │   ├── triples.py               # 트리플 추출
│   │   └── graph.py                 # networkx 그래프 관리
│   ├── agent/
│   │   ├── oracle.py                # Claude API 연동
│   │   └── prompts.py               # 기존 단일 프롬프트 (하위 호환)
│   └── output/
│       └── formatter.py             # Rich 카드형 터미널 출력
│
├── data/
│   ├── portfolio.json               # 포트폴리오 상태
│   └── causal_graph.json            # 인과 그래프
│
└── docs/
    └── specs/
        └── multi-perspective/
            ├── SPEC.md              # 이 문서
            └── prds/                # 구현 계획
                ├── phase1-perspectives.md
                ├── phase2-scripts.md
                └── phase3-causal-graph.md
```

---

## 3. 5개 투자 관점 정의 → [PRD Phase 1](prds/phase1-perspectives.md)

### 3-1. 이광수 (kwangsoo)

**역할**: 프로세스 중심 투자자. 손실 관리와 추세 추종에 집중.

**판단 기준**:
- 추적 손절매 상태 (고점 -10% 이탈 여부)
- 주도주 여부 (시장 대비 상대 강도)
- 오르는 주식인가 (모멘텀 양수)
- 분할 매수 가능 구간인가

**출력 형식**:
```json
{
  "perspective": "kwangsoo",
  "verdict": "SELL",
  "confidence": 0.9,
  "reasoning": [
    "코스피 20일 -12.9% → 하락 추세 미종결",
    "고점 223,000 대비 -19.4% → 추적 손절매 200,700원 이미 이탈",
    "6/6 베어 만장일치 → 반등 시그널 0개",
    "이광수 원칙: 빠지면 무조건 판다. 손실을 뒤로 미루는 것은 본성이지만 이겨내야 함"
  ],
  "reason": "손절가 이탈 + 반등 근거 없음. 즉시 매도.",
  "action": {"type": "sell", "price": 179700, "urgency": "immediate"},
  "philosophy": "빠지면 팔아라. 손절은 실패가 아니라 프로세스의 완성."
}
```

### 3-2. 포렌식 감사관 (ouroboros)

**역할**: OUROBOROS 프레임워크 기반. 기업의 숨겨진 리스크를 파헤치는 냉소적 감사관.

**판단 기준**:
- 희석 리스크 (유상증자, 전환사채, 워런트)
- 내부자 거래 패턴
- 기관 수급 이탈 여부
- 재무 건전성 (현금소진율, 부채비율)

**출력 형식**:
```json
{
  "perspective": "ouroboros",
  "verdict": "HOLD",
  "confidence": 0.6,
  "reasoning": [
    "최근 6개월 유상증자/CB 발행 이력 없음 → 희석 리스크 클린",
    "내부자 거래: 최근 3개월 임원 매도 내역 없음 → 탈출 신호 없음",
    "기관 수급: 외국인 연속 순매도 중이나 연기금 매수 유입",
    "PER 27 → 고평가이나 파운드리 MBI 수주 시 이익 급증 가능성 잔존",
    "결론: 즉각적 위험 요인 없음. 다만 고평가 상태이므로 적극 매수도 아님"
  ],
  "reason": "희석 리스크 없음. PER 27 고평가이나 파운드리 반등 시 정당화 가능.",
  "risks": ["파운드리 적자 지속", "스마트폰 수요 부진"],
  "action": {"type": "hold", "watch": "분기 실적 발표"}
}
```

### 3-3. 퀀트 시그널 (quant)

**역할**: 6-시그널 앙상블의 기계적 판정. 감정 없는 기계.

**판단 기준**:
- 6개 시그널 투표 결과 (MIN_VOTES=4)
- RSI 과매수/과매도 상태
- ATR 기반 손절매 가격
- BB 압축 (돌파 임박 여부)

**출력 형식**:
```json
{
  "perspective": "quant",
  "verdict": "SELL",
  "confidence": 1.0,
  "reasoning": [
    "모멘텀 20일 -17.0% → 베어 (임계값 -3% 초과)",
    "단기 모멘텀 5일 -3.5% → 베어",
    "EMA(5) 185,000 < EMA(20) 188,378 → 데드크로스 유지",
    "RSI(8) = 35.9 → 50 미만 베어. 과매도(31) 미달이므로 반등 근거 없음",
    "MACD 히스토그램 -2,397 → 베어 강화 중",
    "BB 46%ile → 압축 구간이나 방향 중립이므로 베어에 1표 추가 불가",
    "결과: Bear 6/6 vs Bull 1/6 → MIN_VOTES(4) 충족. 명확한 매도 시그널"
  ],
  "reason": "Bear 6/6 만장일치. RSI 35.9 과매도 미달.",
  "signals": {"momentum": "bear", "ema": "bear", "rsi": "bear", "macd": "bear", "bb": "bull", "short_mom": "bear"},
  "action": {"type": "sell", "stop_loss": 142545}
}
```

### 3-4. 매크로 인과 (macro)

**역할**: 금리, 환율, 지정학, 섹터 사이클의 인과 체인으로 판단.

**판단 기준**:
- 기업 이익에 직접 영향을 미치는 매크로 변수 (디램 가격, 환율, 금리)
- 섹터 사이클 위치 (상승/피크/하강/바닥)
- 지정학적 리스크/수혜
- 인과 그래프 참조 (있을 경우)

**출력 형식**:
```json
{
  "perspective": "macro",
  "verdict": "BUY",
  "confidence": 0.7,
  "reasoning": [
    "핵심 변수 식별: 삼성전자 이익의 최대 드라이버는 디램/낸드 가격 (금리 아님)",
    "디램 가격 추이: 2026Q1 고정거래가격 상승 중 → 이익 증가 인과 체인 활성",
    "AI 투자 → HBM 수요 → 반도체 가격 → 하이닉스/삼성 이익 (인과 그래프 경로)",
    "금리: 미 연준 동결 → 성장주 밸류에이션에 중립. 삼성전자에 직접 영향 제한적",
    "환율: 원/달러 1,400원대 → 수출기업 실적에 긍정적",
    "리스크: 미중 반도체 수출 규제 추가 가능성 상존",
    "결론: 이익 증가 인과 체인이 가격 하락을 상쇄할 가능성. 단기 하락은 매수 기회"
  ],
  "reason": "반도체 가격 상승 중. AI 투자 확대 → HBM 수요 → 이익 증가 인과 체인 활성.",
  "causal_chain": ["AI 투자 확대", "HBM 수요 증가", "반도체 가격 상승", "삼성전자 이익 증가"],
  "action": {"type": "buy", "condition": "반도체 가격 추세 유지 확인 시"}
}
```

### 3-5. 가치 투자 (value)

**역할**: PER/PBR/배당수익률 기반 절대적 가치 평가.

**판단 기준**:
- PER: 업종 평균 대비 위치
- PBR: 1.0 이하 저평가, 2.0 이상 고평가
- 배당수익률: 시장금리 대비
- 이익 증가율 vs PER (PEG 비율)

**출력 형식**:
```json
{
  "perspective": "value",
  "verdict": "SELL",
  "confidence": 0.8,
  "reasoning": [
    "PER 27.38 → 반도체 업종 평균 15 대비 82% 할증. 고평가 영역",
    "PBR 2.81 → 자산 대비 2.8배 평가. 저평가 구간(1.0 이하) 아님",
    "배당수익률 0.93% → 시장금리(3.5%) 대비 매력 없음",
    "PEG 추정: PER 27 / 이익성장률 추정 15% = 1.8 → 1.0 초과 = 성장 대비 고평가",
    "동종 비교: SK하이닉스 PER 15.64 대비 삼성전자 PER 27.38 → 같은 섹터 내에서도 비쌈",
    "결론: 현재 가격은 이익 회복을 이미 선반영. 추가 상승 여력 제한"
  ],
  "reason": "PER 27.38 > 업종 평균 15. PBR 2.81 고평가. 배당 0.93% 매력 없음.",
  "metrics": {"per": 27.38, "pbr": 2.81, "div_yield": 0.93, "sector_avg_per": 15},
  "action": {"type": "sell", "fair_value_estimate": 130000}
}
```

---

## 4. 합의도 시스템 (MAXS-lite) → [PRD Phase 1 M3](prds/phase1-perspectives.md#m3-합의도-시스템-maxs-lite-구현)

### 4-0. 관점별 출력 필드 규격

모든 관점은 아래 공통 필드를 반드시 포함:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `perspective` | string | ✅ | 관점 식별자 (kwangsoo, ouroboros, quant, macro, value) |
| `verdict` | string | ✅ | 판정 (BUY / SELL / HOLD) |
| `confidence` | float | ✅ | 확신도 (0.0 ~ 1.0) |
| `reasoning` | string[] | ✅ | **단계별 추론 과정** — 왜 이렇게 판단했는지. 데이터 → 해석 → 결론 순서 |
| `reason` | string | ✅ | 한 줄 요약 (최종 결론) |
| `action` | object | ✅ | 구체적 행동 지침 (type, price, condition 등) |

**`reasoning` vs `reason` 구분**:
- `reasoning`: 추론 과정. "코스피 20일 -12.9% → 하락 추세 미종결" 같은 단계별 논리 체인. 사용자가 "왜?"라고 물었을 때의 답.
- `reason`: 결론 요약. "손절가 이탈 + 반등 근거 없음." 한 줄로 끝나는 최종 판정 이유.

관점별 추가 필드:

| 관점 | 추가 필드 |
|------|----------|
| kwangsoo | `philosophy` (이광수 철학 한 줄) |
| ouroboros | `risks` (감지된 리스크 리스트) |
| quant | `signals` (6개 시그널 상세) |
| macro | `causal_chain` (인과 체인 경로) |
| value | `metrics` (PER/PBR/배당 수치), `fair_value_estimate` |

### 4-1. 판정 분류

각 관점의 verdict는 4가지 중 하나:
- `BUY` — 매수 (신규 또는 추가)
- `SELL` — 매도 (전량 또는 비중 축소)
- `HOLD` — 관망 (현 상태 유지)
- `N/A` — 판정 불가 (LLM 호출 실패, 데이터 부족 등)

### 4-2. 호출 방식 및 실패 처리

**병렬 호출**: 5개 관점을 `asyncio`/`ThreadPool`로 동시 호출. 응답 시간 = 가장 느린 1개 관점.

**부분 실패 허용**: 일부 관점이 LLM 호출 실패(타임아웃, API 에러)하면 해당 관점만 `N/A` 처리하고 성공한 관점만으로 합의도 계산. 전체 재시도 불필요.

**파싱 실패 처리**: LLM 반환 JSON에서 verdict 파싱 실패(비표준 값, JSON 형식 불량) 시 동일 프롬프트로 1회 재호출. 재실패 시 해당 관점 `N/A`.

**퀀트 관점 특례**: 퀀트 관점은 하이브리드 구조 — `technical.py`에서 verdict/signals를 코드로 직접 계산(실패 없음)하고, LLM은 reasoning 텍스트만 생성. LLM reasoning 생성 실패 시 코드 계산 결과(verdict + signals)만 표시.

### 4-3. 합의도 계산

```
유효 관점 수 = N/A가 아닌 관점 수
합의도 = max(buy_count, sell_count, hold_count) / 유효 관점 수

판정:
  유효 5/5 동일 → "만장일치" (confidence: very high)
  유효 4/5 또는 4/4 동일 → "강한 합의" (confidence: high)
  유효 3/5 또는 3/4 동일 → "약한 합의" (confidence: moderate, 소수 의견 명시)
  유효 2개 이하 → "판정 보류" (데이터 부족으로 신뢰도 낮음)
  기타 → "분기" (confidence: low, 양측 근거 모두 제시, 사용자 선택 요구)
```

### 4-4. 분기 시 사용자 제시 형식

```
📊 한화에어로스페이스 — 관점 분기 (2매수 / 1관심 / 2매도)

  매수 측 (이광수 + 매크로):
    "하락장에서 20일 +11.7% 유지 = 주도주. NATO 재무장 구조적 수혜."
    → 매수가 1,300,000~1,350,000원, 손절가 1,201,500원

  매도 측 (포렌식 + 가치):
    "PER 46.72, PBR 7.09 극도 고평가. 어닝 미스 시 급락 리스크."
    → 현 보유자: 추적 손절매 1,201,500원 설정 후 관찰

  → 당신의 판단: 성장 기대 vs 밸류에이션 부담
```

---

## 5. 인과 그래프 (DEMOCRITUS-lite) → [PRD Phase 3](prds/phase3-causal-graph.md)

### 5-1. 구축 프로세스

1. **토픽 확장**: LLM에 "한국 주식 시장" 도메인 루트 토픽 제공 → BFS 확장
   - 루트: 매크로경제, 반도체, 자동차, 방산, 금융, 바이오, 에너지, 소비재
   - 깊이: 3단계, 최대 500 토픽
2. **인과 진술 생성**: 각 토픽에서 "X causes Y" 형태 진술 3개씩
3. **트리플 추출**: (subject, relation, object) 파싱
4. **그래프 저장**: networkx DiGraph → JSON 직렬화
5. **임베딩** (선택): sentence-transformers로 노드 임베딩 → UMAP 시각화

### 5-2. 저장 형식

```json
{
  "metadata": {
    "created_at": "2026-03-28",
    "num_topics": 500,
    "num_triples": 1500,
    "llm_model": "claude-sonnet-4-20250514"
  },
  "triples": [
    {"subject": "금리인상", "relation": "reduces", "object": "성장주 밸류에이션", "domain": "매크로"},
    {"subject": "반도체 가격상승", "relation": "increases", "object": "SK하이닉스 이익", "domain": "반도체"},
    ...
  ]
}
```

### 5-3. 갱신 정책

- **구조적 이벤트 발생 시**: 분기 실적 발표, 상법 개정, 금리 방향 전환, 새 섹터 부상
- **주기**: 분기 1회 (3개월)
- **증분 갱신**: 기존 그래프에 새 토픽/트리플 추가. 전체 재구축 불필요.
- **갱신 불필요**: 일일 주가, 수급, 기술적 지표 변동

### 5-4. 활용 방식

- 매크로 관점 프롬프트에 관련 인과 체인 삽입
- LLM이 "왜" 이 종목이 영향받는지 설명할 때 참조
- 사용자가 "반도체 가격이 오르면 어떤 종목이 수혜?" 질문 시 그래프 순회

---

## 6. 데이터 소스

| 데이터 | 소스 | 주기 | 실패 시 폴백 |
|--------|------|------|-------------|
| OHLCV (일봉) | pykrx | 매 실행 | 해당 종목 분석 스킵 |
| 코스피/코스닥 지수 | FinanceDataReader | 매 실행 | 시장 환경 섹션 생략 |
| PER/PBR/배당 | 네이버 금융 스크래핑 | 매 실행 | 7일 이내 캐시 사용, 초과 시 가치 관점 비활성화 → [PRD Phase 1 M4](prds/phase1-perspectives.md#m4-펀더멘털-캐시-및-가치-관점-안정화) |
| 시가총액/상장주식수 | FinanceDataReader | 매 실행 | 시총 정보 없이 진행 |
| 인과 그래프 | LLM 생성 (Claude API) | 분기 1회 | 인과 체인 없이 매크로 관점 진행 |

### 6-1. 펀더멘털 캐시 정책

네이버 금융 스크래핑 실패 시 `data/fundamentals_cache.json`에서 캐시 조회:
- 캐시 데이터가 **7일 이내**: 캐시 값 사용. 출력에 `(캐시: YYYY-MM-DD 기준)` 표시.
- 캐시 데이터가 **7일 초과** 또는 캐시 없음: 가치 관점(value) 비활성화. 나머지 4개 관점으로 판정.
- 스크래핑 성공 시: 캐시 갱신.

---

## 7. 기술적 분석 — 6-시그널 앙상블

auto-researchtrading 프로젝트의 검증된 앙상블 기법을 일봉에 적응.

| 시그널 | 계산 | Bull 조건 | Bear 조건 |
|--------|------|----------|----------|
| 모멘텀 | 20일 수익률 | > 3% | < -3% |
| 단기 모멘텀 | 5일 수익률 | > 1.5% | < -1.5% |
| EMA 크로스 | EMA(5) vs EMA(20) | 단기 > 장기 | 단기 < 장기 |
| RSI | RSI(8) | > 50 | < 50 |
| MACD | MACD(12,26,9) 히스토그램 | > 0 | < 0 |
| BB 압축 | BB폭 백분위 | < 80%ile | < 80%ile (방향 중립) |

**MIN_VOTES = 4**: 6개 중 4개 이상 동의 시 시그널 발생.

**추가 지표**:
- ATR(20) 기반 손절매 가격
- 고점 대비 10% 추적 손절매
- 52주 고가/저가
- RSI 과매수(69)/과매도(31) 경고

---

## 8. shacs-bot 연동 → [PRD Phase 2](prds/phase2-scripts.md)

### 8-1. SKILL.md

`SKILL.md`는 프로젝트 루트에 위치. shacs-bot workspace의 `skills/trading-oracle/`로 심링크 또는 이동하여 사용.

### 8-2. 사용자 요청 → 스크립트 매핑

| 사용자 요청 | 스크립트 | 설명 |
|-------------|---------|------|
| "오늘 주식 분석해줘" | `scripts/daily.py --json` | 다관점 분석 |
| "삼성전자 어때?" | `scripts/daily.py -t 005930 --json` | 특정 종목 |
| "주도주 뭐 있어?" | `scripts/screen.py --json` | 스크리닝 |
| "삼성전자 20만원에 10주 샀어" | `scripts/portfolio.py add 005930 200000 10 --json` | 매수 기록 |
| "포트폴리오 보여줘" | `scripts/portfolio.py show --json` | 포트폴리오 |
| "SK하이닉스 팔았어" | `scripts/portfolio.py remove 000660 --json` | 매도 기록 |
| "현금 천만원" | `scripts/portfolio.py cash 10000000 --json` | 현금 설정 |
| "이광수 관점으로만 봐줘" | `scripts/perspective.py --kwangsoo -t 005930 --json` | 단일 관점 |
| "인과 그래프 만들어줘" | `scripts/build_causal.py --json` | 1회성 구축 |
| "거래 내역" | `scripts/portfolio.py history --json` | 히스토리 |

### 8-3. JSON 출력 규격

모든 스크립트는 `--json` 플래그 시 stdout에 JSON 출력. shacs-bot 서브에이전트가 파싱하여 채널에 포맷팅.

---

## 9. 비용 예산

### 9-1. API 호출 횟수

| 모드 | LLM 호출 수 | 예상 토큰 | 예상 비용 (Claude Sonnet) |
|------|-----------|----------|------------------------|
| 단일 관점 (기존) | 1회 | ~4K input + ~2K output | ~$0.02 |
| 다관점 (4 LLM + 1 코드) | 4회 병렬 + 퀀트 reasoning 1회 | ~20K input + ~10K output | ~$0.10 |
| 다관점 + 재시도 최악 | 8회 (4×2 재시도) + 1회 | ~40K input + ~20K output | ~$0.20 |
| 인과 그래프 구축 | ~500회 | ~500K input + ~250K output | ~$5.00 (1회성) |

**참고**: 퀀트 관점은 verdict/signals를 코드로 계산(비용 0). LLM은 reasoning 텍스트만 생성(1회).

### 9-2. 일일 예산

- 기본 모드 (4 LLM + 1 코드): ~$0.10/일 → 월 $3
- 재시도 포함 최악: ~$0.20/일 → 월 $6
- 인과 그래프: 분기 $5 (연 $20)

---

## 10. 구현 우선순위

### Phase 1: 다관점 시스템 → [PRD](prds/phase1-perspectives.md)
1. `src/perspectives/base.py` — 공통 인터페이스 (Perspective ABC)
2. `src/perspectives/kwangsoo.py` — 이광수 관점 (기존 프롬프트 분리)
3. `src/perspectives/ouroboros.py` — 포렌식 관점
4. `src/perspectives/quant_perspective.py` — 퀀트 관점
5. `src/perspectives/macro.py` — 매크로 관점
6. `src/perspectives/value.py` — 가치 관점
7. `src/consensus/voter.py` — 병렬 호출 + 판정 파싱
8. `src/consensus/scorer.py` — 합의도 계산

### Phase 2: scripts/ 분리 → [PRD](prds/phase2-scripts.md)
1. `scripts/daily.py` — 다관점 일일 분석
2. `scripts/portfolio.py` — 포트폴리오 관리
3. `scripts/screen.py` — 스크리닝
4. `scripts/perspective.py` — 단일 관점
5. SKILL.md 갱신

### Phase 3: 인과 그래프 (DEMOCRITUS-lite) → [PRD](prds/phase3-causal-graph.md)
1. `src/causal/builder.py` — 토픽 확장 + 인과 진술
2. `src/causal/triples.py` — 트리플 추출
3. `src/causal/graph.py` — 그래프 저장/조회
4. `scripts/build_causal.py` — 구축 스크립트
5. 매크로 관점에 인과 그래프 참조 연동

---

## 11. 투자 철학 기반 (참고 문서)

### 이광수 대표 핵심 원칙
1. 손실 줄이기, 이익 늘리기 (추적 손절매)
2. 오르는 주식은 팔지 않는다 (고점 -10% 매도)
3. 주도주 추종 (발명하지 말고 쫓아가라)
4. 3~5종목 집중
5. 기록 (매수이유, 손절가, 변동이유, 매도이유)
6. 분할 매수
7. 10시 전 매수 지양
8. 장기 투자 = 시장에 오래 남기
9. 예측 최소화, 대응 중심
10. 현금 = 기회

### auto-researchtrading 기법
- 6-시그널 앙상블 보팅 (Score 21.4 달성)
- ATR 트레일링 스톱
- RSI 과매수/과매도 출구
- BB 압축 필터

### MAXS 논문 핵심
- Lookahead + 앙상블 보팅으로 최적 추론 경로 선택
- Advantage + Step Variance + Slope Variance 복합 평가
- Trajectory Convergence로 조기 종료 (비용 절감)
- → 실용적 적용: 다관점 병렬 판정 + 합의도

### DEMOCRITUS 논문 핵심
- LLM에서 도메인별 인과 관계(causal triples) 대량 추출
- Geometric Transformer로 인과 매니폴드 구축
- 도메인 슬라이스 간 교차점 발견
- → 실용적 적용: 한국 주식 시장 인과 그래프 구축 + 배경 지식 참조

### OUROBOROS 프레임워크
- Triple-Gate 데이터 검증 (시간/맥락/편차)
- 9단계 정밀 분석 (매크로 → 펀더멘털 → 포렌식 → 최종 판정)
- Devil's Advocate (기관이 이 종목을 버린 이유 역설계)

---

## Clarifications

### Session 2026-03-28

- Q: 5개 관점 중 일부 LLM 호출 실패 시 동작? → A: 부분 실패 허용 — 성공한 관점만으로 합의도 계산, 실패 관점은 "N/A" 표시
- Q: 네이버 스크래핑 실패 시 PER/PBR 처리? → A: A+B 혼합 — 캐시 7일 이내면 캐시 사용(날짜 표시), 7일 초과 시 가치 관점 비활성화
- Q: 5개 관점 LLM 호출 방식? → A: 병렬 — 5개 동시 호출, asyncio/ThreadPool 사용
- Q: 관점 JSON 파싱 실패 시 처리? → A: 1회 재시도 후 N/A — 동일 프롬프트로 1회 재호출, 재실패 시 해당 관점 N/A
- Q: 퀀트 관점의 LLM 사용 여부? → A: 하이브리드 — 코드로 verdict/signals 계산, LLM은 reasoning 텍스트만 생성

---

## 12. 제약 사항

- **투자 면책**: 본 시스템은 투자 참고용이며, 투자 결과의 책임은 사용자에게 있음
- **데이터 지연**: pykrx/FDR 데이터는 전일 종가 기준. 실시간 아님
- **LLM 한계**: Claude API의 학습 데이터 기준일 이후 시장 이벤트는 반영 불가
- **한국 시장 전용**: KOSPI/KOSDAQ만 지원. 해외 주식 미지원
- **네이버 스크래핑**: 네이버 금융 페이지 구조 변경 시 PER/PBR 수집 실패 가능

---

## 13. 성공 기준

- 매일 실행하여 5분 이내에 포트폴리오 기반 행동 지침 제공
- 5개 관점의 판정이 JSON으로 구조화되어 shacs-bot에서 파싱 가능
- 합의 시 확신 있는 단일 조언, 분기 시 양측 근거 + 사용자 선택지
- 손절매 경고가 실제 손절가 이탈 시 즉시 발생
- 인과 그래프 구축 1시간 이내 완료 (500 토픽 기준)
