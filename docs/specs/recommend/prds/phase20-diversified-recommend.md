# PRD: Phase 20 — 추천 후보군 확장 + 다양성 선택

> **SPEC 참조**: [SPEC.md](../SPEC.md)
> **상태**: 📝 초안
> **우선순위**: P1
> **선행 조건**: Phase 8 종목 추천(완료), Phase 19 상관 리스크 관리(완료)

---

## 문제

현재 `scripts/recommend.py` 파이프라인은 시장 전체를 탐색하는 것처럼 보이지만, 실제로는 스크리닝 초기에 시가총액 상위 소수만 잘라서 본다.

이 구조는 다음 문제를 만든다.

1. **대형주 편향**
   - `top_n`이 후보군 확보 단계에 바로 적용되어, 사실상 초대형주 몇 개만 분석 대상으로 들어간다.
   - `ALL` 기본 흐름도 체감상 코스피 대형주 중심으로 수렴한다.

2. **시장 의미 불명확**
   - `US`는 있으나 `KR`은 없다.
   - `ALL`이 한국 전체 시장처럼 오해되기 쉽고, 실제 의미도 일관되지 않다.

3. **섹터 쏠림**
   - 최종 분석 대상 선정 시 섹터 다양성 제약이 없어 반도체/자동차/바이오/빅테크 등 특정 섹터가 추천 리스트를 독식할 수 있다.

4. **설명 가능성 부족**
   - 사용자는 “왜 이 종목이 들어왔고 다른 종목은 빠졌는지”를 시장/섹터/점수 관점에서 이해하기 어렵다.

## 솔루션

추천 파이프라인을 다음 두 단계로 분리한다.

1. **넓은 후보군 확보**: 선택한 시장별로 충분히 넓은 universe를 먼저 구성
2. **다양성 선택**: 기존 점수(score)를 유지하되, 시장/섹터 편중을 완화하는 greedy selection으로 최종 `top_n` 분석 대상을 선택

즉, 기존의 “시총 상위 몇 개만 바로 자르기”를 제거하고:

```text
시장 선택
→ 넓은 후보군 확보
→ 기존 점수 계산
→ 다양성 선택으로 top_n 압축
→ 시그널 필터
→ 다관점 분석
→ BUY 합의 종목 반환
```

## 설계 원칙

- **시장 옵션 명확화**: `KR`, `US`, `ALL` 의미를 대칭적으로 정의한다.
- **외과적 변경**: 기존 시그널 필터, 다관점 분석, action_plan 계산은 유지한다.
- **설명 가능성**: “점수 + 다양성 규칙”으로 최종 후보 선정 이유를 설명할 수 있어야 한다.
- **점진적 완화**: 다양성 규칙 때문에 후보가 부족해지면 제약을 순차 완화한다.
- **비파괴**: 섹터 정보가 부족해도 기존처럼 점수 기반 추천은 동작해야 한다.

---

## 마일스톤

### M1: 시장 옵션 재정의

**목표**: `--market` 의미를 대칭적으로 정리하고 기본값을 명확히 한다.

**변경 파일**:
- `scripts/recommend.py`
- `src/common.py`
- `src/screener/leading.py`

- [ ] 지원 시장을 다음과 같이 정의:
  - `KOSPI`
  - `KOSDAQ`
  - `KR` = `KOSPI + KOSDAQ`
  - `NASDAQ`
  - `NYSE`
  - `US` = `NASDAQ + NYSE`
  - `ALL` = `KR + US`
- [ ] `scripts/recommend.py`의 기본 `--market` 값을 `KR`로 변경
- [ ] 도움말/출력 문구에서 `ALL != KR` 의미를 명확히 표기
- [ ] `run_recommend()`와 스크리너 호출부가 위 시장 semantics를 동일하게 사용하도록 통일

**검증 기준**:
- `KR`는 한국 전체, `US`는 미국 전체, `ALL`은 한국+미국 전체로 일관 동작
- 기존 `KOSPI`, `KOSDAQ`, `NASDAQ`, `NYSE` 단일 시장 옵션은 그대로 유지

---

### M2: 넓은 후보군 확보 단계 분리

