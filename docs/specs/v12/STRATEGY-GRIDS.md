# v12 Strategy Feature And Grid Contract
> **상태**: 📝 초안

상위 문서: [v12 Intraday Strategy Cohort](SPEC.md)

이 문서는 15개 전략의 deterministic feature, gate, score, 최대 4개 parameter set을 고정한다. 숫자 또는 공식이 바뀌면 새 v12 strategy version과 local run manifest가 필요하다.

## 1. 공통 계산

모든 계산은 [v10](../v10/SPEC.md)의 complete 5분봉과 cutoff 당시 point-in-time 조정계수만 사용한다.

| Symbol | Definition |
| --- | --- |
| `C_t`, `H_t`, `L_t`, `V_t` | 현재 complete 5분봉 close, high, low, volume |
| `TR_t` | `max(H_t-L_t, abs(H_t-C_(t-1)), abs(L_t-C_(t-1)))` |
| `ATR14_t` | 현재 봉까지의 `TR` 14개 단순평균, 현재 세션 전 부족분은 직전 정규장 complete 봉 사용 |
| `RVOL_N_t` | `V_t / median(V_(t-N) ... V_(t-1))`; 분모 0 또는 N개 부족이면 candidate 없음 |
| `VWAP_t` | 현재 정규장 첫 regular 봉부터 t까지 `sum(((H+L+C)/3)*V) / sum(V)` |
| `RET_L_t` | `C_t / C_(t-L) - 1` |
| `RS_L_t` | symbol `RET_L_t` minus 시장별 canonical benchmark `RET_L_t` |
| `CLV_t` | `(C_t-L_t)/(H_t-L_t)`; `H_t=L_t`이면 0.5 |
| `P60(x)` | 직전 60 공식 거래세션의 동일 minute-of-session에서 관측된 x에 대한 midrank percentile |
| `clip01(x)` | `min(1, max(0, x))` |

`P60`은 최소 20개 과거 관측값이 있어야 한다. `n>1`이면 `(midrank-1)/(n-1)`, `n=1`이면 1.0, 전체 동률이면 0.5다. 현재 세션 또는 미래 세션 값은 reference distribution에 넣지 않는다.

각 전략의 `deterministic_score`는 명시된 component percentile의 산술평균이다. 유한한 0~1 값만 허용한다. Gate가 false거나 필수 feature가 없으면 score 0을 반환하는 대신 candidate를 만들지 않는다.

Canonical benchmark는 KR 전체 universe에 `KR_BROAD_KS11`, US 전체 universe에 `US_BROAD_SPY`를 사용한다. KOSDAQ 종목도 KR cohort 비교 일관성을 위해 `KR_BROAD_KS11`을 사용한다. Benchmark adapter와 source artifact ID는 v10 manifest에 고정한다. 동일 cutoff complete benchmark 봉이 없으면 relative-strength candidate를 fail closed 한다.

각 strategy-symbol은 공식 세션당 최초 false-to-true gate에서 candidate를 최대 한 번 생성한다. 같은 gate가 유지되는 동안 5분마다 중복 candidate를 만들지 않는다.

## 2. Long Strategy 계약

### `long_orb_15m`

