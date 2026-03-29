# Trading Oracle v2 — Feature Specification

> v1 SPEC: [../multi-perspective/SPEC.md](../multi-perspective/SPEC.md) (Phase 1~10 완료)
> v2는 v1의 파이프라인 위에 **인과추론 검증**, **정량 매크로 시계열**, **숙의 합의**를 추가한다.

## PRD 연결

| Phase | PRD | 상태 | 설명 |
|-------|-----|------|------|
| Phase 11 | [phase11-macro-timeseries.md](prds/phase11-macro-timeseries.md) | ✅ 완료 | 매크로 변수 정량 시계열 수집 |
| Phase 12 | [phase12-causal-verification.md](prds/phase12-causal-verification.md) | ✅ 완료 | Granger 기반 트리플 검증 + 신뢰도 태깅 |
| Phase 13 | [phase13-deliberative-consensus.md](prds/phase13-deliberative-consensus.md) | 🔲 미착수 | MAXS식 multi-round 숙의 합의 |

---

## 개요

### v1 → v2 핵심 변화

| 영역 | v1 | v2 |
|---|---|---|
| 인과 그래프 | LLM 생성 → 무검증 저장 | + Granger causality 검증 → 신뢰도/시차 태깅 |
| 매크로 데이터 | 웹 검색 텍스트 뉴스 | + 금리/환율/원자재 정량 시계열 (FDR) |
| 합의도 | 1회 독립 투표 → 단순 집계 | + multi-round deliberation (소수 의견 재판정) |
| 트리플 활용 | 1,500개 무차별 프롬프트 주입 | + 검증 통과 트리플만 선별 주입 |

### v2 설계 원칙

1. **v1 비파괴**: v1 파이프라인은 그대로 동작한다. v2 기능은 옵트인(플래그) 또는 자동 활성화.
2. **점진적 가치**: Phase 11 → 12 → 13 순서대로 구현. 각 Phase 단독으로도 가치를 낸다.
3. **비용 의식**: 일일 분석 비용이 v1 대비 2배를 넘지 않는다. 숙의는 분기 시에만 발동.
4. **검증 가능**: 모든 새 기능은 "이전 대비 개선됐는가?"를 측정할 수 있어야 한다.

---

## 1. 사용자 시나리오 (v2 추가분)

### 1-1. 검증된 인과 체인 기반 분석

**v1**: 매크로 관점이 "금리 인상 → 성장주 하락"을 LLM 상식에 기반해 서술.
**v2**: 동일한 서술에 "Granger p=0.003, lag 22일, 신뢰도 0.87"이 근거로 붙음.

```
📊 삼성전자 (005930) — 매크로 관점
  인과 체인 (데이터 검증됨):
    미국10년국채 금리 상승 →(lag 15일, p=0.01)→ 원달러 환율 상승
    원달러 환율 상승 →(lag 8일, p=0.02)→ 외국인 순매도 증가
    외국인 순매도 증가 →(lag 3일, p=0.04)→ 삼성전자 주가 하락압력
  현재 상태: 미국10년국채 4.35% (+12bp/5일) → 체인 활성화 가능성 높음
```

### 1-2. 숙의 합의 (분기 시)

**v1**: 3:2 분기 → 양측 근거 나열 후 사용자에게 선택 떠넘김.
**v2**: 분기 발생 시 소수 측에 다수 측 근거를 제시하고 재판정. 수렴하면 합의로 승격.

```
📊 한화에어로스페이스 — 숙의 결과

  Round 1: BUY 3 / SELL 2 → 분기
  Round 2: SELL 측(포렌식, 가치)에 BUY 측 근거 제시 후 재판정
    포렌식: SELL → HOLD 변경 (방산 수주 잔고 확인 후 리스크 하향)
    가치: SELL 유지 (PER 46 여전히 과도)
  최종: BUY 3 / HOLD 1 / SELL 1 → "약한 합의 (BUY)" 승격

  수렴 지표: Round 1→2 변동 1건, δ=0.04 < 0.1 → 종료
```

