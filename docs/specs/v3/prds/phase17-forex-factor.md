# PRD: Phase 17 — 환율 팩터 시스템 (다통화 + 레짐 + 포지션 반영)

> **SPEC 참조**: [SPEC.md](../SPEC.md) (Phase 17 섹션 추가 필요)
> **상태**: ✅ 완료
> **우선순위**: P2
> **선행 조건**: Phase 11 매크로 시계열 (완료), Phase 6 시장 레짐 감지 (완료)

---

## 문제

현재 환율 데이터(`USD/KRW`, `DXY`)는 매크로 관점 프롬프트에 수치로 주입될 뿐, **구조화된 팩터로 활용되지 않는다.**

1. **종목별 환율 민감도 미분류** — 수출주(삼성전자)와 내수주(BGF리테일)가 환율 변동에 동일하게 취급됨
2. **환율 시그널 부재** — 환율 급변(±2% 이상)이 발생해도 시그널 레벨에서 반영되지 않음
3. **포지션 사이징 미반영** — 환율 급등 시 수출주 비중 확대 / 수입주 비중 축소 로직 없음
4. **다통화 부재** — JPY/KRW(일본 경쟁사 환율), CNY/KRW(중국 수출입)가 수집되지 않음
5. **환율 레짐 미감지** — 원화 강세/약세/안정 구간을 구분하지 않음

## 솔루션

환율을 독립적인 **팩터 시스템**으로 구축하여 시그널 → 관점 → 포지션 사이징까지 수직 통합.

---

## 마일스톤

### M1: 다통화 환율 수집 확장

**목표**: 기존 `USD/KRW`, `DXY`에 `JPY/KRW`, `CNY/KRW`, `EUR/KRW` 추가.

**변경 파일**: `src/data/macro.py`

- [ ] `MACRO_SYMBOLS`에 추가:
  - `JPY_KRW`: `JPY/KRW` — 일본 경쟁사 환율 (자동차, 전자)
  - `CNY_KRW`: `CNY/KRW` — 중국 수출입 환율 (화학, 철강)
  - `EUR_KRW`: `EUR/KRW` — 유럽 수출 환율 (자동차, 조선)
- [ ] `format_macro_for_prompt()`에 신규 통화 라벨/단위 추가
- [ ] FDR에서 `JPY/KRW`, `CNY/KRW`, `EUR/KRW` 수집 가능 여부 확인 → 불가 시 `USD/KRW × KRW/JPY` 크로스레이트 계산
- [ ] 파생 지표: 각 통화별 5일/20일 변화율, 1일 차분 (기존 `_add_derived` 로직 자동 적용)

**검증 기준**: `uv run main.py macro` 실행 시 6개 통화(USD, DXY, JPY, CNY, EUR + 기존) 데이터 출력

---

### M2: 종목별 환율 민감도(베타) 계산

**목표**: 각 종목의 주가와 환율 간 상관계수/베타를 계산하여 수출주/내수주/중립을 분류.

**신규 파일**: `src/signals/forex.py`

- [ ] `compute_fx_beta(ticker_ohlcv, fx_series, window=60)` → `float`
  - 종목 일간 수익률과 USD/KRW 일간 수익률의 60일 롤링 베타
  - 양수 베타 = 원화 약세 시 주가 상승 (수출주)
  - 음수 베타 = 원화 약세 시 주가 하락 (내수주/수입주)
- [ ] `classify_fx_sensitivity(beta)` → `"export" | "import" | "neutral"`
  - β > 0.3: export (수출주)
  - β < -0.3: import (수입주/내수주)
  - 그 외: neutral
- [ ] 다통화 베타: 자동차 → JPY/KRW 베타도 계산, 화학 → CNY/KRW 베타도 계산
  - 섹터-통화 매핑 테이블 (`SECTOR_FX_MAP`)로 관리
- [ ] 베타 캐시: `data/fx_beta_cache.json`에 일별 캐시 (당일 계산분)

**검증 기준**: 삼성전자 β > 0, 내수주(예: BGF리테일) β ≈ 0 또는 음수

---

### M3: 환율 시그널 모듈