- Range: 공식 개장 뒤 첫 complete 5분봉 3개의 high·low.
- Window: 개장 15분 이후 60분 이내.
- Gate: `C_t > range_high + b*ATR14_t` 그리고 `RVOL_12_t >= r`.
- Score: mean of `P60((C_t-range_high)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `L15_A=(b=0.00,r=1.00)`, `L15_B=(0.00,1.50)`, `L15_C=(0.05,1.00)`, `L15_D=(0.05,1.50)`.

### `long_orb_30m`

- Range: 공식 개장 뒤 첫 complete 5분봉 6개.
- Window: 개장 30분 이후 90분 이내.
- Gate, score: `long_orb_15m`과 같고 30분 range를 사용한다.
- Grid: `L30_A=(b=0.00,r=1.00)`, `L30_B=(0.00,1.50)`, `L30_C=(0.05,1.00)`, `L30_D=(0.05,1.50)`.

### `long_gap_continuation`

- `gap=(official_open/previous_adjusted_close)-1`.
- Gate: `gap >= g`, 첫 w분 complete range가 끝난 뒤 `C_t`가 그 range high를 상향 돌파, `C_t > VWAP_t`.
- Score: mean of `P60(gap)`, `P60((C_t-range_high)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `LGC_A=(g=0.01,w=15)`, `LGC_B=(0.01,30)`, `LGC_C=(0.02,15)`, `LGC_D=(0.02,30)`.

### `long_session_high_breakout`

- Prior high: 현재 봉을 제외한 직전 n개 complete 5분봉 high의 최대값이며 같은 세션 봉만 사용한다.
- Gate: `C_t > prior_high + b*ATR14_t`.
- Score: mean of `P60((C_t-prior_high)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `LSH_A=(n=6,b=0.00)`, `LSH_B=(6,0.05)`, `LSH_C=(12,0.00)`, `LSH_D=(12,0.05)`.

### `long_vwap_reclaim`

- Gate: 직전 k개 complete 봉 close가 모두 당시 VWAP 이하이고 `C_t > VWAP_t + b*ATR14_t`, `C_(t-1) <= VWAP_(t-1)`.
- Score: mean of `P60((C_t-VWAP_t)/ATR14_t)`, `P60(RVOL_12_t)`, `P60(CLV_t)`.
- Grid: `LVR_A=(k=1,b=0.00)`, `LVR_B=(1,0.05)`, `LVR_C=(2,0.00)`, `LVR_D=(2,0.05)`.

### `long_ma_trend`

- `SMA_n`은 현재 봉을 포함한 close n개의 단순평균이다.
- Gate: `SMA_fast > SMA_slow`, `C_t > SMA_fast`, 두 평균 모두 직전 봉보다 상승.
- Score: mean of `P60((SMA_fast-SMA_slow)/ATR14_t)`, `P60((C_t-SMA_fast)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `LMA_A=(fast=3,slow=9)`, `LMA_B=(6,18)`, `LMA_C=(9,27)`, `LMA_D=(12,36)`.

### `long_relative_strength`

- Benchmark는 공통 계산에 고정된 `KR_BROAD_KS11` 또는 `US_BROAD_SPY`의 동시 complete 5분봉이다.
- Gate: `RS_L_t > 0`이고 `P60(RS_L_t) >= 0.70`, `C_t > VWAP_t`.
- Score: mean of `P60(RS_L_t)`, `P60(RET_L_t)`, `P60(RVOL_12_t)`.
- Grid: `LRS_A=(L=6)`, `LRS_B=(12)`, `LRS_C=(24)`, `LRS_D=(36)`.

### `long_volume_breakout`

- Prior high는 현재 봉 제외 직전 n개 complete 봉 high 최대값이다.
- Gate: `C_t > prior_high`, `RVOL_12_t >= r`.
- Score: mean of `P60((C_t-prior_high)/ATR14_t)`, `P60(RVOL_12_t)`, `P60(CLV_t)`.
- Grid: `LVB_A=(n=6,r=1.5)`, `LVB_B=(6,2.0)`, `LVB_C=(12,1.5)`, `LVB_D=(12,2.0)`.

### `long_volatility_expansion`

- Gate: `TR_t/ATR14_(t-1) >= e`, `CLV_t >= q`, `C_t > C_(t-1)`.
- Score: mean of `P60(TR_t/ATR14_(t-1))`, `P60(CLV_t)`, `P60(RVOL_12_t)`.
- Grid: `LVE_A=(e=1.25,q=0.70)`, `LVE_B=(1.25,0.80)`, `LVE_C=(1.50,0.70)`, `LVE_D=(1.50,0.80)`.

### `long_range_compression`

- `compression_n=(max(H_(t-n)..H_(t-1))-min(L_(t-n)..L_(t-1)))/ATR14_(t-1)`.
- Gate: `compression_n <= c` 그리고 `C_t`가 compression range high를 상향 돌파.
- Score: mean of `P60(-compression_n)`, `P60((C_t-range_high)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `LRC_A=(n=3,c=0.75)`, `LRC_B=(3,0.50)`, `LRC_C=(6,0.75)`, `LRC_D=(6,0.50)`.

## 3. Short Strategy 계약

모든 Short candidate는 feature gate 전에 [v11](../v11/SPEC.md)의 borrow·locate·규제 eligibility를 통과해야 한다.

### `short_orb_15m`

- Range와 window는 `long_orb_15m`과 같다.
- Gate: `C_t < range_low - b*ATR14_t` 그리고 `RVOL_12_t >= r`.
- Score: mean of `P60((range_low-C_t)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `S15_A=(b=0.00,r=1.00)`, `S15_B=(0.00,1.50)`, `S15_C=(0.05,1.00)`, `S15_D=(0.05,1.50)`.

### `short_gap_continuation`

- `gap=(official_open/previous_adjusted_close)-1`.
- Gate: `gap <= -g`, 첫 w분 range가 끝난 뒤 `C_t`가 range low를 하향 돌파, `C_t < VWAP_t`.
- Score: mean of `P60(-gap)`, `P60((range_low-C_t)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `SGC_A=(g=0.01,w=15)`, `SGC_B=(0.01,30)`, `SGC_C=(0.02,15)`, `SGC_D=(0.02,30)`.

### `short_session_low_breakdown`

- Prior low: 현재 봉 제외, 같은 공식 세션에 속한 직전 n개 complete 5분봉 low 최소값. 같은 세션 봉이 n개보다 적으면 candidate 없음.
- Gate: `C_t < prior_low - b*ATR14_t`.
- Score: mean of `P60((prior_low-C_t)/ATR14_t)`, `P60(RVOL_12_t)`.
- Grid: `SSL_A=(n=6,b=0.00)`, `SSL_B=(6,0.05)`, `SSL_C=(12,0.00)`, `SSL_D=(12,0.05)`.

### `short_vwap_rejection`

- Gate: 직전 k개 complete 봉에서 하나 이상 `high >= VWAP`, 직전 close는 VWAP 이상, 현재 `C_t < VWAP_t - b*ATR14_t`.
- Score: mean of `P60((VWAP_t-C_t)/ATR14_t)`, `P60(RVOL_12_t)`, `P60(1-CLV_t)`.
- Grid: `SVR_A=(k=1,b=0.00)`, `SVR_B=(1,0.05)`, `SVR_C=(2,0.00)`, `SVR_D=(2,0.05)`.

### `short_volume_breakdown`

- Prior low는 현재 봉 제외 직전 n개 complete 봉 low 최소값이다.
- Gate: `C_t < prior_low`, `RVOL_12_t >= r`.
- Score: mean of `P60((prior_low-C_t)/ATR14_t)`, `P60(RVOL_12_t)`, `P60(1-CLV_t)`.
- Grid: `SVB_A=(n=6,r=1.5)`, `SVB_B=(6,2.0)`, `SVB_C=(12,1.5)`, `SVB_D=(12,2.0)`.

## 4. 공통 실행과 청산

- Candidate는 v10의 10초 watermark 이후에만 확정한다.
- 신규 진입 intent는 v11의 결정 완료 후 최초 1분 경계를 목표로 한다.
- 모든 전략은 정규장 종료 20분 전 신규 candidate 생성을 중단한다.
- 종료 5분 전에 청산 intent를 만들고 그 뒤 최초 거래 가능한 1분 경계에서 청산한다.
- Stop-loss, profit target, pyramiding은 이 grid에 없다.
- Risk kill, short recall, 거래정지는 장마감 청산보다 우선한다.

## 5. Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `current_in_reference` | 현재 값을 P60 reference에 포함 | lookahead failure |
| `score_out_of_range` | score가 0~1 밖 | score failure |
| `fifth_grid` | strategy에 다섯 번째 set 추가 | grid failure |
| `duplicate_session_signal` | gate 유지 중 같은 strategy-symbol 재발행 | candidate duplication failure |
| `short_without_borrow` | eligibility 전에 short feature 평가·발행 | short boundary failure |
| `future_benchmark` | 미완결 benchmark 봉으로 RS 계산 | point-in-time failure |

## 6. Acceptance Criteria

- 15개 strategy ID 각각에 gate, score, 정확히 4개 이하 parameter set이 있다.
- 모든 feature가 complete point-in-time 봉과 과거 reference distribution만 사용한다.
- Deterministic score가 유한한 0~1이고 missing feature를 0점 후보로 위장하지 않는다.
- 각 strategy-symbol-session은 최초 false-to-true candidate를 최대 한 번 생성한다.
- Short는 feature보다 borrow·regulation gate를 먼저 통과한다.
- 상위 SPEC의 최초 1분 진입과 장마감 청산 경계를 따른다.
