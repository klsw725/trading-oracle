# PRD: Phase 11 — 매크로 변수 정량 시계열 수집

> **SPEC 참조**: [SPEC.md §3 (매크로 변수 정량 시계열)](../SPEC.md#3-매크로-변수-정량-시계열--phase-11)
> **상태**: 🔲 미착수
> **우선순위**: P1 — v2 최우선. Phase 12의 전제 조건.
> **선행 조건**: 없음 (독립 착수 가능)

---

## 문제

매크로 관점(`macro.py`)이 금리/환율/원자재 데이터를 **웹 검색 텍스트 뉴스**로만 참조한다. "금리가 올랐다"는 정보는 있지만 "얼마나, 며칠간, 어떤 추세로"는 없다. 정량 시계열이 없으면 Phase 12의 Granger 검증도 불가능하다.

## 솔루션

FinanceDataReader를 사용하여 12개 매크로 변수의 일간 시계열을 수집하고, parquet으로 캐시한다. 수집된 데이터는 (1) 매크로 프롬프트에 정량 주입, (2) Phase 12 Granger 검증의 입력으로 사용.

---

## 마일스톤

### M1: 매크로 시계열 수집 모듈
- [ ] `src/data/macro.py` 생성
- [ ] 12개 변수 FDR 수집 (§3-1 대상)
- [ ] 개별 변수 실패 시 스킵 (전체 중단 없음)
- [ ] `data/macro_series.parquet`에 저장
- [ ] 초기 수집 (2년치) + 증분 수집 (마지막 수집일 이후)

**검증**: `uv run -c "from src.data.macro import fetch_macro_series; df = fetch_macro_series(); print(df.shape, df.columns.tolist())"` → (500+, 12) 확인

### M2: 파생 지표 계산
- [ ] 변화율 (5일, 20일) 자동 계산
- [ ] 차분 (1일) — Granger test 입력용
- [ ] 장단기 금리차 (US10YT - US2YT)
- [ ] 캐시 만료 정책: 당일 수집분 존재 시 재수집 스킵

**검증**: 파생 지표 컬럼이 DataFrame에 포함. 차분 컬럼의 ADF test p < 0.05 (정상성 확인)

### M3: 프롬프트 주입
- [ ] `macro.py`의 `_build_user_prompt()`에 정량 매크로 데이터 섹션 추가
- [ ] 기존 `web_macro` 텍스트와 **병행** 제공 (대체 아님)
- [ ] 매크로 시계열 수집 실패 시 기존 동작 유지 (graceful degradation)

**검증**: 매크로 관점 프롬프트에 "한국10년국채: 3.42% (5일 +8bp)" 형태의 정량 데이터가 포함

### M4: CLI 통합
- [ ] `collect_market_data()`에 매크로 시계열 수집 연동
- [ ] `--no-macro-series` 플래그로 비활성화 가능
- [ ] `uv run scripts/daily.py --json` 출력에 매크로 정량 데이터 포함

**검증**: `--no-macro-series` 플래그 시 v1 동작과 동일한 출력

---

## 의존성

- `pyarrow` 또는 `fastparquet`: parquet 읽기/쓰기. pandas 의존성으로 이미 설치되어 있을 가능성 높음. 없으면 추가.
- `FinanceDataReader`: 기존 의존성. 추가 설치 불필요.

## 비용

- API: $0 (FDR 무료)
- 저장: ~2MB
- 연산: 무시 가능