**목표**: `top_n`을 universe 확보 단계가 아니라 “최종 분석 대상 수”로 재정의.

**변경 파일**:
- `src/screener/leading.py`

- [ ] 현재 `sort_values("Marcap").head(top_n)` 방식 제거
- [ ] 시장별 universe 확보용 내부 함수 분리
  - 예: `_load_market_universe(market, universe_size)`
- [ ] 시장별 기본 universe 크기 도입
  - `KOSPI`, `KOSDAQ`, `NASDAQ`, `NYSE` 각각 기본 50개
- [ ] 복합 시장은 하위 시장별 universe를 결합
  - `KR` → `KOSPI 50 + KOSDAQ 50`
  - `US` → `NASDAQ 50 + NYSE 50`
  - `ALL` → `KOSPI 50 + KOSDAQ 50 + NASDAQ 50 + NYSE 50`
- [ ] 후보 객체에 최소 메타데이터 포함
  - `market`
  - `score`
  - `sector` (가능한 경우)
  - `selection_reason` 또는 후속 선택 설명용 필드

**검증 기준**:
- `top_n=6`이어도 초기 후보군은 6개보다 훨씬 넓게 확보됨
- 코스닥/NYSE 종목이 구조적으로 초기에 배제되지 않음

---

### M3: 다양성 선택(greedy diversified selection)

**목표**: 넓은 후보군에서 최종 `top_n` 분석 대상만 다양성 규칙으로 압축.

**변경 파일**:
- `src/screener/leading.py` 또는 신규 `src/screener/select.py`
- `src/portfolio/correlation.py` (필요 시 섹터 분류 재사용)

- [ ] 후보를 `score` 내림차순으로 정렬
- [ ] greedy selection 함수 추가
  - 예: `select_diversified_candidates(candidates, top_n, market, config)`
- [ ] 기본 제약:
  - 동일 섹터 중복 최소화 (기본 `sector_cap=1`)
  - 복합 시장(`KR`, `US`, `ALL`)에서는 하위 시장 완전 독식 완화
- [ ] 제약은 **하드 고정**이 아니라 **우선 규칙**으로 동작
- [ ] 후보 부족 시 아래 순서로 완화:
  1. 섹터 중복 금지 유지 + 시장 균형 유지
  2. 시장 균형 완화
  3. 섹터 cap 완화
  4. 점수 순으로 잔여 슬롯 채움
- [ ] 선택 결과에 설명 메타데이터 추가
  - 예: `selected_by: ["score", "sector_diversity"]`
  - 예: `skipped_reason: "same_sector_cap"`

**검증 기준**:
- `KR` 추천에서 코스피/코스닥 한쪽 독식 가능성이 낮아짐
- 최종 후보가 동일 섹터만으로 채워질 확률이 크게 줄어듦
- 후보가 적은 날에도 빈 리스트 대신 완화 규칙으로 정상 선택됨

---

### M4: 섹터 분류 소스 보강

**목표**: 다양성 선택에 필요한 섹터 정보를 한국/미국 시장 모두에서 최대한 안정적으로 확보.

**변경 파일**:
- `src/screener/leading.py`
- `src/portfolio/correlation.py`

- [ ] 섹터 정보 우선순위 정의:
  1. 거래소 listing의 sector/industry 컬럼
  2. 기존 내부 매핑 규칙
  3. 종목명 키워드 기반 fallback
  4. 없으면 `기타`
- [ ] `classify_sector()`를 추천 파이프라인에서도 재사용 가능하게 정리
- [ ] 한국/미국 종목 모두 `sector` 필드를 일관된 문자열로 반환

**검증 기준**:
- 미국 시장에서 종목명 키워드만으로 분류 실패하더라도 listing 정보가 있으면 우선 사용
- 섹터 정보가 없는 종목도 추천 파이프라인이 중단되지 않음

---

### M5: 추천 파이프라인/출력 통합

**목표**: 추천 결과에 universe/selection 메타데이터를 포함하여 설명 가능성 강화.

**변경 파일**:
- `src/common.py`
- `scripts/recommend.py`
- `src/output/formatter.py`