### 1-3. 매크로 대시보드 (정량)

**v1**: "금리 올라가고 있대요" (웹 뉴스 텍스트)
**v2**: 정량 데이터 + 방향/변화율 자동 계산

```
📈 매크로 환경 (2026-03-29)
  한국10년국채: 3.42% (5일 +8bp, 20일 +15bp) ↑
  미국10년국채: 4.35% (5일 +12bp, 20일 -3bp)  →
  원달러환율:   1,385원 (5일 +1.2%, 20일 +2.8%) ↑
  WTI원유:     $72.30 (5일 -2.1%, 20일 -5.4%)  ↓
  금:          $3,085 (5일 +0.8%, 20일 +3.2%)   ↑
```

---

## 2. 시스템 아키텍처 (v2 변경분)

### 2-1. 데이터 레이어 확장

```
[v1 데이터 레이어]
  pykrx/FDR → 종목 OHLCV, 지수
  네이버 금융 → PER/PBR
  DuckDuckGo → 웹 뉴스 텍스트

[v2 추가]
  FDR → 매크로 정량 시계열 (금리, 환율, 원자재)
       → src/data/macro.py (신규)
       → data/macro_series.parquet (캐시)
```

### 2-2. 인과추론 레이어 (신규)

```
[v1]
  builder.py → graph.json → macro.py 프롬프트 주입

[v2]
  builder.py → graph.json
                    ↓
  verifier.py → 트리플 ↔ 시계열 매핑 → Granger test
                    ↓
  graph_verified.json (신뢰도/시차 태깅된 트리플)
                    ↓
  macro.py → 검증 통과 트리플만 주입 (confidence ≥ threshold)
```

### 2-3. 합의 레이어 확장

```
[v1]
  5개 관점 → voter.py (1회 호출) → scorer.py (단순 투표)

[v2]
  5개 관점 → voter.py (Round 1)
                  ↓
  scorer.py → 분기 감지?
    YES → deliberator.py (소수 측 재판정, 최대 3 round)
              ↓ 수렴 체크 (δ < threshold)
          scorer.py (최종 합의도)
    NO  → scorer.py (기존대로)
```

---

## 3. 매크로 변수 정량 시계열 → Phase 11

### 3-1. 수집 대상

| 변수명 | FDR 심볼 | 단위 | 갱신 주기 |
|--------|----------|------|----------|
| 한국 10년 국채금리 | `KR10YT=RR` | % | 일간 |
| 미국 10년 국채금리 | `US10YT=RR` | % | 일간 |
| 원달러 환율 | `USD/KRW` | 원 | 일간 |
| WTI 원유 | `CL=F` | USD/bbl | 일간 |
| 금 | `GC=F` | USD/oz | 일간 |
| 코스피 | `KS11` | pt | 일간 (기존) |
| 코스닥 | `KQ11` | pt | 일간 (기존) |
| 나스닥 | `IXIC` | pt | 일간 (기존) |
| S&P 500 | `US500` | pt | 일간 (기존) |
| 한국 3년 국채금리 | `KR3YT=RR` | % | 일간 |
| 미국 2년 국채금리 | `US2YT=RR` | % | 일간 |
| 달러 인덱스 | `DX=F` | pt | 일간 |

### 3-2. 저장 형식

```
data/macro_series.parquet
  columns: date(index), KR10YT, US10YT, USD_KRW, WTI, GOLD, ...
  rows: 최근 2년 (약 500 거래일)
```

**왜 parquet**: 시계열 데이터는 JSON보다 parquet이 10x 빠르고 5x 작음. pandas 네이티브.

### 3-3. 수집 정책

- **초기**: 최근 2년치 일괄 수집 (1회)
- **일일**: 분석 실행 시 마지막 수집일 이후 데이터만 증분 수집
- **실패 시**: 개별 심볼 실패는 해당 변수만 스킵. 전체 중단 없음.
- **캐시 만료**: 당일 수집 데이터가 있으면 재수집하지 않음

