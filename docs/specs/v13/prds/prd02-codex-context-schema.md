# PRD: v13 PRD 02 Codex, Context, Schema
> **상태**: 📝 초안
> 상위 SPEC: [v13 SPEC](../SPEC.md)

## 의존성

- v10 `context_artifact`
- v12 execution-feasible candidates
- 기존 `src/agent/codex.py` provider boundary

## 목표

시장별 1회 Codex batch, 20초 no-retry timeout, structured output, point-in-time context, veto·abstain, prompt-injection 경계를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v13/codex.py` | Provider adapter, timeout, recorded response |
| `src/v13/context.py` | 24시간 뉴스·7일 공시 snapshot과 priority |
| `src/v13/prompts.py` | Canonical prompt bytes와 untrusted-data boundary |
| `src/v13/schema.py` | Candidate output envelope와 forbidden fields |
| `src/v13/validation.py` | Item·envelope 오류 분리, veto evidence |

## 핵심 계약

- Input은 execution-feasible candidate만 포함한다.
- Fixed budget overflow는 후보를 자르지 않고 market quant-only다.
- Item 오류·abstain은 symbol quant-only, envelope 오류는 market quant-only다.
- Hard veto는 허용 code와 cutoff 이전 artifact ID가 모두 있어야 한다.
- Tool·web 접근, ticker·strategy·quantity·price·order 생성은 금지한다.
- HTML/script/style/hidden 제거 후 외부 text를 untrusted block에 넣는다.

## CLI

```bash
uv run python -m src.v13.cli prd02-acceptance
uv run python -m src.v13.cli codex-integration-probe
```

Integration probe는 opt-in이며 acceptance는 credential·network 없이 recorded fixture만 사용한다.

## Acceptance와 Mutation

- Normal batch, timeout, auth/provider/model mismatch
- Invented candidate와 order instruction 차단
- Partial item, duplicate ID, cutoff·prompt hash mismatch
- Future news, unproven veto, prompt injection
- Overflow market quant-only와 no retry

## 완료 조건

- Prompt, model, schema, source IDs, raw·parsed response hash를 보존한다.
- 실제 network가 없어도 모든 failure path가 재현된다.
