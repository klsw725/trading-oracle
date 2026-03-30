# Trading Oracle v3 — Self-Learning Oracle

> v1 SPEC: [../multi-perspective/SPEC.md](../multi-perspective/SPEC.md) (Phase 1~10)
> v2 SPEC: [../v2/SPEC.md](../v2/SPEC.md) (Phase 11~13)
> v3는 축적된 성과 데이터를 활용하여 **시스템이 스스로 개선**하는 자가 학습 루프를 완성한다.

## PRD 연결

| Phase | PRD | 상태 | 설명 |
|-------|-----|------|------|
| Phase 14 | [phase14-hit-pattern.md](prds/phase14-hit-pattern.md) | ✅ 완료 | 적중 패턴 분석 + 레짐별 관점 성적표 |
| Phase 15 | [phase15-regime-weights.md](prds/phase15-regime-weights.md) | ✅ 완료 | 레짐별 적응형 가중치 자동 조정 |
| Phase 16 | [phase16-prompt-tuning.md](prds/phase16-prompt-tuning.md) | ✅ 완료 | 프롬프트 자가 튜닝 (LLM 기반 자기 개선) |
| Phase 17 | [phase17-forex-factor.md](prds/phase17-forex-factor.md) | ✅ 완료 | 환율 팩터 시스템 (다통화 + 레짐 + 포지션 반영) |
| Phase 18 | [phase18-backtest.md](prds/phase18-backtest.md) | ✅ 완료 | 시그널 백테스트 프레임워크 |

---

## 개요

### v2 → v3 핵심 변화

| 영역 | v2 | v3 |
|---|---|---|
| 가중치 | 전체 기간 적중률 기반 고정 가중치 | **레짐별 동적 가중치** (상승장/하락장/횡보 따로) |
| 피드백 | 성과 리포트 수동 확인 | **자동 패턴 분석 + 학습 루프** |
| 프롬프트 | 수동 작성, 변경 없음 | **적중률 기반 자가 튜닝 제안** |
| 의사결정 | 매 실행 독립 판정 | **과거 유사 상황 참조** |

### v3 설계 원칙

1. **데이터 의존**: v3 기능은 스냅샷 30개+ 축적 후 의미. 그 전에는 v2 동작과 동일.
2. **과최적화 경계**: 적중률 패턴이 통계적으로 유의해야만 가중치 변경. 최소 표본 수 요구.
3. **투명성**: 가중치 변경 사유를 항상 기록. "왜 이 관점의 가중치가 낮아졌는가"를 사용자가 확인 가능.
4. **비파괴**: v2 파이프라인은 그대로 동작. v3 기능은 데이터 충분할 때만 자동 활성화.

---

## 1. 사용자 시나리오 (v3 추가분)

### 1-1. 관점별 성적표

```
📊 관점별 성적표 (최근 30일)

  이광수:   적중 15/22 (68%) — bear장 적중률 80%, bull장 50%
  포렌식:   적중 18/22 (82%) — 전 레짐 안정적
  퀀트:     적중 10/22 (45%) — bull장에서 과다 SELL 판정
  매크로:   적중 14/22 (64%) — sideways 약세
  가치:     적중 12/22 (55%) — bear장 강세

  현재 레짐: bear → 이광수(0.80), 포렌식(0.82) 가중치 상향
```

### 1-2. 레짐별 자동 가중치 조정

**v2**: 전체 기간 적중률 → 단일 가중치 세트
**v3**: 레짐(bull/bear/sideways)별 적중률 → 현재 레짐에 맞는 가중치 자동 선택

```
📈 적응형 가중치 (현재 레짐: bear)

  이광수: 0.80 (bear 적중률 기반) ← v2: 0.68
  포렌식: 0.82 (전 레짐 안정)     ← v2: 0.82
  퀀트:   0.30 (bear 적중률 낮음) ← v2: 0.45
  매크로: 0.70 (bear 적중률 양호) ← v2: 0.64
  가치:   0.75 (bear 적중률 높음) ← v2: 0.55
```