### 3-4. 파생 지표 (자동 계산)

| 지표 | 계산 | 용도 |
|------|------|------|
| 변화율 (5d, 20d) | pct_change | 매크로 대시보드, 프롬프트 주입 |
| 차분 (1d) | diff | Granger test 입력 (정상성 확보) |
| 장단기 금리차 | US10YT - US2YT | 경기 침체 시그널 |
| 실질금리 (근사) | 국채금리 - 기대인플레 proxy | 성장주/가치주 로테이션 |

### 3-5. 프롬프트 주입 형식

```
### 매크로 정량 데이터
- 한국10년국채: 3.42% (5일 +8bp, 20일 +15bp)
- 미국10년국채: 4.35% (5일 +12bp, 20일 -3bp)
- 원달러환율: 1,385원 (5일 +1.2%, 20일 +2.8%)
- WTI원유: $72.30 (5일 -2.1%, 20일 -5.4%)
- 장단기금리차: +0.42%p (5일 -5bp) — 정상
```

이 섹션은 기존 `web_macro` 텍스트 뉴스와 **병행** 제공. 대체가 아님.

---

## 4. 인과추론 검증 엔진 → Phase 12

### 4-1. 개요

v1의 인과 그래프(1,500 트리플)는 LLM이 생성한 "상식적 인과 관계"다. v2는 이 트리플을 실제 시계열 데이터로 **검증**하여 신뢰도를 태깅한다.

**목표**: "LLM이 말한 것"과 "데이터가 보여주는 것"이 일치하는 트리플만 프롬프트에 주입.

### 4-2. 검증 파이프라인

```
Step 1: 노드 → 시계열 매핑
  "금리 인상"           → KR10YT (diff > 0)
  "반도체 기업 영업이익"  → 005930 close (proxy)
  "원화 약세"           → USD_KRW (diff > 0)

Step 2: Granger Causality Test
  grangercausalitytests(df[[effect, cause]], maxlag=30)
  → p-value, optimal lag

Step 3: 신뢰도 태깅
  p < 0.01 → confidence: high (0.9)
  p < 0.05 → confidence: medium (0.7)
  p < 0.10 → confidence: low (0.5)
  p ≥ 0.10 → confidence: none (0.0) — 검증 실패

Step 4: 방향 일치성 확인
  트리플 relation이 "increases"인데 상관이 음수 → 불일치 → 신뢰도 0.0
```

### 4-3. 노드 → 시계열 매핑

전체 2,436개 노드 중 정량 시계열에 매핑 가능한 것은 일부. 두 가지 전략 병행:

**전략 A: 규칙 기반 매핑 (핵심 50~100개)**

```python
NODE_SERIES_MAP = {
    # 매크로 변수
    "금리 인상": ("KR10YT", "diff", "positive"),
    "금리 인하": ("KR10YT", "diff", "negative"),
    "미국 금리 인상": ("US10YT", "diff", "positive"),
    "원화 약세": ("USD_KRW", "diff", "positive"),
    "원화 강세": ("USD_KRW", "diff", "negative"),
    "유가 상승": ("WTI", "diff", "positive"),
    "유가 하락": ("WTI", "diff", "negative"),
    "코스피 상승": ("KS11", "pct_change", "positive"),
    "코스피 하락": ("KS11", "pct_change", "negative"),

    # 섹터/종목 proxy
    "반도체 기업 이익 증가": ("005930", "pct_change", "positive"),  # 삼성전자
    "반도체 주가 상승": ("005930", "pct_change", "positive"),
    "자동차 수출 증가": ("005380", "pct_change", "positive"),  # 현대차
    "방산 수주 증가": ("012450", "pct_change", "positive"),  # 한화에어로
    "은행 이익 증가": ("105560", "pct_change", "positive"),  # KB금융
    # ...
}
```

**전략 B: LLM 자동 매핑 (확장용)**

