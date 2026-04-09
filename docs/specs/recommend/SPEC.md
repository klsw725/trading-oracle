# Trading Oracle Recommendation Pipeline — Feature Specification

> 기존 추천 파이프라인 기준: [../multi-perspective/prds/phase8-recommend.md](../multi-perspective/prds/phase8-recommend.md)
> Recommendation Pipeline 스펙은 기존 1-step 추천 파이프라인 위에 **시장 semantics 정리**, **넓은 후보군 확보**, **다양성 선택**을 추가한다.

## PRD 연결

| Phase | PRD | 상태 | 설명 |
|-------|-----|------|------|
| Phase 20 | [prds/phase20-diversified-recommend.md](prds/phase20-diversified-recommend.md) | 📝 초안 | 추천 후보군 확장 + 다양성 선택 |
| Phase 21 | [prds/phase21-sizing-visibility.md](prds/phase21-sizing-visibility.md) | 📝 초안 | 추천 포지션 사이징 가시성 |

---

## 개요

### 기존 추천 → Recommendation Pipeline 핵심 변화

| 영역 | 기존 추천(Phase 8) | Recommendation Pipeline |
|---|---|---|
| 시장 옵션 | `ALL`, `KOSPI`, `KOSDAQ`, `US`, `NASDAQ`, `NYSE` | **`KR`, `US`, `ALL` 의미 대칭화** + 단일 시장 옵션 유지 |
| 후보군 확보 | 시총 상위 일부를 바로 잘라 사용 | **시장별 넓은 universe 확보 후 압축** |
| `top_n` 의미 | 초기 후보 수에 가까움 | **최종 분석 대상 수** |
| 다양성 | 점수 정렬 중심 | **점수 + 시장/섹터 다양성 선택** |
| 설명 가능성 | 왜 빠졌는지 추적 어려움 | **universe/selection 메타데이터 제공** |

### Recommendation Pipeline 설계 원칙

1. **시장 의미 명확화**: `KR = KOSPI + KOSDAQ`, `US = NASDAQ + NYSE`, `ALL = KR + US`.
2. **넓게 보고 좁게 고르기**: 시총 상위 소수만 즉시 자르지 않고, 먼저 넓은 모집단을 확보한다.
3. **다양성은 우선 규칙**: 시장/섹터 분산은 강제 빈 리스트를 만들지 않고, 후보 부족 시 순차 완화한다.
4. **기존 파이프라인 비파괴**: 시그널 필터, 다관점 분석, BUY 합의, action_plan 계산은 유지한다.
5. **설명 가능성 유지**: 사용자에게 “왜 이 후보가 선택되었는지”를 규칙으로 설명할 수 있어야 한다.

---

## 1. 사용자 시나리오

### 1-1. 한국 시장 전체 추천

사용자는 `uv run scripts/recommend.py` 또는 `--market KR`로 한국 전체 추천을 요청한다.

**기존**: 시총 상위 일부만 시작점이 되어 코스피 대형주 위주로 수렴하기 쉽다.
**Recommendation Pipeline**: KOSPI/KOSDAQ 각각 넓은 후보군을 확보한 뒤, 점수와 다양성 규칙으로 최종 분석 대상을 고른다.

```text
🎯 종목 추천 (KR)
  universe: KOSPI 50 + KOSDAQ 50
  최종 분석 대상: 6개
  선택 기준: score 우선 + 섹터 중복 완화 + 시장 편중 완화
```

### 1-2. 미국 시장 전체 추천

사용자는 `--market US`로 미국 전체 추천을 요청한다.

**동작**:
- NASDAQ universe 확보
- NYSE universe 확보
- 점수 계산 후 diversified selection
- 이후 기존 시그널 필터/다관점 분석 실행

### 1-3. 전체 시장 추천

사용자는 `--market ALL`로 한국+미국 전체 추천을 요청한다.

**핵심 의미**:
- `ALL`은 더 이상 한국 전체와 동의어가 아니다.
- `ALL = KR + US`

### 1-4. 특정 시장 집중 탐색

사용자는 `--market KOSDAQ`, `--market NASDAQ`처럼 단일 시장만 선택할 수 있다.

이 경우에도 내부적으로는:
- 넓은 universe 확보
- 점수 계산
- 섹터 다양성 선택
을 거친 뒤 최종 `top_n` 분석 대상으로 압축한다.

---

## 2. 시장 semantics

### 지원 시장 정의

- `KOSPI`
- `KOSDAQ`
- `KR` = `KOSPI + KOSDAQ`
- `NASDAQ`
- `NYSE`
- `US` = `NASDAQ + NYSE`
- `ALL` = `KR + US`

### 기본값

- CLI 기본 `--market` 값은 `KR`

### 의미 규칙

- `KR`은 한국 전체 시장이다.
- `US`는 미국 전체 시장이다.
- `ALL`은 한국+미국 전체 시장이다.
- 단일 시장 옵션(`KOSPI`, `KOSDAQ`, `NASDAQ`, `NYSE`)은 상세 제어용이다.

