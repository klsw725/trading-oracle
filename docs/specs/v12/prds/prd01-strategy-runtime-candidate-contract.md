# PRD: v12 PRD 01 Strategy Runtime And Candidate Contract
> **상태**: 📝 초안
> 상위 SPEC: [v12 SPEC](../SPEC.md)

## 의존성

- 구현 완료된 v10 complete 5분봉·universe·adjustment
- 구현 완료된 v11 execution decision·risk·ledger
- [v12 Strategy Grids](../STRATEGY-GRIDS.md)

## 목표

15개 전략이 공유하는 feature engine, grid registry, candidate identity, dedup, pre-portfolio·execution-feasible 경계를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v12/models.py` | Strategy, parameter set, candidate typed model |
| `src/v12/features.py` | TR, ATR14, RVOL, VWAP, RET, RS, CLV, P60 |
| `src/v12/registry.py` | 15 strategy ID와 최대 4개 grid registry |
| `src/v12/candidates.py` | Gate evaluation, score, identity, lifecycle |
| `src/v12/adapters.py` | v10 input과 v11 execution_decision 변환 |

## Candidate 계약

- ID seed: market, symbol, strategy ID, strategy version, parameter set, cutoff
- Score: finite 0~1, Strategy Grids의 component 평균
- `entry_boundary=first_1m_after_decision`
- 같은 strategy-symbol-session의 최초 false-to-true event만 emit
- Data·session·instrument·action·short regulation 통과 후 `pre_portfolio_candidate`
- v11 계좌 risk 통과 후 `execution_feasible_candidate`

## CLI

```bash
uv run python -m src.v12.cli prd01-build --input <fixture>
uv run python -m src.v12.cli prd01-verify --artifact <artifact>
uv run python -m src.v12.cli prd01-acceptance
```

## Acceptance와 Mutation

- P60 현재·미래 값 제외, 최소 20 관측, midrank determinism
- Score out-of-range와 missing feature 차단
- Fifth grid와 KR·US grid definition drift 차단
- Duplicate-session signal no-op
- Candidate collision과 strategy ID mutation 차단
- 미완결 benchmark·5분봉 차단

## 완료 조건

- 공통 engine이 전략별 하드코딩 없이 registry를 실행한다.
- 모든 parameter set을 `active_parameter_set_id`로 직접 선택한다.
- 같은 입력은 byte-identical candidate를 생성한다.