매핑되지 않은 노드에 대해 LLM에 "이 노드를 가장 잘 대리하는 시계열은?"을 질문.
결과를 `data/node_series_map.json`에 캐시. 수동 검토 후 승인.

### 4-4. 검증 결과 저장 형식

```json
{
  "metadata": {
    "verified_at": "2026-03-29",
    "total_triples": 1500,
    "mappable_triples": 320,
    "verified_triples": 185,
    "failed_triples": 135
  },
  "triples": [
    {
      "subject": "미국 금리 인상",
      "relation": "decreases",
      "object": "성장주 밸류에이션",
      "domain": "글로벌매크로",
      "verification": {
        "status": "verified",
        "method": "granger",
        "p_value": 0.003,
        "optimal_lag_days": 22,
        "direction_match": true,
        "confidence": 0.9,
        "subject_series": "US10YT",
        "object_series": "KS11",
        "verified_at": "2026-03-29"
      }
    },
    {
      "subject": "반도체 수요 증가",
      "relation": "increases",
      "object": "반도체 기업 영업이익",
      "domain": "반도체",
      "verification": {
        "status": "unmappable",
        "reason": "subject 노드에 대응하는 시계열 없음",
        "confidence": null
      }
    }
  ]
}
```

### 4-5. 검증 정책

- **검증 주기**: 인과 그래프 재구축 시 (분기 1회) + 매크로 시계열 2년치 사용
- **최소 데이터**: Granger test에 최소 60 거래일(~3개월) 필요. 부족 시 해당 쌍 스킵.
- **다중 lag 테스트**: lag 1~30일 범위. 최소 p-value의 lag를 optimal로 선택.
- **정상성**: ADF test로 비정상 시계열 감지 → 차분 적용 후 검증.
- **다중 비교 보정**: Bonferroni correction 적용 (검증 쌍 수에 따라 유의수준 조정).

### 4-6. 프롬프트 주입 변경

```
[v1] — 무차별 주입
### 인과 그래프 참조 (배경 지식)
- 금리 인상 → (decreases) → 성장주 밸류에이션
- 반도체 수요 증가 → (increases) → 반도체 기업 영업이익
  (검증 안 된 15개 트리플 전부 주입)

[v2] — 선별 주입
### 인과 그래프 참조 (데이터 검증됨)
- 미국 금리 인상 →(22일 lag, p=0.003)→ 성장주 하락 [신뢰도: 높음]
- 원달러 환율 상승 →(8일 lag, p=0.02)→ 외국인 순매도 [신뢰도: 중간]
  (검증 통과 + confidence ≥ 0.5인 트리플만)

### 인과 그래프 참조 (미검증, 참고용)
- 반도체 수요 증가 → (increases) → 반도체 기업 영업이익 [미검증]
  (매핑 불가 트리플은 별도 섹션, 축소 주입)
```

### 4-7. 검증 임계값

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `GRANGER_MAX_LAG` | 30 | 최대 시차 (거래일) |
| `GRANGER_P_THRESHOLD` | 0.05 | 유의수준 |
| `MIN_DATA_POINTS` | 60 | 최소 데이터 포인트 |
| `CONFIDENCE_HIGH` | 0.01 | p < 0.01 → 신뢰도 높음 |
| `CONFIDENCE_MED` | 0.05 | p < 0.05 → 신뢰도 중간 |
| `CONFIDENCE_LOW` | 0.10 | p < 0.10 → 신뢰도 낮음 |
| `INJECT_MIN_CONFIDENCE` | 0.5 | 프롬프트 주입 최소 신뢰도 |

---

## 5. 숙의 합의 시스템 (MAXS-deliberation) → Phase 13

### 5-1. 개요

v1의 합의도는 1회 투표로 끝난다. 분기(DIVIDED) 시 사용자에게 양측 근거를 보여줄 뿐, 관점 간 교차 검증이 없다.

v2는 MAXS 논문의 Lookahead + Convergence 개념을 차용하여, **분기 발생 시에만** 소수 측 관점에 다수 측 근거를 제시하고 재판정하는 숙의 라운드를 추가한다.

