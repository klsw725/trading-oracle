# PRD: Phase 9 — 시그널 엔진 v2 (변동성 적응 + 독립성 강화)

> **SPEC 참조**: [SPEC.md](../SPEC.md)
> **상태**: 📋 PRD 작성 완료
> **우선순위**: P0 — 시그널 레이어는 전체 파이프라인의 기반
> **선행 조건**: Phase 8 완료, 백테스트 인프라(`scripts/backtest.py`) 존재

---

## 문제

백테스트 결과, 현재 시그널 엔진이 미국 시장에서 **통계적으로 유의미한 엣지가 없음**이 확인됨.

### 정량적 근거

| 종목 | BULLISH 5일 적중 | 5일 샤프 | 20일 샤프 |
|------|-----------------|---------|---------|
| AAPL | 47.9% (동전 이하) | -0.26 | -0.05 |
| NVDA | 59.3% | -0.08 | 0.14 |
| TSLA | 53.8% | -0.03 | 0.11 |
| 삼성전자 | 66.0% | 0.32 | 0.53 |

삼성전자의 양호한 수치도 일방적 상승 추세 기간의 편향 — BEARISH 적중률 24%가 이를 증명.

### 구조적 원인 (5가지)

**1. 시그널 상관성**: 추세 시그널 5개의 평균 상관계수 0.43~0.47. "6개 독립 투표"가 아니라 "3개 상관 클러스터". 4/6 기준이 너무 쉽게 달성됨.

**2. BB 양쪽 공짜 투표**: 미장 대형주에서 BB compressed 96~97%. Bull/Bear 양쪽에 항상 +1표 → 실질적으로 "5개 중 3개 동의" 수준으로 기준 하락. BEARISH 판정의 100%에 BB가 기여.

**3. 고정 임계값**: 모멘텀 3% 기준이 변동성을 무시.
- 삼성(std 3.11%): 3%는 의미 있는 움직임
- Apple(std 1.39%): 3%는 2시그마 수준 → 거의 항상 발동하거나 거의 안 발동

**4. 볼륨 미사용**: OHLCV에 volume이 있지만 6개 시그널 어디에도 사용 안 됨. AAPL에서 고거래량 BULLISH 적중률 63% vs 저거래량 45% (+18%p 차이).

**5. 레짐 미연동**: `_detect_regime()`이 존재하지만 `compute_signals()`와 분리됨. 상승장에서 BEARISH가 역신호 되는 구조적 모순.

---

## 솔루션 개요

`compute_signals()` 함수를 v2로 개선. **기존 인터페이스(입출력 형식)는 유지**하여 하위 파이프라인 변경 최소화.

### 설계 원칙

1. **하위 호환**: `compute_signals()` 반환 dict 구조 유지. 기존 키 보존. 신규 키는 추가만.
2. **백테스트 검증 필수**: 모든 변경은 `scripts/backtest.py`로 A/B 비교. 개선 안 되면 머지 안 함.
3. **과최적화 경계**: 특정 종목/기간에 맞추지 않음. 4종목(삼성, AAPL, NVDA, TSLA) 전체에서 개선 확인.
4. **점진적 적용**: M1~M4를 순차 적용하며 각 단계마다 백테스트 비교.

---

## 마일스톤

### M1: 변동성 정규화 임계값 (가장 임팩트 큼)

**변경**: 모멘텀 시그널의 고정 3%/1.5% 임계값을 ATR 기반 상대값으로 교체.

```python
# 현재 (v1)
threshold = 0.03  # 고정 3%
mom_bull = ret_mom > threshold

# 개선 (v2)
atr_pct = atr / current_price  # ATR을 가격 대비 비율로
threshold = max(atr_pct * 1.0, 0.01)  # ATR 1배, 최소 1%
mom_bull = ret_mom > threshold
```

- [ ] `compute_signals()`에 ATR 기반 동적 임계값 구현
- [ ] 단기 모멘텀도 동일하게 `threshold * 0.5` → `atr_pct * 0.5`
- [ ] 반환값에 `threshold_used` 필드 추가 (디버깅/투명성)
- [ ] `config.yaml`에 `momentum_threshold_atr_mult` 옵션 추가 (기본값 1.0)

