# PRD: v14 PRD 03 Hypothesis And Verdicts
> **상태**: 📝 초안
> 상위 SPEC: [v14 SPEC](../SPEC.md)

## 의존성

- v14 PRD 01 experiment plan manifest
- v14 PRD 02 primary metric·CI·sample artifact

## 목표

ORB primary, 비-ORB Holm family, exploratory BH-FDR, mixed-router hierarchical gate, validation·holdout verdict를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v14/hypotheses.py` | Null, comparator, family registry |
| `src/v14/multiple_testing.py` | One-sided p-value, Holm, BH-FDR |
| `src/v14/verdicts.py` | Validation·holdout decision table |
| `src/v14/router_gate.py` | Enabled strategy와 deterministic comparator gate |

## 통계 계약

- P-value: `(1 + count(resampled_mean <= 0))/10001`
- 비-ORB strategy는 market family별 Holm step-down alpha 0.05
- ORB와 gated mixed-router paired test는 one-sided alpha 0.05
- Exploratory metric은 BH-FDR이며 confirmatory pass 금지

Hypothesis family와 comparator inventory는 PRD 01 plan manifest를 읽기만 하며 결과를 본 뒤 추가·삭제하지 않는다.

## Verdict

- Validation pass: 60/150, integrity 0, baseline·2× return >0, CI upper >0
- Holdout pass: 100/300, CI lower >0, baseline·2× return >0
- Reject: no edge, cost fragile, multiple testing
- Inconclusive: CI includes 0 또는 insufficient sample
- Invalid: data·manifest·replay integrity failure

## CLI

```bash
uv run python -m src.v14.cli prd03-acceptance
```

## Acceptance와 Mutation

- ORB primary와 14-strategy family
- Holm 첫 실패 이후 reject
- Router 선행 gate 없는 pass 차단
- `uncorrected_family`, `secondary_override`
- 모든 verdict enum happy fixture

## 완료 조건

- 같은 입력과 seed가 같은 corrected verdict를 낸다.
- Secondary·exploratory 결과가 confirmatory verdict를 뒤집지 않는다.