### 5-2. 발동 조건

숙의는 **비용이 드는 작업**(LLM 재호출)이므로 분기 시에만 발동:

```
Round 1 결과가 다음 중 하나일 때만 숙의 발동:
  - "분기" (DIVIDED): 최다 득표가 동률
  - "약한 합의" (moderate): 3:2 분기 — 소수 2표가 뒤집히면 강한 합의로 승격 가능

발동하지 않는 경우:
  - "만장일치" (very high): 숙의 불필요
  - "강한 합의" (high): 4:1 또는 4/4 — 충분한 합의
  - "판정 보류" (insufficient): 유효 관점 부족 — 숙의해도 의미 없음
```

### 5-3. 숙의 프로세스

```
Round 1: 기존 5개 관점 독립 판정 (v1과 동일)
         결과: BUY 3 (이광수, 매크로, 퀀트) / SELL 2 (포렌식, 가치)

  분기 감지 → 숙의 발동

Round 2: 소수 측(SELL 2)에 다수 측 근거를 컨텍스트로 제공하고 재판정
  프롬프트: "다음은 BUY 측 관점의 근거입니다: [이광수 reasoning], [매크로 reasoning], [퀀트 reasoning].
            이 근거를 고려한 후에도 당신의 판단(SELL)을 유지합니까?
            유지한다면 왜 BUY 측 근거가 불충분한지 반론하세요.
            변경한다면 어떤 근거가 설득력 있었는지 명시하세요."

  결과 수집:
    포렌식: SELL → HOLD (변경. 이유: "방산 수주 잔고 데이터 확인 후 리스크 재평가")
    가치: SELL 유지 (이유: "PER 46은 어떤 성장 기대에도 과도. BUY 측 근거는 가격 무시")

  수렴 체크:
    Round 1→2 변동: 1건 (5개 중 1개 변경)
    δ = 변동 비율 = 1/5 = 0.2

Round 3 (δ > 0.1이면):
  이번엔 변경한 관점(포렌식 HOLD)과 유지한 관점(가치 SELL)에 갱신된 전체 상황 제시
  ...

수렴 조건: δ ≤ 0.1 (5개 중 0~0.5개 변경) 또는 Round 3 도달 시 강제 종료
```

### 5-4. 수렴 판정

MAXS의 Trajectory Convergence를 적용:

```
δ = |Round N 변경 관점 수| / |전체 유효 관점 수|

δ ≤ 0.1  → 수렴. 종료.
δ > 0.1  → 미수렴. 다음 라운드.
Round 3  → 강제 종료. 미수렴 상태로 보고.
```

**최대 비용**: 숙의 시 소수 측만 재호출.
- Round 2: 소수 측 2개 관점 × 1회 = 2 LLM 호출
- Round 3: 최대 2개 관점 × 1회 = 2 LLM 호출
- 최악: 4 LLM 추가 호출 (v1 대비 +80% 비용, 분기 시에만)

### 5-5. 숙의 프롬프트 설계

```
당신은 {perspective_name} 관점의 투자 분석가입니다.

## Round 1에서 당신의 판단
{original_verdict}: {original_reasoning}

## 다수 측({majority_verdict}) 근거
{majority_perspectives_reasoning}

## 지시
1. 다수 측 근거를 면밀히 검토하세요.
2. 당신의 원래 판단을 유지하거나 변경하세요.
3. 유지한다면: 다수 측의 어떤 근거가 불충분한지 구체적으로 반론하세요.
4. 변경한다면: 어떤 근거가 설득력 있었는지 명시하세요.

반드시 아래 JSON 형식으로 응답하세요:
```json
{
  "verdict": "BUY/SELL/HOLD",
  "changed": true/false,
  "reasoning": ["..."],
  "reason": "한 줄 요약",
  "rebuttal_or_acceptance": "변경/유지 이유"
}
```
```

### 5-6. 숙의 결과 출력 형식