**검증 기준**: AAPL BULLISH 5일 적중률 47.9% → 55%+ 개선. 4종목 평균 적중률 상승.

### M2: BB 시그널 재설계

**변경**: BB 압축(방향 중립)을 **BB 위치 기반(방향성 있음)**으로 교체.

```python
# 현재 (v1): 압축 여부만 → 양쪽 공짜 투표
bb_compressed = bb_pctile < 80
bull_votes에 bb_compressed 추가
bear_votes에 bb_compressed 추가

# 개선 (v2): 가격의 BB 내 위치로 방향 투표
sma = np.mean(closes[-bb_period:])
std = np.std(closes[-bb_period:])
upper = sma + 2 * std
lower = sma - 2 * std
bb_position = (current_price - lower) / (upper - lower)  # 0~1

bb_bull = bb_position > 0.8  # 상단 밴드 근접 (돌파 시도)
bb_bear = bb_position < 0.2  # 하단 밴드 근접 (붕괴 시도)
# 0.2~0.8 구간 → 투표 안 함 (기권)
```

- [ ] BB 시그널을 위치 기반으로 교체
- [ ] bb_compressed는 참고 지표로 보존 (반환값에 유지)
- [ ] Bull/Bear 투표에서 BB가 기권 가능하도록 투표 로직 수정

**검증 기준**: BEARISH 판정 중 BB 기여율 100% → 50% 이하. BEARISH 적중률 상승.

### M3: 볼륨 확인 시그널 추가

**변경**: 6번째 시그널(BB)을 방향성 있게 바꿨으므로, 7번째로 볼륨 시그널 추가.

```python
# 볼륨 시그널: 현재 거래량 vs 20일 평균
vol_avg = np.mean(volumes[-20:])
vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
vol_bull = vol_ratio > 1.2 and ret_short > 0  # 거래량 증가 + 상승
vol_bear = vol_ratio > 1.2 and ret_short < 0  # 거래량 증가 + 하락
# 거래량 평균 이하 → 기권 (시그널 강도 부족)
```

- [ ] 볼륨 시그널 구현 (7번째 시그널)
- [ ] `min_votes` 기본값 4 유지 (7개 중 4개 — 더 엄격해짐)
- [ ] 반환값에 `volume_signal` 추가
- [ ] config에 `volume_threshold` 옵션 (기본값 1.2)

**검증 기준**: 전체 적중률 상승. 특히 AAPL에서 고거래량 필터 효과 확인.

### M4: 레짐 필터 연동

**변경**: `compute_signals()`에 선택적 `regime` 파라미터 추가. 레짐에 따라 verdict 보정.

```python
def compute_signals(df, config, regime=None):
    ...
    # 기존 투표 계산 후
    if regime == "bear":
        # 하락장에서 BULLISH → min_votes 상향 (5/7)
        if verdict == "BULLISH" and bull_votes < 5:
            verdict = "NEUTRAL"
    elif regime == "bull":
        # 상승장에서 BEARISH → min_votes 상향 (5/7)
        if verdict == "BEARISH" and bear_votes < 5:
            verdict = "NEUTRAL"
```

- [ ] `compute_signals()`에 `regime` 파라미터 추가 (기본값 None = 기존 동작)
- [ ] `analyze_ticker()`에서 regime 전달 연동
- [ ] 레짐별 min_votes 오버라이드 로직

**검증 기준**: 상승장 BEARISH 역신호 비율 감소. 전략 샤프 비율 개선.

---

## 영향 범위 분석

### 직접 변경
| 파일 | 변경 내용 |
|------|----------|
| `src/signals/technical.py` | M1~M4 시그널 로직 변경 |
| `config.yaml` | 신규 설정 키 추가 |
| `src/common.py` | `analyze_ticker()`에 regime 전달 (M4) |

