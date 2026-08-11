# PRD: v10 PRD 04 Context, Canonical Artifacts, Acceptance
> **상태**: 📝 초안
> 상위 SPEC: [v10 SPEC](../SPEC.md)

## 의존성

- v10 PRD 01~03 산출물

## 목표

1. 뉴스·공시·기업행사·규제자료를 point-in-time context artifact로 보존한다.
2. `published_at`, archival `observed_at`, local `ingested_at`을 분리한다.
3. 모든 v10 artifact의 canonical hash·forbidden-field 경계를 검증한다.
4. v10 전체 acceptance CLI를 로컬 fixtures만으로 실행한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v10/context.py` | Context normalize, relevance, archival qualification |
| `src/v10/canonical.py` | Canonical JSON, finite numeric, duplicate-key, hash 검증 |
| `src/v10/acceptance.py` | PRD acceptance orchestration과 mutation matrix |
| `src/v10/cli.py` | `prdXX-*`와 version-level `acceptance` command |
| `docs/specs/v10/fixtures/` | 모든 로컬 canonical fixtures |

## Context 계약

- 당시 보존본과 archival observed_at을 증명할 수 있어야 historical 자격이 있다.
- 현재 처음 수집한 문서의 published_at을 과거 observed_at으로 바꾸지 않는다.
- 자료가 없는 cutoff도 empty healthy snapshot으로 기록한다.
- Coverage gap, supersede ref, source identity, canonical text hash를 숨기지 않는다.

## CLI

```bash
uv run python -m src.v10.cli prd04-acceptance
uv run python -m src.v10.cli acceptance
```

Version acceptance는 PRD 01~04 happy path와 모든 normative mutation을 실행하고 canonical JSON을 stdout에 출력한다. 후속 버전 directory 또는 module import는 금지한다.

## 필수 시나리오

- 정상 context, empty healthy cutoff, context supersede
- `backfilled_observation` 차단
- Duplicate key, non-finite numeric, hash mutation
- Secret, credential, raw account ID field 차단
- Primary·fallback·missing minute·late revision·holiday·early close
- Universe freeze·corporate action·price layer
- 반복 실행 byte-identical report

## 완료 조건

- `uv run python -m src.v10.cli acceptance` exit 0
- PRD별 coverage와 mutation result가 report에 포함
- v10 문서·로컬 fixtures·공통 adapter만으로 실행
- Broker submit과 portfolio mutation 0건
