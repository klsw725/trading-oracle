# PRD: v14 PRD 02 Metrics, Bootstrap, Cost Stress
> **상태**: 📝 초안
> 상위 SPEC: [v14 SPEC](../SPEC.md)

## 의존성

- v14 PRD 01 frozen cohort·selection·experiment plan manifest
- v11 baseline·2× variable execution-cost contract

## 목표

비거래 기준선 대비 일별 순비용 초과수익, 5일 block bootstrap CI, sample sufficiency, baseline·2× cost 결과를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v14/series.py` | Calendar-aligned daily excess return |
| `src/v14/cost_stress.py` | Baseline과 variable cost 2× replay |
| `src/v14/bootstrap.py` | 5일 block, 10,000 resample, fixed seed |
| `src/v14/samples.py` | 독립 신호일·완료 거래 count |
| `src/v14/metrics.py` | Primary와 secondary metrics |

## Sample 계약

- Validation: 독립 신호일 60, OOS 완료 거래 150
- Holdout: 독립 신호일 100, OOS 완료 거래 300
- 신호일은 `pre_portfolio_candidate`가 하나 이상인 공식 거래일
- No-trade day를 일별 series에서 삭제하지 않음

Bootstrap은 PRD 01 plan manifest의 seed·block·resample 값을 읽기만 하며 자체 default를 만들거나 변경하지 않는다.

## CLI

```bash
uv run python -m src.v14.cli prd02-build --input <run>
uv run python -m src.v14.cli prd02-acceptance
```

## Acceptance와 Mutation

- Fixed seed의 byte-identical CI
- Baseline·stress 비용 계층 구분
- Fixed tax·commission을 2배하지 않음
- `sample_or`, missing day deletion, future revision 차단
- Secondary metric이 primary series를 수정하지 않음

## 완료 조건

- 시장·segment별 primary series, CI, sample report를 생성한다.
- 표본 부족을 pass나 reject로 위장하지 않는다.
