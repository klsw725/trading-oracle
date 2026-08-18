# PRD: v16 PRD 03 Leaf CLI Contract
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v16 SPEC](../SPEC.md)

Canonical PRD acceptance report hash:
`sha256:862514be5f675d7b0bdb80a8a6e295dba05a91ceb86c8837a437f98d5b0a281c`

## 의존성

- [PRD 01](prd01-config-path-and-identity.md)의 config·identity service
- [PRD 02](prd02-data-calendar-health.md)의 health service

## 목표

각 기능을 직접 검증할 수 있는 작은 CLI command와 machine-readable 출력·exit code를 고정하고, 호출 위치나 locale에 따른 차이를 제거한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v16/cli.py` | Argument parse, leaf dispatch, exit code |
| `src/v16/reporting.py` | Canonical one-line JSON serialization |
| `src/v16/errors.py` | Public failure code와 redaction |

## Command 계약

| Command | Side effect | 의미 |
| --- | --- | --- |
| `config-check` | 없음 | config path·schema·identity 검증 |
| `data-health` | 없음 | calendar·dataset health 검증 |
| `prd01-acceptance` | temp 내부만 | PRD 01 mutation 실행 |
| `prd02-acceptance` | temp 내부만 | PRD 02 mutation 실행 |
| `prd03-acceptance` | temp 내부만 | CLI 자체 계약 실행 |
| `prd04-acceptance` | temp 내부만 | 전체 boundary scenario 실행 |
| `acceptance` | temp 내부만 | PRD 01~04 standalone 합성 |

인식하지 못한 command·option, 필수 option 누락은 argparse 자유문 대신 canonical `CLI_USAGE_ERROR` JSON과 exit 2를 낸다. `--help`만 사람이 읽는 stdout text와 exit 0을 허용한다.

## 출력 계약

- JSON은 UTF-8, compact separators, trailing newline 하나인 단일 line이다.
- Top-level key와 item array order는 schema가 고정한다.
- 성공 status는 `PASS`, 검증 실패는 `FAIL`, 내부 오류는 `ERROR`다.
- 절대 temp path, traceback, wall-clock timestamp, secret raw value는 stdout에 없다.
- 예상된 입력 실패의 설명은 report 안의 stable code로 전달하고 stderr는 비운다.
- 내부 오류만 redacted message를 stderr에 쓰고 exit 1이다.

## Exit Code

| Code | 의미 |
| ---: | --- |
| 0 | 요청한 검증·acceptance 통과 |
| 1 | 구현 결함 또는 예상하지 못한 runtime error |
| 2 | 입력·schema·health·usage 계약 실패 |

Pipe, subprocess, Python module 호출이 같은 serializer를 사용해야 한다. `main()`은 integer exit code를 반환하고 import 시 실행하지 않는다.

## Determinism과 격리

명령은 locale, terminal width, CWD, process ID, wall clock을 report에 반영하지 않는다. Acceptance temp directory는 실행 후 제거하며 fixture와 tracked file을 쓰지 않는다. Network API와 `data/portfolio.json`은 열지 않는다.

## CLI

```bash
uv run python -m src.v16.cli prd03-acceptance
uv run python -m src.v16.cli acceptance
```

## Acceptance와 Mutation

- 모든 leaf command의 성공·입력 실패·내부 오류 exit code
- Unknown command와 option이 `CLI_USAGE_ERROR`, exit 2
- 예상 failure에서 stderr empty, 내부 error에서 stdout canonical `ERROR`
- locale·CWD·terminal 환경 변경 뒤 stdout bytes 동일
- report array를 의도적으로 shuffle해도 serializer가 ID 순서로 복구
- import만으로 stdout·stderr·file mutation 없음

## 완료 조건

- 문서화된 모든 command가 하나의 stable JSON/exit contract를 사용한다.
- canonical version command가 정확히 `uv run python -m src.v16.cli acceptance`다.
- v17 이후 모듈과 network 없이 전 command를 검증할 수 있다.

## 비목표

- Interactive prompt, TUI, web UI
- daemon·scheduler·remote RPC
- backward-compatible legacy CLI wrapper