**목표**: 환율 변동을 독립 시그널로 생성하여 기존 6-시그널 앙상블과 병렬 제공.

**신규 파일**: `src/signals/forex.py` (M2에 추가)

- [ ] `compute_fx_signal(fx_series, ticker_beta, regime)` → `dict`
  - **FX Momentum**: USD/KRW 5일/20일 변화율 방향
  - **FX Volatility**: USD/KRW 20일 변동성 (고변동 = 리스크 확대)
  - **FX Regime Alignment**: 현재 환율 레짐(M5)과 종목 민감도의 정합성
    - 원화 약세 + 수출주 → BULLISH boost
    - 원화 약세 + 내수주 → BEARISH boost
    - 원화 강세 + 수출주 → BEARISH boost
    - 원화 강세 + 내수주 → BULLISH boost
  - **Cross-currency Signal**: 섹터별 관련 통화 시그널
    - 자동차: JPY 약세 → 한국 자동차 경쟁력 약화 → BEARISH
    - 화학/철강: CNY 약세 → 중국 덤핑 리스크 → BEARISH
- [ ] 반환 형식:
  ```python
  {
      "fx_verdict": "BULLISH" | "BEARISH" | "NEUTRAL",
      "fx_confidence": 0.0~1.0,
      "fx_beta": 0.45,
      "fx_class": "export",
      "components": {
          "momentum": {"usd_krw_5d": +1.2, "direction": "weakening"},
          "volatility": {"usd_krw_20d_vol": 0.8, "level": "normal"},
          "regime_alignment": {"aligned": True, "boost": "BULLISH"},
          "cross_currency": {"jpy_signal": "NEUTRAL", "cny_signal": "NEUTRAL"},
      },
  }
  ```

**통합**: `src/common.py`의 파이프라인에서 `compute_signals()` 호출 직후 `compute_fx_signal()` 호출, 결과를 `PerspectiveInput`에 추가

**검증 기준**: 원화 약세 기간(USD/KRW 상승) 데이터로 수출주에 BULLISH 시그널 생성 확인

---

### M4: 관점 프롬프트 환율 팩터 주입

**목표**: 각 관점의 LLM 프롬프트에 종목별 환율 팩터를 구조화하여 주입.

**변경 파일**: `src/perspectives/macro.py`, `src/perspectives/kwangsoo.py`, `src/perspectives/quant_perspective.py`

- [ ] `PerspectiveInput`에 `fx_signal: dict | None` 필드 추가 (`src/perspectives/base.py`)
- [ ] 매크로 관점: 기존 환율 수치 + **환율 베타/분류/시그널** 추가 삽입
  ```
  ### 환율 팩터
  - 종목 환율 민감도: 수출주 (β=0.45)
  - USD/KRW: 1,380원 (5일 +1.2%, 약세 추세)
  - 환율-종목 정합성: BULLISH (원화 약세 + 수출주)
  - JPY/KRW: 안정 (경쟁사 환율 중립)
  ```
- [ ] 이광수/퀀트 관점: 환율 팩터를 보조 컨텍스트로 주입 (기존 프롬프트 구조 변경 최소화)

**검증 기준**: LLM 응답의 `reasoning`에 환율 관련 근거가 포함되는지 확인

---

### M5: 환율 레짐 감지

**목표**: 원화 강세/약세/안정 레짐을 감지하여 Phase 6 시장 레짐과 병렬 운용.

**신규 파일**: `src/signals/forex.py` (M2에 추가)

- [ ] `detect_fx_regime(fx_series, window=60)` → `dict`
  - **판정 로직**:
    - 20일 이동평균 vs 60일 이동평균 크로스
    - 20일 변화율 ±3% 이상 = 강세/약세
    - 볼린저 밴드 위치 (상단 근접 = 약세 극단, 하단 근접 = 강세 극단)
  - **레짐 분류**:
    - `krw_strong`: 원화 강세 (USD/KRW 하락 추세)
    - `krw_weak`: 원화 약세 (USD/KRW 상승 추세)
    - `krw_stable`: 횡보
    - `krw_extreme_weak`: 원화 급락 (20일 +5% 이상) → 리스크 경보
    - `krw_extreme_strong`: 원화 급등 (20일 -5% 이상)
  - **반환**:
    ```python
    {
        "fx_regime": "krw_weak",
        "fx_regime_description": "원화 약세 구간 (USD/KRW 20MA > 60MA)",
        "usd_krw_ma20": 1385.2,
        "usd_krw_ma60": 1362.8,
        "usd_krw_bb_position": 0.78,
        "change_20d_pct": +2.1,
        "is_extreme": False,
    }
    ```
