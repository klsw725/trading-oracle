# PRD: Phase 5 — 성과 기반 적응형 관점 가중치

> **SPEC 참조**: [SPEC.md §4 (합의도 시스템)](../SPEC.md#4-합의도-시스템-maxs-lite)
> **상태**: ✅ 완료 (M1~M4 구현)
> **우선순위**: P1 — Phase 4 완료 후 착수
> **선행 조건**: Phase 4 (추천 성과 추적) 완료

---

## 문제

합의도 시스템(`scorer.py`)이 5개 관점을 동등하게 취급한다. 실제로는 시장 상황에 따라 관점별 적중률이 다르다. Phase 4에서 성과 추적 인프라를 구축했지만, 축적된 데이터를 의사결정 개선에 활용하지 않고 있다. 피드백 루프가 열려 있다.

## 솔루션

축적된 스냅샷의 관점별 5일 적중률을 가중치로 변환하여 합의도 계산에 반영한다. 가중 투표(weighted voting)로 적중률 높은 관점의 발언권을 높인다.

**핵심 원칙**: 단순함. 베이지안/레짐 분류 없이, 순수 적중률 기반 가중치만 적용.

## 설계

### 가중치 계산

```python
# 관점별 5일 적중률 → 가중치
# 예: kwangsoo 70% 적중 → weight 0.7
# 적중 데이터 없으면 → weight 1.0 (동등)
# 최소 5개 스냅샷 미만 → 전체 동등 가중치 (cold start)
```

### 가중 합의도

```
가중 투표값 = sum(weight[p] for p in same_verdict_perspectives)
총 가중치 = sum(weight[p] for p in valid_perspectives)
가중 합의도 = max_weighted_votes / 총 가중치

판정 기준은 기존과 동일하되, 단순 카운트 대신 가중합 사용:
  가중 합의도 >= 0.8 → "강한 합의"
  가중 합의도 >= 0.6 → "약한 합의"
  기타 → "분기"
  만장일치는 변경 없음 (5/5 동일이면 가중치 무관)
```

### 가중치 저장

별도 파일 없음. 매 실행 시 스냅샷에서 on-the-fly 계산.

---

## 마일스톤

### M1: 가중치 계산 로직
- [x] `src/performance/tracker.py`에 `compute_perspective_weights()` 추가
- [x] 5일 윈도우 적중률 기반. 최소 5개 평가 가능 스냅샷 필요.
- [x] cold start: 5개 미만이면 `None` 반환 → 기존 동등 가중치 사용

**검증**: 스냅샷 1개 → `None` 반환 ✅. 5개 이상이면 dict 반환.

### M2: 가중 합의도 계산
- [x] `scorer.py:compute_consensus()`에 `weights: dict | None` 파라미터 추가
- [x] weights=None이면 기존 동등 가중치 동작 (하위 호환 100%)
- [x] weights 있으면 가중 투표로 합의도 계산
- [x] 출력에 `weighted: true/false`, `weights_used` 필드 추가

**검증**: 3개 시나리오 검증 ✅ (동등→약한합의, 가중→분기, 만장일치→가중치무관)

### M3: 파이프라인 연동
- [x] `common.py:run_multi_perspective()`에서 가중치 로드 → scorer에 전달
- [x] `--no-weights` 플래그로 가중치 비활성화 지원 (daily.py, main.py)
- [x] 합의도 카드에 `(가중)` 태그 표시

**검증**: daily.py/main.py `--no-weights` 플래그 동작 확인 ✅

### M4: 리포트 및 문서
- [x] `scripts/performance.py report`에 현재 가중치 표시 (활성화 시 테이블, 미활성 시 안내 메시지)
- [x] PRD, SPEC.md, SKILL.md 갱신

**검증**: report 명령 cold start 메시지 표시 확인 ✅

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성. |
| 2026-03-28 | M1~M4 구현: compute_perspective_weights() (적중률→가중치), 가중 합의도 계산 (scorer.py), 파이프라인 연동 (common.py + --no-weights), 리포트 가중치 섹션 (performance.py), SPEC/SKILL 갱신. |