```json
{
  "consensus_verdict": "BUY",
  "consensus_label": "숙의 합의",
  "confidence": "moderate",
  "deliberation": {
    "triggered": true,
    "reason": "Round 1 분기 (BUY 3 / SELL 2)",
    "rounds": 2,
    "converged": true,
    "delta": 0.2,
    "changes": [
      {
        "perspective": "ouroboros",
        "round": 2,
        "from": "SELL",
        "to": "HOLD",
        "reason": "방산 수주 잔고 데이터 확인 후 리스크 재평가"
      }
    ]
  },
  "vote_summary": {"BUY": 3, "SELL": 1, "HOLD": 1, "N/A": 0},
  "perspectives": [...]
}
```

### 5-7. MAXS 요소 매핑

| MAXS 원논문 | v2 적용 | 설명 |
|---|---|---|
| Lookahead (Rollout) | 소수 측 재판정 | 다수 근거를 본 후의 미래 상태를 시뮬레이션 |
| Advantage Score | 변경 전후 합의도 변화 | 숙의로 합의가 개선됐는가? |
| Step-Level Variance (Lyapunov) | Round 간 verdict 변동률 δ | 판정이 안정화되고 있는가? |
| Trajectory Convergence | δ ≤ 0.1 → 종료 | 더 숙의해도 결과가 안 변함 → 조기 종료 |
| Slope-Level Variance (Lipschitz) | 미적용 | 이산 투표(BUY/SELL/HOLD)에는 연속 기울기 개념 부적합 |

---

## 6. 파일 구조 (v2 신규)

```
src/
  data/
    macro.py          # Phase 11: 매크로 시계열 수집/캐시
  causal/
    graph.py          # 기존 유지
    builder.py        # 기존 유지
    verifier.py       # Phase 12: Granger 검증 엔진
    node_mapper.py    # Phase 12: 노드 → 시계열 매핑
  consensus/
    voter.py          # 기존 유지
    scorer.py         # 기존 유지
    deliberator.py    # Phase 13: 숙의 라운드 관리

data/
  causal_graph.json           # 기존 유지 (v1 원본)
  causal_graph_verified.json  # Phase 12: 검증 결과
  macro_series.parquet        # Phase 11: 매크로 시계열
  node_series_map.json        # Phase 12: 노드 매핑 캐시

scripts/
  verify_causal.py    # Phase 12: 검증 실행 스크립트
```

---

## 7. 구현 순서 및 의존성

```
Phase 11 (매크로 시계열)  ← 선행 조건 없음. 독립 착수 가능.
    ↓
Phase 12 (인과추론 검증)  ← Phase 11 필요 (시계열 데이터)
    ↓
Phase 13 (숙의 합의)     ← 선행 조건 없음. Phase 11/12와 독립.
                           단, Phase 12의 검증된 트리플을 숙의 근거에 활용하면 시너지.
```

**추천 순서**: Phase 11 → Phase 13 → Phase 12

- Phase 11은 Phase 12의 전제 조건이면서, 단독으로도 매크로 프롬프트 품질을 올림.
- Phase 13은 Phase 11/12와 독립이므로 병렬 착수 가능. 사용자 체감 가치가 즉각적.
- Phase 12는 Phase 11 완료 후 착수. 가장 높은 기술적 가치이지만 의존성이 있음.

---

## 8. 비용 예산 (v2 추가분)

### 8-1. Phase 11 (매크로 시계열)

- API 비용: $0 (FDR는 무료)
- 연산 비용: 무시 가능 (pandas 연산)
- 저장: ~2MB (parquet, 2년 × 12 변수)

### 8-2. Phase 12 (인과추론 검증)

- API 비용: 전략 B(LLM 자동 매핑) 사용 시 ~$0.50 (1회성, 매핑 대상 노드 수에 비례)
- 연산 비용: Granger test ~320쌍 × 30 lag = 수 초 (statsmodels)
- 저장: ~500KB (verified JSON)
- 추가 의존성: `statsmodels` (ADF test + Granger test)