- [ ] 다통화 레짐: JPY/KRW, CNY/KRW에도 동일 로직 적용 (간소화)

**통합**: `src/common.py`에서 시장 레짐(`detect_regime`) 호출 시 `detect_fx_regime`도 병렬 호출, `market_context`에 `fx_regime` 추가

**검증 기준**: 2024년 4월 원화 급락 기간 데이터로 `krw_extreme_weak` 감지 확인

---

### M6: 포지션 사이징 환율 반영

**목표**: 환율 팩터를 포지션 사이징에 반영하여 환율 리스크를 자동 조절.

**변경 파일**: `src/portfolio/sizer.py`

- [ ] `compute_buy_plan()`에 환율 조정 로직 추가:
  - **원화 약세 + 수출주**: 목표 수량 × 1.15 (최대 15% 확대)
  - **원화 약세 + 내수주**: 목표 수량 × 0.85 (최대 15% 축소)
  - **원화 급락(extreme)**: 전체 신규 매수 축소 (목표 수량 × 0.7) — 변동성 리스크
  - **원화 강세 + 내수주**: 목표 수량 × 1.10 (소폭 확대)
  - **원화 강세 + 수출주**: 목표 수량 × 0.90 (소폭 축소)
  - **안정**: 조정 없음 (× 1.0)
- [ ] `compute_sell_plan()`에 환율 기반 긴급 감축:
  - **원화 급락 + 내수주 보유**: 매도 비율 상향 (+20%p)
  - **원화 급등 + 수출주 보유**: 매도 비율 상향 (+10%p)
- [ ] `check_portfolio_health()`에 환율 리스크 지표 추가:
  - 포트폴리오 내 수출주/내수주 비중
  - 현재 환율 레짐 대비 포트폴리오 정합성 점수
- [ ] 조정 계수는 `config.yaml`의 `position_sizing.fx_adjustment`로 오버라이드 가능

**검증 기준**: 동일 종목 BUY 시그널에서 원화 약세/강세 시 산출 수량이 달라지는지 확인

---

### M7: 인과 그래프 환율 체인 강화

**목표**: 인과 그래프에 환율 전용 인과 체인을 보강.

**변경 파일**: `src/causal/builder.py`

- [ ] `ROOT_TOPICS`에 환율 전용 토픽 추가:
  ```python
  {"topic": "원달러 환율과 수출 경쟁력", "domain": "환율"},
  {"topic": "엔화 환율과 한일 경쟁", "domain": "환율"},
  {"topic": "위안화 환율과 중국 수출입", "domain": "환율"},
  {"topic": "달러 인덱스와 신흥국 자본흐름", "domain": "환율"},
  ```
- [ ] `src/perspectives/macro.py`의 키워드 매핑에 환율 키워드 추가:
  - 전체 종목: `["환율", "원달러"]` 기본 포함
  - 수출주: `["수출 경쟁력", "원화 약세 수혜"]`
  - 수입주: `["원자재 수입", "환율 비용"]`

**검증 기준**: 인과 그래프 빌드 후 "환율" 도메인 트리플이 10개 이상 생성

---

## 데이터 흐름

```
[M1] macro.py           ──→ 다통화 시계열 (USD/JPY/CNY/EUR/KRW)
                              │
[M5] forex.py           ──→ 환율 레짐 감지 (krw_weak/strong/stable/extreme)
                              │
[M2] forex.py           ──→ 종목별 환율 베타 + 수출/내수 분류
                              │
[M3] forex.py           ──→ 종목별 환율 시그널 (BULLISH/BEARISH/NEUTRAL)
                              │
[M4] perspectives/*.py  ──→ LLM 프롬프트에 환율 팩터 주입
                              │
[M6] sizer.py           ──→ 포지션 사이징 환율 조정 (±15%)
                              │
[M7] builder.py         ──→ 인과 그래프 환율 체인 보강
```

