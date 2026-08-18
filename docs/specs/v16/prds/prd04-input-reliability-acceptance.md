# PRD: v16 PRD 04 Input Reliability Acceptance
> **상태**: 📋 구현 예정
> 상위 SPEC: [v16 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-config-path-and-identity.md)
- [PRD 02](prd02-data-calendar-health.md)
- [PRD 03](prd03-leaf-cli-contract.md)
- v16 local immutable fixtures

## 목표

Config path·identity, calendar·data health, CLI failure semantics와 hard boundary를 한 offline deterministic version acceptance로 증명한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v16/acceptance.py` | Check·mutation scenario와 report assembly |
| `src/v16/boundaries.py` | Network, portfolio, later-version import guard |
| `src/v16/fixtures.py` | Fixture inventory와 immutable hash 검증 |
| `src/v16/cli.py` | PRD 04·version acceptance entrypoint |

## Fixture 계약

`docs/specs/v16/fixtures`는 healthy KR/US config·calendar·dataset과 mutation source를 포함한다. Inventory 파일이 모든 fixture 상대경로와 SHA-256를 열거하며 acceptance 시작과 종료에 검증한다. Mutation은 fixture 원본이 아니라 temp copy에만 적용한다.

## 필수 시나리오

- Root 밖 CWD와 project-root CWD의 동일 identity·report
- Semantic config diff와 cosmetic config diff 구분
- KR·US healthy, single-market failure, `ALL` aggregate failure
- Unknown config/schema/policy/source/kind/calendar status fail closed
- Stale, missing interval, duplicate, order, future timestamp, hash forgery
- Market·currency·account selector·arm selector identity 분리
- Leaf command별 success, expected failure, internal error, usage error
- 동일 acceptance 2회 byte-identical output

## Hard Boundary

Acceptance 동안 socket connect, DNS, HTTP client 호출을 trap해 0건을 증명한다. `data/portfolio.json`은 시작 전 없음 또는 bytes/hash를 기록하고 종료 후 동일해야 한다. `src.v17` 이후 import를 trap하며 0건이어야 한다. Credential·broker·live destination 문자열이 boundary input에 나타나면 즉시 실패한다.

## Report 계약

Report schema는 `v16.acceptance.1`이다. `checks`, `mutations`, `boundaries`의 모든 항목이 `PASS`일 때만 top-level `PASS`와 exit 0이다. 기대한 fail-closed가 발생한 mutation은 mutation test의 `PASS`다. 하나라도 누락·skip·unexpected pass면 exit 1이다.

## CLI

```bash
uv run python -m src.v16.cli prd04-acceptance
uv run python -m src.v16.cli acceptance
```

Version acceptance는 PRD command subprocess를 재호출하지 않고 동일 typed service를 직접 조합한다. 따라서 shell, PATH, timing 차이를 결과에 넣지 않는다.

## Acceptance와 Mutation

- SPEC의 14개 mutation ID를 모두 report에 포함
- 각 mutation이 expected stable failure code와 evidence hash를 가짐
- Fixture inventory 시작·종료 hash 동일
- Network 0, later import 0, portfolio mutation 0
- 임시 디렉터리 정리 뒤 tracked worktree 변화 없음
- JSON report 자체를 recovery truth나 다음 실행 입력으로 읽지 않음

## 완료 조건

- `uv run python -m src.v16.cli acceptance`가 offline fixture만으로 exit 0이다.
- 두 연속 실행 stdout이 byte-identical하다.
- v17이 없어도 v16 acceptance가 import·runtime error 없이 완료된다.
- v16이 durable state를 생성하지 않고 검증된 `RuntimeInputBundle` 계약에서 종료한다.

## 비목표

- 실제 vendor endpoint smoke test
- 계좌 migration·event replay·projection 검증
- live 주문 또는 credential 유효성 확인
