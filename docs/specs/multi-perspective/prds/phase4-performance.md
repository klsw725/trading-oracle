# PRD: Phase 4 — 추천 성과 추적 시스템

> **SPEC 참조**: [SPEC.md](../SPEC.md)
> **상태**: ✅ 완료 (M1~M4 구현)
> **우선순위**: P1 — Phase 1~3 완료 후 즉시 착수
> **선행 조건**: Phase 1 (다관점 시스템), Phase 2 (scripts/ 분리) 완료

---

## 문제

시스템이 매일 구체적 행동 지침(매수/매도/관망 + 가격)을 제시하지만, 그 추천이 실제로 맞았는지 추적하는 수단이 없다. 피드백 루프가 없으면:
- 어떤 관점이 잘 맞는지 알 수 없음
- confidence 값의 실제 의미를 검증할 수 없음
- 만장일치가 분기보다 정말 더 정확한지 알 수 없음
- 전략 최적화의 기반이 없음

## 솔루션

1. 매일 다관점 분석 실행 시 추천 내역을 자동 스냅샷 저장
2. N일 후 실제 가격과 비교하여 적중 여부 평가
3. 관점별/합의도별/확신도별 적중률 리포트 생성

부가: 데이터 파이프라인 최적화 (중복 OHLCV fetch 제거, 종목 병렬 분석)

---

## 마일스톤

### M1: 스냅샷 저장 인프라
- [x] `src/performance/__init__.py`
- [x] `src/performance/tracker.py` — `save_snapshot()`, `load_snapshot()`, `list_snapshots()`
- [x] 스냅샷 형식: `data/snapshots/YYYY-MM-DD.json`
- [x] `common.py:run_multi_perspective()`에서 자동 저장 연동

**스냅샷 저장 형식**:
```json
{
  "date": "2026-03-28",
  "market": {"kospi": {"close": 2500.0}, "kosdaq": {"close": 700.0}},
  "recommendations": {
    "005930": {
      "name": "삼성전자",
      "price": 179700,
      "consensus_verdict": "SELL",
      "consensus_confidence": "high",
      "consensus_label": "강한 합의",
      "vote_summary": {"BUY": 1, "SELL": 3, "HOLD": 1, "N/A": 0},
      "perspectives": [
        {"perspective": "kwangsoo", "verdict": "SELL", "confidence": 0.9},
        ...
      ]
    }
  }
}
```

### M2: 성과 평가 로직
- [x] `evaluate_snapshot()` — 과거 스냅샷 vs 현재 가격 비교
- [x] 적중 판정 기준:
  - BUY → 5일 후 수익률 > 0% = 적중
  - SELL → 5일 후 수익률 < 0% = 적중
  - HOLD → |5일 후 수익률| < 3% = 적중
  - DIVIDED/INSUFFICIENT → 미평가
- [x] 5일/20일 두 가지 평가 윈도우
- [x] 관점별 개별 적중률도 계산

### M3: 리포트 CLI
- [x] `scripts/performance.py report` — 전체 성과 요약
- [x] `scripts/performance.py list` — 저장된 스냅샷 목록
- [x] `scripts/performance.py detail YYYY-MM-DD` — 특정 날짜 상세
- [x] `--json` 출력 지원
- [x] Rich 터미널 출력

### M4: 데이터 파이프라인 최적화
- [x] `analyze_ticker()`에서 ohlcv를 결과에 포함 (메모리 내 재사용, `_ohlcv` 키)
- [x] `run_multi_perspective()`에서 중복 `fetch_ohlcv()` 제거
- [x] `run_single_perspective()`에서도 동일 최적화 적용
- [x] SKILL.md, SPEC.md 갱신

---

## 적중 판정 상세

### 합의 verdict 적중
| 추천 | 5일 적중 조건 | 20일 적중 조건 |
|------|-------------|--------------|
| BUY | return > 0% | return > 3% |
| SELL | return < 0% | return < -3% |
| HOLD | \|return\| < 3% | \|return\| < 5% |
| DIVIDED | 미평가 | 미평가 |
| INSUFFICIENT | 미평가 | 미평가 |

### 개별 관점 적중
각 관점의 verdict도 동일 기준으로 개별 적중률 계산.

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성. |
| 2026-03-28 | M1~M4 구현: tracker.py (스냅샷 저장/평가/리포트), performance.py (CLI), common.py 파이프라인 최적화 (중복 fetch 제거 + 자동 스냅샷 저장), SKILL.md/SPEC.md 갱신. |