---

## 안전장치

| 장치 | 설명 |
|------|------|
| 베타 최소 데이터 | 60일 미만 OHLCV → 베타 계산 불가, neutral 분류 |
| 환율 레짐 폴백 | FX 데이터 수집 실패 → 레짐 없음, 조정 계수 1.0 |
| 사이징 상한 | 환율 조정 계수 최대 ±15% (극단 시 ±30%) |
| 크로스레이트 정합성 | JPY/KRW 직접 수집 불가 시 USD/KRW ÷ USD/JPY로 계산, 오차 경고 |
| 비파괴 원칙 | 환율 팩터 없어도 기존 파이프라인 100% 동작 (모든 환율 로직은 None 체크 후 스킵) |

---

## config.yaml 추가 섹션

```yaml
forex:
  # 다통화 수집
  currencies: ["USD/KRW", "JPY/KRW", "CNY/KRW", "EUR/KRW"]
  
  # 베타 계산
  beta_window: 60          # 롤링 베타 윈도우 (일)
  beta_export_threshold: 0.3
  beta_import_threshold: -0.3
  
  # 환율 레짐
  regime_ma_short: 20
  regime_ma_long: 60
  regime_extreme_threshold: 5.0  # 20일 변화율 % 기준
  
  # 포지션 사이징 조정
  sizing_adjustment:
    weak_export: 1.15      # 원화 약세 + 수출주
    weak_import: 0.85      # 원화 약세 + 내수주
    strong_export: 0.90    # 원화 강세 + 수출주
    strong_import: 1.10    # 원화 강세 + 내수주
    extreme_cap: 0.70      # 환율 급변 시 전체 축소
    
  # 섹터-통화 매핑
  sector_fx_map:
    반도체: ["USD/KRW"]
    자동차: ["USD/KRW", "JPY/KRW"]
    화학: ["USD/KRW", "CNY/KRW"]
    철강: ["CNY/KRW"]
    조선: ["USD/KRW", "EUR/KRW"]
    에너지: ["USD/KRW"]
    금융: ["USD/KRW"]
```

---

## 비용 영향

| 마일스톤 | 추가 비용 |
|----------|----------|
| M1 (다통화 수집) | $0 (FDR 무료) |
| M2 (베타 계산) | $0 (통계 계산) |
| M3 (환율 시그널) | $0 (규칙 기반) |
| M4 (프롬프트 주입) | ~$0 (기존 프롬프트 길이 미세 증가) |
| M5 (환율 레짐) | $0 (통계 계산) |
| M6 (사이징 반영) | $0 (규칙 기반) |
| M7 (인과 그래프) | ~$0.50 (1회성 빌드) |
| **합계** | **~$0.50** |

---

## 리스크

| 리스크 | 영향 | 완화 |
|--------|------|------|
| FDR 크로스레이트 미지원 | JPY/KRW 등 직접 수집 불가 | USD 기준 크로스레이트 계산 폴백 |
| 환율 베타 과적합 | 단기 상관이 장기 인과로 오해 | 60일 윈도우 + Granger 검증(Phase 12) 연계 |
| 사이징 과조정 | 환율 팩터가 포지션을 과도하게 왜곡 | ±15% 상한 + config 오버라이드 |
| 섹터 분류 오류 | 종목의 실제 수출비중과 베타 기반 분류 불일치 | 베타 기반 자동분류 + 수동 오버라이드(`config.yaml`) |
| 환율 레짐 노이즈 | 환율 횡보 구간에서 레짐 빈번 전환 | 히스테리시스: 레짐 전환 후 최소 5일 유지 |

---

## 구현 순서

```
M1 (다통화 수집) → M5 (환율 레짐) → M2 (베타 계산) → M3 (환율 시그널) → M4 (프롬프트) → M6 (사이징) → M7 (인과)
```

M1~M3는 순차 의존. M4/M6/M7은 M3 완료 후 병렬 가능.