### 하위 호환 확인 (변경 불필요해야 함)
| 파일 | 의존 방식 | 호환성 |
|------|----------|--------|
| `src/perspectives/quant_perspective.py` | `signals` dict에서 verdict, bull_votes 읽음 | ✅ 키 이름 유지 |
| `src/perspectives/kwangsoo.py` | `signals` dict에서 수치 읽음 | ✅ 키 이름 유지 |
| `src/perspectives/ouroboros.py` | `signals` dict에서 수치 읽음 | ✅ 키 이름 유지 |
| `src/perspectives/macro.py` | `signals` dict에서 수치 읽음 | ✅ 키 이름 유지 |
| `src/perspectives/value.py` | `signals` dict 거의 안 읽음 | ✅ 무관 |
| `src/consensus/scorer.py` | PerspectiveResult만 소비 | ✅ 무관 |
| `src/performance/tracker.py` | 스냅샷에 verdict 저장 | ✅ verdict 값 동일 |
| `src/screener/leading.py` | `compute_signals()` 결과 사용 | ✅ 키 이름 유지 |
| `src/output/formatter.py` | 시그널 카드 출력 | ⚠️ 신규 시그널 표시 추가 필요 (선택) |

### 퀀트 관점 특별 고려
`quant_perspective.py`의 `_code_verdict_to_perspective()`와 `_build_signals_dict()`가 시그널 dict를 직접 매핑:
- `_build_signals_dict()`에 volume_signal, bb_position 추가 필요
- `_build_user_prompt()`에 7번째 시그널 표시 추가 필요
- verdict 매핑 로직은 변경 불필요 (BULLISH/BEARISH/NEUTRAL 유지)

---

## 검증 프로토콜

### A/B 백테스트 비교

각 마일스톤마다 4종목 × 450일 백테스트 실행:

```bash
# v1 (현재) 기준선
uv run scripts/backtest.py 005930 AAPL NVDA TSLA --days 450

# v2 (개선) 비교
uv run scripts/backtest.py 005930 AAPL NVDA TSLA --days 450
```

### 통과 기준 (ALL 충족)

| 지표 | v1 현재 | v2 최소 목표 |
|------|--------|-------------|
| AAPL BULLISH 5일 적중률 | 47.9% | 55%+ |
| NVDA BULLISH 5일 적중률 | 59.3% | 60%+ |
| TSLA BULLISH 5일 적중률 | 53.8% | 55%+ |
| 4종목 평균 5일 전략 샤프 | -0.01 | 0.10+ |
| 삼성 BULLISH 5일 적중률 | 66.0% | 60%+ (퇴보 없음) |

### 회귀 방지

- 삼성전자 적중률이 60% 미만으로 하락하면 해당 변경 롤백
- 기존 파이프라인(`daily.py`, `portfolio` 등) 정상 동작 확인

---

## 비적용 항목 (의도적 제외)

1. **시그널 수 축소**: 기존 6→5로 줄이는 방안은 고려했으나, 볼륨 추가 + BB 재설계로 7개 유지가 더 유연. 상관성 문제는 임계값 정규화로 완화.
2. **RSI 극단 투표**: RSI를 50선 대신 과매수/과매도에서만 투표하는 방안. 변경 폭이 크고 백테스트에서 효과 불확실. M1~M4 결과 보고 후속 검토.
3. **시장별 파라미터 분리**: 변동성 정규화(M1)로 대부분 해결. 별도 프로파일은 과최적화 리스크.
4. **MACD/EMA 기간 조정**: 파라미터 튜닝은 과최적화 직행. 구조적 개선 우선.

---

## 일정 (예상)

| 마일스톤 | 예상 작업량 | 누적 |
|---------|-----------|------|
| M1 (임계값 정규화) | 30분 | 30분 |
| M1 백테스트 검증 | 10분 | 40분 |
| M2 (BB 재설계) | 20분 | 1시간 |
| M2 백테스트 검증 | 10분 | 1시간 10분 |
| M3 (볼륨 시그널) | 20분 | 1시간 30분 |
| M3 백테스트 검증 | 10분 | 1시간 40분 |
| M4 (레짐 필터) | 30분 | 2시간 10분 |
| M4 백테스트 검증 + 퀀트 관점 연동 | 20분 | 2시간 30분 |

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-29 | 백테스트 결과 기반 분석 완료. PRD 작성. |
| 2026-03-29 | M1~M4 구현 시도. BB 투표 변경(M2)과 볼륨 투표(M3)는 AAPL/TSLA 성능 악화로 투표 참여에서 제외. 최종: ATR 임계값(M1) + BB위치/볼륨 정보필드 + 레짐 필터 인프라(M4). v1 대비 회귀 없음 확인. |