---

## 3. 추천 파이프라인

```text
시장 선택
→ 시장별 넓은 universe 확보
→ 기존 score 계산
→ diversified selection으로 top_n 압축
→ 시그널 필터(Bull 4/6+)
→ 다관점 분석
→ BUY 합의 종목 반환
```

### 단계별 의미

1. **universe 확보**
   - 시장별 시총 상위 50~100개 수준의 넓은 후보군 확보
2. **score 계산**
   - 기존 `leading.py` 점수식 최대한 유지
3. **diversified selection**
   - 점수 우선 정렬
   - 섹터/시장 편중 완화
   - 부족하면 점진적 완화
4. **기존 파이프라인 연결**
   - 시그널 필터
   - 다관점 분석
   - BUY 합의 필터

---

## 4. 다양성 선택 규칙

### 기본 규칙

- 동일 섹터 중복 최소화
- 복합 시장(`KR`, `US`, `ALL`)에서는 하위 시장 완전 독식 완화
- 최종 선정은 greedy selection 기반

### 완화 순서

1. 섹터 중복 최소화 + 시장 균형 유지
2. 시장 균형 완화
3. 섹터 cap 완화
4. 남은 슬롯은 점수 순으로 채움

### 설계 의도

- 다양성은 **추천 품질 개선 장치**이지, 후보를 억지로 비우는 장치가 아니다.
- 후보가 적은 날에도 추천 파이프라인은 계속 동작해야 한다.

---

## 5. 섹터 정보 원천

다양성 선택에 필요한 섹터 정보는 다음 우선순위를 따른다.

1. 거래소 listing의 sector/industry 컬럼
2. 내부 섹터 매핑 규칙
3. 종목명 키워드 fallback
4. 없으면 `기타`

### 이유

- 한국 종목은 이름 기반 fallback만으로도 어느 정도 동작 가능
- 미국 종목은 listing 메타데이터를 우선 활용해야 정확도가 높다.

---

## 6. 출력/설명 가능성

Recommendation Pipeline 스펙은 추천 결과에 다음 메타데이터를 포함할 수 있어야 한다.

```json
{
  "market": "KR",
  "universe_size": 100,
  "universe_breakdown": {"KOSPI": 50, "KOSDAQ": 50},
  "screened": 6,
  "portfolio_sizing": {
    "cash": 8000000,
    "cash_ratio": 65.0,
    "cash_floor": 25,
    "cash_floor_amount": 3075000,
    "available_cash": 4925000
  },
  "selection_constraints": {
    "sector_cap": 1,
    "prefer_market_balance": true,
    "relaxed": false
  }
}
```

### 목적

- 사용자가 왜 해당 후보만 분석됐는지 이해할 수 있게 함
- 사용자가 왜 `매수 가능 금액`과 `목표 수량`이 그렇게 계산됐는지 이해할 수 있게 함
- 추후 추천 품질/편향을 사후 분석할 수 있게 함

---

## 7. 기존 기능과의 관계

Recommendation Pipeline은 기존 추천 파이프라인을 대체하는 재설계안이지만, 아래 로직은 유지한다.

- Bull 4/6+ 시그널 필터
- 5관점 다관점 분석
- BUY 합의 종목만 추천
- 포트폴리오 상태 기반 `action_plan` 계산

즉, Recommendation Pipeline의 핵심 변화는 **“무엇을 분석 대상으로 올릴지”**에 있다.

---

## 8. 리스크

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 다양성 규칙이 과도함 | 점수 높은 후보 탈락 | 단계적 완화 + 최종 점수 순 채우기 |
| 섹터 분류 부정확 | 잘못된 중복 제한 | listing 우선 + fallback 허용 |
| 미국장 메타데이터 편차 | NASDAQ/NYSE 품질 차이 | 거래소별 컬럼 점검 + `기타` 폴백 |
| universe 확대에 따른 지연 | 추천 응답 시간 증가 | 시장별 universe size 설정화 |

---

## 9. 성공 기준

- `KR`, `US`, `ALL` semantics가 코드/CLI/출력에서 일관된다.
- `KR` 추천 시 코스닥 종목이 구조적으로 배제되지 않는다.
- 추천 후보가 특정 섹터로만 몰리는 빈도가 줄어든다.
- `top_n`이 “초기 후보 수”가 아니라 “최종 분석 대상 수”로 일관되게 동작한다.
- 사용자에게 후보 선택 이유를 메타데이터로 설명할 수 있다.

---

## 10. 구현 진입점

구체 구현 계획은 PRD를 따른다.

- [Phase 20 PRD](prds/phase20-diversified-recommend.md)

이 SPEC은 추천 파이프라인 재설계의 상위 개념 문서이며, 실제 작업 분해/파일 변경/검증 기준은 PRD에서 관리한다.
