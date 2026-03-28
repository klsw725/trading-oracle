# PRD: Phase 6 — 시장 레짐 감지 (Market Regime Detection)

> **SPEC 참조**: [SPEC.md](../SPEC.md)
> **상태**: ✅ 완료 (M1~M3 구현)
> **우선순위**: P1 — Phase 5 완료 후 착수
> **선행 조건**: Phase 1 (시그널 레이어), Phase 2 (scripts 분리) 완료

---

## 문제

5개 관점이 각자 시장 상황을 독자적으로 해석한다. "지금이 하락장인가"에 대한 시스템 수준의 공통 판단이 없어서 관점 간 불일치의 원인이 불명확하다. 사용자도 현재 시장이 어떤 국면인지 한눈에 파악할 수 없다.

## 솔루션

코스피 지수 데이터에서 시장 레짐(bull/bear/sideways)을 코드로 분류하여 `collect_market_data()` 결과에 포함. 모든 관점 프롬프트의 시장 컨텍스트 섹션에 자동 삽입.

**판정 기준** (LLM 불필요, 비용 0):
- `bull`: 코스피 20일 수익률 > 3% AND 종가 > EMA(20)
- `bear`: 코스피 20일 수익률 < -3% AND 종가 < EMA(20)
- `sideways`: 그 외

---

## 마일스톤

### M1: 레짐 감지 로직
- [x] `src/common.py`에 `_detect_regime()` 추가
- [x] `collect_market_data()` 결과에 `regime` 필드 포함
- [x] bull/bear/sideways 3분류 + 한글 라벨 + 설명

**검증**: 코스피 20일 -12.9% → `bear` (하락 추세) 정확 ✅

### M2: 관점 프롬프트 연동
- [x] `PerspectiveInput.market_context`에 regime 자동 포함 (run_multi/run_single 양쪽)
- [x] kwangsoo, ouroboros, macro 3개 관점 user prompt에 레짐 정보 표시

**검증**: 3개 관점 프롬프트의 "시장 환경" 섹션에 `**시장 레짐: 하락 추세**` 삽입 ✅

### M3: 출력 및 문서
- [x] `daily.py`, `main.py` 터미널 출력에 레짐 표시 (색상: bull=green, bear=red, sideways=yellow)
- [x] JSON 출력에 `regime` 필드 포함 (`market_data.regime`)
- [x] 스냅샷에 레짐 자동 기록 (market_data 포함)
- [x] PRD, SPEC.md 갱신

**검증**: collect_market_data() 결과에 regime 필드 확인 ✅

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성. |
| 2026-03-28 | M1~M3 구현: _detect_regime() (EMA+모멘텀 기반), market_context 연동, 3개 관점 프롬프트 삽입, 터미널/JSON 출력, SPEC 갱신. |