### 1-3. 프롬프트 자가 튜닝 제안

```
🔧 프롬프트 튜닝 제안 (퀀트 관점 — 적중률 45%)

  문제: bull장에서 SELL 과다 판정 (Bull 시그널을 무시하는 경향)
  분석: RSI 50선 기준이 bull장에서 너무 보수적
  제안: "bull 레짐에서는 RSI 40 이하만 Bear로 판정" 추가
  
  적용하시겠습니까? [Y/N]
```

---

## 2. Phase 14: 적중 패턴 분석

### 목표
축적된 스냅샷에서 관점별/레짐별/종목별 적중 패턴을 자동 분석하여 성적표를 생성.

### 입력
- `data/snapshots/*.json` (일별 추천 스냅샷)
- `market_data.regime` (각 스냅샷 시점의 시장 레짐)
- Phase 4의 `evaluate_snapshot()` 결과

### 출력
- 관점별 전체 적중률
- **관점별 × 레짐별 적중률 행렬** (핵심)
- 관점별 × verdict별 적중률 (BUY 맞추는 관점 vs SELL 맞추는 관점)
- 시계열 추세 (적중률이 시간에 따라 개선/악화되는지)

### 활성화 조건
- 스냅샷 30개 이상
- 각 레짐에서 최소 5개 이상의 평가 가능 스냅샷

### 기술 설계

```python
def analyze_hit_patterns(min_snapshots: int = 30) -> dict | None:
    """적중 패턴 분석.
    
    Returns:
        {
            "overall": {"kwangsoo": {"total": 22, "hits": 15, "rate": 68.2}, ...},
            "by_regime": {
                "bull": {"kwangsoo": {"total": 10, "hits": 5, "rate": 50.0}, ...},
                "bear": {"kwangsoo": {"total": 8, "hits": 6, "rate": 75.0}, ...},
                "sideways": {"kwangsoo": {"total": 4, "hits": 4, "rate": 100.0}, ...},
            },
            "by_verdict": {
                "BUY": {"kwangsoo": {"total": 8, "hits": 6, "rate": 75.0}, ...},
                "SELL": {"kwangsoo": {"total": 10, "hits": 7, "rate": 70.0}, ...},
                ...
            },
            "trend": {
                "kwangsoo": {"slope": 0.02, "improving": True},
                ...
            }
        }
    """
```

### 위치
- `src/performance/pattern_analyzer.py` (신규)
- `scripts/performance.py`에 `patterns` 서브커맨드 추가

---

## 3. Phase 15: 레짐별 적응형 가중치

### 목표
Phase 14의 레짐별 적중률을 가중치로 변환하여, 현재 시장 레짐에 맞는 관점 가중치를 자동 선택.

### v2 vs v3 가중치

```
v2: compute_perspective_weights()
  → 전체 기간 적중률 → 단일 가중치 세트
  → bull/bear/sideways 구분 없음

v3: compute_regime_weights(regime)
  → 현재 레짐의 적중률 → 해당 레짐 최적 가중치
  → 레짐 변경 시 가중치 자동 전환
```

### 설계

```python
def compute_regime_weights(regime: str, min_per_regime: int = 5) -> dict | None:
    """레짐별 관점 가중치 계산.
    
    Args:
        regime: "bull" | "bear" | "sideways"
        min_per_regime: 해당 레짐에서 최소 평가 가능 스냅샷 수
    
    Returns:
        {"kwangsoo": 0.80, "ouroboros": 0.82, ...} 또는 None (데이터 부족)
    """
```

### 통합 방식
- `scorer.py`의 `compute_consensus(weights=)`에 전달되는 가중치가 레짐별로 전환됨
- `common.py:run_multi_perspective()`에서:
  1. 현재 레짐 확인
  2. `compute_regime_weights(regime)` 호출
  3. 데이터 부족 시 v2 `compute_perspective_weights()` 폴백
  4. 그마저도 부족 시 동등 가중치

