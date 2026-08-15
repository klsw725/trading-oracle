# PRD: v14 PRD 04 Manifest, Holdout, Acceptance
> **상태**: 📝 초안
> 상위 SPEC: [v14 SPEC](../SPEC.md)

## 의존성

- v14 PRD 01~03

## 목표

PRD 01의 pre-run experiment plan manifest를 검증하고 실행 결과 hash를 결합한 result manifest, validation one-way gate, holdout one-shot, v14 독립 acceptance CLI를 구현한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v14/manifest.py` | Pre-run plan 검증과 결과 hash를 결합한 result manifest |
| `src/v14/integrity.py` | Hash, segment, replay, version 검증 |
| `src/v14/holdout.py` | Approval-bound one-shot lease |
| `src/v14/prd04_sources.py` | Source path read-once typed parsing and evidence hashes |
| `src/v14/prd04_runs.py` | Segment-specific validation and post-lease holdout artifacts |
| `src/v14/acceptance.py` | Synthetic 12/6/6 scenarios |
| `src/v14/cli.py` | Build, verify, acceptance commands |

## Manifest 필수 항목

PRD 01 plan manifest는 code commit·dirty state, runtime lock, config, strategy·risk·router, universe, calendar, data, source, cost, prompt·model·schema, seeds, periods, hypothesis family를 포함한다. PRD 04는 이를 변경하지 않고 validation·holdout artifact hash와 verdict를 결합해 result manifest를 만든다.

## CLI

```bash
uv run python -m src.v14.cli prd04-acceptance
uv run python -m src.v14.cli acceptance
uv run python -m src.v14.cli prd04-build \
  --input docs/specs/v14/fixtures/prd04-source.json \
  --history docs/specs/v14/fixtures/prd04-history.json
```

## Mutation

- `validation_tune`, `holdout_repeat`, `cost_change`
- `manifest_partial`, `future_revision`, `context_gap_fill`
- `validation_undefined`와 sample gate 없는 holdout open 차단
- Validation reject 뒤 holdout open
- Holdout result 뒤 같은 version rerun

## Version Acceptance

Local synthetic cohort로 PASS, no-edge, cost-fragile, multiple-testing, inconclusive, insufficient, invalid를 모두 실행한다. v15 module·paper operation 없이 canonical report를 출력한다.

## 완료 조건

- `uv run python -m src.v14.cli acceptance` exit 0
- Holdout은 승인된 exact manifest에서 한 번만 실행
- PRD 02/03 production build는 validation-only artifact를 출력하고, holdout-only
  builder는 valid approval-bound lease 뒤에만 호출한다.
- Source descriptor의 PRD 01~03 및 v13 경로를 각각 한 번 읽어 raw content hash와
  typed artifact hash를 result bundle에 고정한다.
- 하나의 experiment-level `HoldoutPlan`이 KR/US validation eligible set, router enabled
  set, correction/verdict hash, holdout period hash를 함께 동결한다.
- 각 시장의 15개 전략과 router raw/hierarchy validation이 모두 PASS일 때만 global
  holdout plan을 열며 부분 PASS나 router reject/inconclusive는 허용하지 않는다.
- CLI build는 full prior history를 명시적으로 받고 lease의 prior head와 일치시킨다.
- `HistoryEntry`는 result manifest가 아니라 post-lease `holdout_run_hash`를 기록하며,
  consumed history head를 만든 뒤 result manifest를 생성한다.
- One-shot 상태는 `HoldoutPlan → Approval → Lease → HistoryEntry` immutable hash chain으로 전달하며 승인된 최신 history head를 다음 실행 입력으로 요구한다.
- 모든 mutation이 typed failure로 보고됨
- Offline verdict와 frozen artifacts만으로 v14 책임이 종료됨
