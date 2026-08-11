# PRD: v14 PRD 01 Cohort And Development Selection
> **상태**: 📝 초안
> 상위 SPEC: [v14 SPEC](../SPEC.md)

## 의존성

- v10 data·context manifests
- v11 execution ledger
- v12 strategy runs
- v13 router runs

## 목표

KR·US 연속 24개월 cohort를 12/6/6으로 동결하고 development anchored walk-forward에서 전략·router policy를 선택한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v14/cohort.py` | Market별 24개월 continuity와 12/6/6 split |
| `src/v14/folds.py` | 4→2, 6→2, 8→2, 10→2 fold |
| `src/v14/selection.py` | Strategy 4개·router 6개 조합 선택 |
| `src/v14/tiebreak.py` | 8-decimal half-even, turnover, canonical ID |
| `src/v14/manifest_plan.py` | 결과 조회 전 seed, cost, hypothesis family, periods 동결 |

## 핵심 규칙

- Mixed router는 모든 cutoff의 healthy context snapshot coverage가 필요하다.
- Coverage gap 삭제·quant-only 대체 금지
- Validation·holdout은 development selection에 사용 금지
- 선택 metric은 fold OOS 순비용 초과수익 중앙값
- 각 시장은 독립 선택하며 후보 grid 정의는 공유한다.
- Bootstrap seed, 5일 block, 10,000 resample, cost version, hypothesis family, segment boundaries를 `experiment_plan_manifest`에 동결한 뒤 PRD 02·03을 실행한다.

## CLI

```bash
uv run python -m src.v14.cli prd01-build --input <cohort>
uv run python -m src.v14.cli prd01-acceptance
```

## Acceptance

- 정확한 12/6/6 경계와 KR·US 격리
- 네 anchored fold
- Context gap, segment overlap, future row 차단
- Strategy fifth grid와 router seventh policy 차단
- Tie-break 결정성

## 완료 조건

- Frozen cohort, development-selection artifact, `experiment_plan_manifest`를 canonical hash로 생성한다.
- Validation·holdout payload를 읽지 않고 선택이 재현된다.