- [ ] `run_recommend()` 반환값에 추가 메타데이터 포함:
  ```python
  {
      "market": "KR",
      "universe_size": 100,
      "universe_breakdown": {"KOSPI": 50, "KOSDAQ": 50},
      "screened": 6,
      "selection_constraints": {
          "sector_cap": 1,
          "prefer_market_balance": True,
          "relaxed": False,
      },
  }
  ```
- [ ] 추천 카드/JSON에서 필요 시 `sector`, `market`을 표시 가능하게 확장
- [ ] `--no-llm` 모드에서도 다양성 선택이 먼저 적용되도록 순서 유지

**검증 기준**:
- 사용자가 “왜 6개만 분석했는지”를 universe/selection 정보로 이해 가능
- `--no-llm`과 기본 모드가 동일한 후보 선택 로직을 공유

---

## 데이터 흐름

```text
[M1] market semantics 정리
      KR / US / ALL 정의
              │
[M2] leading.py
      시장별 넓은 universe 확보
              │
[M3] diversified selector
      score + 시장/섹터 다양성 선택
              │
[M5] run_recommend()
      시그널 필터 → 다관점 분석 → BUY 필터
              │
[M5] formatter / JSON
      universe 메타데이터 + 추천 결과 출력
```

---

## config.yaml 추가 섹션

```yaml
recommend:
  default_market: KR
  universe_size:
    KOSPI: 50
    KOSDAQ: 50
    NASDAQ: 50
    NYSE: 50
  diversification:
    sector_cap: 1
    prefer_market_balance: true
    relax_market_balance_if_needed: true
    relax_sector_cap_if_needed: true
```

### 설정 의미
- `default_market`: CLI 기본 시장
- `universe_size`: 시장별 초기 후보군 크기
- `sector_cap`: 1차 선택에서 동일 섹터 허용 개수
- `prefer_market_balance`: 복합 시장에서 하위 시장 분산 우선 여부

---

## 안전장치

| 장치 | 설명 |
|------|------|
| 데이터 부족 폴백 | 특정 시장에서 데이터 수집 실패 시 남은 시장 후보로 계속 진행 |
| 섹터 미분류 허용 | `sector="기타"`로 폴백하여 추천 파이프라인 지속 |
| 점진적 완화 | 시장/섹터 제약 때문에 후보가 부족하면 단계적으로 완화 |
| 비파괴 원칙 | 기존 시그널/합의/action_plan 로직은 유지 |
| 설명 가능성 | universe/constraints 메타데이터를 JSON에 남겨 사후 분석 가능 |

---

## 비용 영향

| 마일스톤 | 추가 비용 |
|----------|----------|
| M1 (시장 옵션 정리) | $0 |
| M2 (넓은 universe 확보) | $0 (데이터 조회량 증가만 있음) |
| M3 (다양성 선택) | $0 |
| M4 (섹터 분류 보강) | $0 |
| M5 (출력/메타데이터) | $0 |
| **합계** | **$0** |

---

## 리스크

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 과도한 다양성 제약 | 점수 높은 종목이 탈락 | 단계적 완화 + 최종 점수 순 채우기 |
| 섹터 분류 오류 | 잘못된 섹터 cap 적용 | listing 우선 + 키워드 fallback + `기타` 허용 |
| 미국 시장 데이터 편차 | NASDAQ/NYSE 메타데이터 불균일 | 거래소 컬럼 우선, 없으면 기존 규칙 기반 폴백 |
| 실행 시간 증가 | 후보군 확대에 따라 응답 지연 | universe 크기 설정화 + `--top`과 별도 관리 |
| 사용자 혼동 | `top_n` 의미 변경 오해 | help/JSON에 `screened`와 `universe_size` 분리 표기 |

---

## 구현 순서

```text
M1 (시장 옵션 재정의)
→ M2 (넓은 universe 확보)
→ M3 (다양성 선택)
→ M4 (섹터 분류 보강)
→ M5 (파이프라인/출력 통합)
```

M1~M3는 순차 의존. M4는 M2 이후 병행 가능. M5는 M3 완료 후 통합.
