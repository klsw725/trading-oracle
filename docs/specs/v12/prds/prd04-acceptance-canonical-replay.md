# PRD: v12 PRD 04 Acceptance And Canonical Replay
> **상태**: 📝 초안
> 상위 SPEC: [v12 SPEC](../SPEC.md)

## 의존성

- 구현 완료된 v10·v11 canonical fixtures
- v12 PRD 01~03

## 목표

15개 전략·60개 parameter arm·모든 mutation을 v13 없이 replay하고 canonical acceptance report를 만든다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v12/acceptance.py` | Coverage matrix와 mutation runner |
| `src/v12/cli.py` | PRD별·version-level commands |
| `src/v12/replay.py` | Strategy fixture deterministic replay |
| `docs/specs/v12/fixtures/` | 15전략 happy/no-signal/mutation fixtures |

## Version CLI

```bash
uv run python -m src.v12.cli acceptance
```

## 필수 Coverage

- Strategy ID 15/15
- Long parameter 40/40, Short parameter 20/20
- Shadow namespace 60/60
- 각 전략 happy·no-signal·missing feature
- `wick_breakout`, `late_orb`, `hidden_stop`
- `current_in_reference`, `score_out_of_range`, `future_benchmark`
- `grid_fifth`, `market_grid_drift`, `duplicate_session_signal`
- `short_without_borrow`, `ownership_transfer`, `candidate_collision`
- Partial fill·cost·forced exit attribution

Normative probe inventory에는 SPEC ID `wick_breakout`, `late_orb`, `incomplete_feature`, `grid_fifth`, `market_grid_drift`, `hidden_stop`, `llm_signal_creation`, `ownership_transfer`, `candidate_collision`을 그대로 보존한다.

## Report와 경계

Report는 전략·grid·arm·mutation coverage, artifact hashes, dependency manifest를 포함한다. V13 이후 import, LLM call, 통계 승격은 0이어야 한다.

## 완료 조건

- `uv run python -m src.v12.cli acceptance` exit 0
- 누락 strategy·grid·fixture가 있으면 non-zero
- 반복 실행 report가 byte-identical
- V10·v11와 v12 로컬 fixture만으로 전체 shadow run이 동작
