# PRD: Phase 8 — 1-Step 종목 추천 파이프라인

> **SPEC 참조**: [SPEC.md §1-3 (주도주 탐색)](../SPEC.md#1-3-주도주-탐색)
> **상태**: ✅ 완료 (M1~M3 구현)
> **우선순위**: P1
> **선행 조건**: Phase 1 (다관점), Phase 2 (scripts), 스크리너 구현 완료

---

## 문제

"뭐 살까?"에 대해 사용자가 2번 명령을 실행하고 직접 BUY 합의를 눈으로 찾아야 한다.

1. `screen.py --json` → 후보 리스트
2. `daily.py --screen --json` → 전체 다관점 분석 → 직접 BUY 찾기

직장인 아침 5분 루틴에 맞지 않음.

## 솔루션

`scripts/recommend.py` — 스크리닝 → 시그널 필터 → 다관점 분석 → BUY 합의 종목만 반환하는 1-step 파이프라인.

**비용 제어**: 시그널 필터(Bull 4/6+)로 LLM 호출 대상을 사전 필터링.

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  스크리닝    │ →  │ 시그널 필터  │ →  │ 다관점 분석  │ →  │ BUY 합의만   │
│  시총+모멘텀 │    │ Bull 4/6+    │    │ 5관점 병렬   │    │  반환        │
│  (비용 0)    │    │ (비용 0)     │    │ (LLM 호출)   │    │              │
└─────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
    ~6종목              ~2종목             ~$0.20              0~2종목
```

## CLI 인터페이스

```bash
# 기본: 한국 주도주에서 BUY 추천
uv run scripts/recommend.py --json

# 미국 시장
uv run scripts/recommend.py --market US --json

# 후보 수 조정
uv run scripts/recommend.py --top 10 --json

# 시그널 필터 없이 전체 분석 (비용 높음)
uv run scripts/recommend.py --no-filter --json

# 시그널만 (LLM 없이, 빠른 스크리닝)
uv run scripts/recommend.py --no-llm --json
```

## JSON 출력 형식

```json
{
  "date": "2026-03-28",
  "market": "KR",
  "regime": {"regime": "bear", "label": "하락 추세", "description": "..."},
  "screened": 6,
  "signal_filtered": 2,
  "recommendations": [
    {
      "ticker": "012450",
      "name": "한화에어로스페이스",
      "price": 1335000,
      "score": 9,
      "signals": {"verdict": "BULLISH", "bull_votes": 4, "bear_votes": 2},
      "consensus": {
        "consensus_verdict": "BUY",
        "consensus_label": "강한 합의",
        "confidence": "high",
        "perspectives": [...]
      }
    }
  ],
  "no_recommendation_reason": null
}
```

`recommendations`가 빈 배열이면 `no_recommendation_reason`에 이유 표시:
- `"시그널 Bull 종목 없음"` — 시장 전체가 약세
- `"BUY 합의 종목 없음"` — 시그널은 Bull이나 관점 분석에서 부정적
- `"스크리닝 실패"` — 데이터 수집 실패

## 터미널 출력 형식

```
🎯 종목 추천 (2026-03-28, 하락 추세)
  스크리닝: 6개 후보 → 시그널 필터: 2개 통과

  🟢 한화에어로스페이스 (012450) — 1,335,000원
     합의도: 강한 합의 (BUY)
     이광수: BUY — 주도주 + 모멘텀 양수
     퀀트: BUY — Bull 4/6
     매크로: BUY — 방산 수요 확대
     가치: SELL — PER 46 고평가
     포렌식: HOLD — 리스크 없음

  추천 없음 시:
  ⚠️ 현재 BUY 합의 종목이 없습니다 (시장 레짐: 하락 추세)
```

---

## 마일스톤

### M1: 추천 파이프라인 로직
- [x] `src/common.py`에 `run_recommend()` 추가
- [x] 스크리닝 → 시그널 필터(Bull 4/6+) → 다관점 분석 → BUY 합의 필터
- [x] `--no-filter` 시 시그널 필터 스킵
- [x] `--no-llm` 시 시그널까지만 (LLM 없이 빠른 후보)
- [x] US 시장 지원 (`--market US`)

**검증**: 6개 스크리닝 → 2개 시그널 필터 통과 (LG에너지솔루션, 삼성바이오로직스) ✅

### M2: CLI 스크립트 + 출력
- [x] `scripts/recommend.py` 생성
- [x] 터미널 Rich 출력 + `--json` 지원
- [x] 추천 없음 시 이유 표시 + 하락장 현금 권고

**검증**: `--help`, `--no-llm` 모드 동작 확인 ✅

### M3: SKILL.md + SPEC.md 갱신
- [x] SKILL.md 매핑 테이블에 "뭐 살까?" / "미국주식 뭐 살까?" 추가
- [x] SKILL.md에 종목 추천 섹션 추가
- [x] SPEC.md PRD 테이블에 Phase 8 추가

**검증**: SKILL.md 매핑 테이블 반영 확인 ✅

---

## 진행 로그

| 날짜 | 내용 |
|------|------|
| 2026-03-28 | PRD 작성 + M1~M3 구현: run_recommend(), recommend.py, SKILL.md/SPEC.md 갱신. |
