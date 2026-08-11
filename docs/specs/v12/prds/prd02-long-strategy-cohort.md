# PRD: v12 PRD 02 Long Strategy Cohort
> **상태**: 📝 초안
> 상위 SPEC: [v12 SPEC](../SPEC.md)

## 의존성

- v12 PRD 01 common runtime
- [v12 Strategy Grids](../STRATEGY-GRIDS.md)의 Long 계약

## 목표

Long 10개 전략과 40개 parameter set을 정확한 gate·score로 구현하고 독립 shadow candidate를 생성한다.

## 전략 Inventory

| ID | Grid prefix |
| --- | --- |
| `long_orb_15m` | `L15_A`~`L15_D` |
| `long_orb_30m` | `L30_A`~`L30_D` |
| `long_gap_continuation` | `LGC_A`~`LGC_D` |
| `long_session_high_breakout` | `LSH_A`~`LSH_D` |
| `long_vwap_reclaim` | `LVR_A`~`LVR_D` |
| `long_ma_trend` | `LMA_A`~`LMA_D` |
| `long_relative_strength` | `LRS_A`~`LRS_D` |
| `long_volume_breakout` | `LVB_A`~`LVB_D` |
| `long_volatility_expansion` | `LVE_A`~`LVE_D` |
| `long_range_compression` | `LRC_A`~`LRC_D` |

## 구현 표면

- `src/v12/strategies/long.py`: 10 evaluator
- `src/v12/strategies/orb.py`: 15m·30m opening range
- `src/v12/strategies/trend.py`: Gap, high, MA, RS
- `src/v12/strategies/volume_volatility.py`: Volume, expansion, compression
- `docs/specs/v12/fixtures/prd02-*.json`: 각 전략 happy/no-signal/missing

## 특별 ORB 계약

- 첫 15분 complete 3개 봉 range
- 개장 15~60분 첫 close breakout
- Wick-only·60분 이후 breakout 거부
- Stop·target 없음, close-5 exit intent

## CLI

```bash
uv run python -m src.v12.cli prd02-acceptance
uv run python -m src.v12.cli prd02-replay --strategy <id> --parameter-set <id>
```

## 완료 조건

- Long 10/10, parameter set 40/40이 실행된다.
- 각 전략 happy, no-signal, missing-feature fixture가 존재한다.
- 공식을 임의 단순화하거나 fifth grid를 추가하지 않는다.
