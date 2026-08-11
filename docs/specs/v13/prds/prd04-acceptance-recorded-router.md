# PRD: v13 PRD 04 Acceptance And Recorded Router
> **상태**: 📝 초안
> 상위 SPEC: [v13 SPEC](../SPEC.md)

## 의존성

- 구현 완료된 v10~v12 canonical fixtures
- v13 PRD 01~03

## 목표

Network 없이 recorded Codex response로 v13 전체 router·fallback·switch·replay를 검증하고 canonical report를 만든다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v13/acceptance.py` | Scenario와 mutation orchestration |
| `src/v13/cli.py` | PRD별·version acceptance command |
| `docs/specs/v13/fixtures/` | Candidate, context, Codex response, switch fixtures |
| `src/v13/coverage.py` | SPEC→PRD→fixture coverage matrix |

## Version CLI

```bash
uv run python -m src.v13.cli acceptance
```

## 필수 Coverage

- 80:20, midrank, ties, veto, quant-only
- NO_TRADE 6개 policy fixture
- Normal, timeout, abstain, item·envelope error, overflow
- News·filing cutoff와 injection
- Two-leg switch와 circuit breaker
- Raw response replay와 provider call count 0
- SPEC mutation 전체
- v14 이후 import count 0

Normative probe inventory에는 `invented_candidate`, `order_instruction`, `future_news`, `partial_item_bad`, `duplicate_id`, `unbounded_batch`, `confidence_weight`, `unproven_veto`, `replay_recall`, `rank_tie_drift`, `single_candidate_gap`, `slot_tie_nondeterministic`, `switch_same_boundary`를 정확한 ID로 포함한다.

## 완료 조건

- Acceptance exit 0과 canonical JSON report
- Credential·network 없이 전체 path 실행
- Local router policy가 run 전에 동결됨
- Candidate 생성·주문 instruction·live side effect 0건