### 8-3. Phase 13 (숙의 합의)

- 분기 발생 시에만 비용 추가
- 최악: 4 LLM 호출 추가 (~$0.08)
- 전체 분석 대비: v1 $0.10 → v2 최대 $0.18 (분기 시)
- 만장일치/강한 합의 시: 추가 비용 $0

### 8-4. 일일 예산 비교

| 시나리오 | v1 | v2 | 증가 |
|----------|----|----|------|
| 합의 (숙의 미발동) | $0.10 | $0.10 | +0% |
| 분기 (숙의 발동) | $0.10 | $0.18 | +80% |
| 분기 + Round 3 | $0.10 | $0.26 | +160% |
| 월 평균 (분기 30% 가정) | $3.00 | $3.72 | +24% |

---

## 9. 성공 기준 (v2)

### Phase 11
- [ ] 12개 매크로 변수의 2년치 시계열을 수집하여 parquet 저장
- [ ] 수집 실패 시 개별 변수만 스킵, 전체 파이프라인 중단 없음
- [ ] 매크로 정량 데이터가 프롬프트에 주입되어 LLM 분석에 활용됨
- [ ] `--no-macro-series` 플래그로 v1 동작 복원 가능

### Phase 12
- [ ] 매핑 가능한 트리플 중 50% 이상에서 Granger test 실행 완료
- [ ] 검증 결과(p-value, lag, confidence)가 트리플에 태깅되어 저장
- [ ] 검증 통과 트리플만 프롬프트에 우선 주입, 미검증은 별도 섹션
- [ ] 방향 불일치 트리플(relation과 상관 부호 반대)이 자동 필터링됨
- [ ] `uv run scripts/verify_causal.py --json`으로 검증 실행 및 결과 조회

### Phase 13
- [ ] 분기/약한 합의 시 숙의 라운드가 자동 발동
- [ ] 숙의 후 합의도가 개선된 비율이 50% 이상 (분기 → 약한 합의 이상)
- [ ] 최대 3 라운드 내 수렴 (δ ≤ 0.1)
- [ ] 숙의 과정(변경/유지 이유)이 출력에 포함
- [ ] `--no-deliberation` 플래그로 v1 동작 복원 가능

### 전체
- [ ] v2 기능 전체 비활성화 시 v1과 동일하게 동작 (비파괴 원칙)
- [ ] 일일 분석 비용이 v1 대비 월 평균 50% 이내 증가

---

## 10. 제약 사항 (v2 추가분)

- **Granger ≠ 인과**: Granger causality는 "예측 기여도"이지 진정한 인과 증명이 아님. 사용자에게 "통계적 선행 관계"로 표현.
- **매핑 한계**: 1,500 트리플 중 정량 시계열 매핑 가능한 것은 20~30%. 나머지는 미검증 상태로 유지.
- **정상성 가정**: 금융 시계열은 비정상(non-stationary)이 대부분. 차분으로 정상성 확보하되, 구조 변화(structural break) 시기에는 검증 결과 신뢰도 하락.
- **숙의 편향**: 소수 측에 다수 측 근거를 보여주면 동조 압력(anchoring bias)이 발생할 수 있음. 이를 완화하기 위해 프롬프트에 "유지 시 반론 필수"를 명시.
- **비용 상한**: 숙의는 최대 3 라운드. 무한 루프 방지.

---

## Clarifications

### Session 2026-03-29

- Q: v2는 v1을 대체하는가? → A: 아니다. v1 위에 얹는 확장. 모든 v2 기능은 플래그로 비활성화 가능.
- Q: Granger test 외 다른 인과추론 방법은? → A: v2 범위에서는 Granger만. SCM/do-calculus는 v3 이후 검토.
- Q: 숙의 시 다수 측도 재판정하는가? → A: 아니다. 소수 측만 재판정. 다수 측 재판정은 비용 대비 효과 낮음.
- Q: Phase 11~13의 번호가 11부터인 이유? → A: v1이 Phase 1~10. v2는 연속 번호.