### 안전장치
- 특정 레짐의 샘플이 5개 미만이면 해당 레짐은 전체 가중치 사용
- 가중치 최소값 0.1 (관점 완전 무시 방지)
- 가중치 변경 시 로그 기록

---

## 4. Phase 16: 프롬프트 자가 튜닝

### 목표
적중률이 지속적으로 낮은 관점의 프롬프트를 LLM이 분석하고 개선 제안을 자동 생성.

### 발동 조건
- 특정 관점의 최근 30일 적중률이 40% 미만
- 해당 관점의 적중률 추세가 하락 중 (Phase 14 trend.slope < 0)

### 프로세스

```
1. 부진 관점 식별 (Phase 14 패턴 분석)
2. 해당 관점의 최근 10건 오답 사례 수집
3. LLM에 "이 관점이 왜 틀렸는지 분석해줘" 요청
4. LLM이 프롬프트 개선 제안 생성
5. 사용자에게 제안 표시 → 수동 승인 후 적용
```

### 안전장치
- **자동 적용 없음**: 항상 사용자 승인 후 적용 (프롬프트 변경은 위험)
- 1회/월 실행 제한 (과도한 튜닝 방지)
- 변경 전/후 A/B 비교 가능 (이전 프롬프트 백업)
- 적중률이 이미 60%+ 이면 튜닝 대상 아님

### 출력 형식

```json
{
  "perspective": "quant",
  "current_hit_rate": 0.45,
  "analysis": "bull 레짐에서 RSI 50선 기준이 과도하게 보수적...",
  "suggestion": "RSI 판정 기준을 레짐별로 분기: bull 40/60, bear 50/50",
  "prompt_diff": "- RSI: >50 Bull, <50 Bear\n+ RSI (bull): >40 Bull, <40 Bear\n+ RSI (bear): >50 Bull, <50 Bear",
  "confidence": 0.6,
  "estimated_improvement": "+8~12%p"
}
```

---

## 5. 선행 조건 및 타임라인

### 선행 조건
- **스냅샷 30개+**: 약 6주 일일 실행 필요 (주말 제외)
- **레짐 다양성**: bull, bear, sideways 각각 5개+ 스냅샷 (시장 상황에 따라 수 개월 소요 가능)

### 착수 시점
| Phase | 최소 스냅샷 | 예상 착수 가능 시점 |
|-------|-----------|-------------------|
| 14 (패턴 분석) | 30개 | ~6주 후 |
| 15 (레짐 가중치) | 30개 + 레짐 다양성 | ~8주 후 |
| 16 (프롬프트 튜닝) | 60개 + Phase 14 결과 | ~12주 후 |

### 현재 해야 할 것
**매일 `uv run scripts/daily.py --json` 실행하여 스냅샷 축적.**

---

## 6. 비용 영향

| Phase | 추가 비용 |
|-------|----------|
| 14 (패턴 분석) | $0 (통계 계산만) |
| 15 (레짐 가중치) | $0 (가중치 계산만) |
| 16 (프롬프트 튜닝) | ~$0.50/월 (LLM 분석 1회/월) |

---

## 7. 리스크

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 과최적화 | 특정 레짐에 과적합 → 레짐 전환 시 성능 급락 | 최소 표본 수 요구 + 전체 기간 폴백 |
| 레짐 오분류 | 잘못된 레짐 → 잘못된 가중치 | Phase 6 레짐 감지 검증 + 레짐 전환 시 경고 |
| 프롬프트 퇴화 | 자가 튜닝이 오히려 악화 | 수동 승인 + A/B 비교 + 이전 백업 |
| 데이터 편향 | 특정 시장 상황에만 스냅샷 축적 | 레짐별 최소 표본 요구 + 경고 표시 |
