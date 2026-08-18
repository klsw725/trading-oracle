# Trading Oracle v16 SPEC: Runtime Inputs, Configuration, Data And Leaf-CLI Reliability
> **상태**: 📋 구현 예정

v16은 paper system이 실행 전에 읽는 경로, 설정, 정책 identity, 시장 데이터와 calendar를 하나의 검증된 runtime input으로 고정한다. 이 버전은 계좌나 주문 상태를 만들지 않으며, [v15](../v15/SPEC.md)의 운영 의미를 새 저장소로 이전하지 않는다.

## 0. 구현 완결성 계약

- v16은 현재 저장소와 v15까지의 문서·고정 fixture만 의존하며 v17 이후 모듈을 import하거나 산출물을 요구하지 않는다.
- `uv run python -m src.v16.cli acceptance`는 네트워크 없이 v16 로컬 fixture만 읽어 canonical JSON 보고서를 stdout에 한 줄로 출력하고 모든 check가 통과하면 exit 0이어야 한다.
- 설정 경로와 project root, config·policy identity, KR·US calendar와 data health, leaf CLI 출력·exit code를 end-to-end 검증한다.
- 모든 시간 판정은 fixture의 명시적 `as_of`를 사용한다. wall clock, 파일 mtime, 실행 순서가 결과를 바꾸지 않는다.
- Acceptance 전후 tracked worktree와 `data/portfolio.json`의 존재 여부·bytes·hash가 같아야 하며 broker, credential, live destination에 접근하지 않는다.
- 이 조건과 아래 Acceptance Criteria가 모두 통과하면 v16은 후속 버전 없이 단독 완료다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Config Path And Identity](prds/prd01-config-path-and-identity.md) | `src/v16/paths.py`, `src/v16/config.py`, `src/v16/identity.py` | `RuntimeConfig`와 `RuntimeIdentity` |
| PRD 02 | [Data And Calendar Health](prds/prd02-data-calendar-health.md) | `src/v16/calendar.py`, `src/v16/data_health.py`, `src/v16/input_manifest.py` | `InputHealthReport`와 manifest |
| PRD 03 | [Leaf CLI Contract](prds/prd03-leaf-cli-contract.md) | `src/v16/cli.py`, `src/v16/reporting.py` | 안정된 leaf command JSON 계약 |
| PRD 04 | [Input Reliability Acceptance](prds/prd04-input-reliability-acceptance.md) | `src/v16/acceptance.py`, `src/v16/boundaries.py` | standalone acceptance report |

PRD 01→04 순서로 구현한다. PRD 04는 PRD 01~03을 실제 CLI 경계에서 합성하지만 v17 저장소나 계좌를 만들지 않는다.

## 1. 범위와 불변식

v16의 입력 단위는 `RuntimeInputBundle`이다. 다음 항목을 모두 가진 검증 완료 bundle만 후속 paper runtime에 전달할 수 있다.

- 절대 `project_root`와 `config_path`
- `config_schema_version`, `policy_version`, canonical config hash
- `as_of`, market, currency, session과 calendar version
- 원천별 provenance, normalized dataset hash, row count, min/max timestamp
- freshness, completeness, ordering, duplicate, symbol identity verdict
- 전체 항목을 묶은 `runtime_identity`

모든 실행은 paper-only다. KR과 US, KRW와 USD, account와 arm namespace를 합치거나 한 범위의 정상 입력으로 다른 범위의 실패를 덮지 않는다. v16에는 계좌 mutation이 없지만 후속 버전이 격리를 검증할 수 있도록 market·currency·account·arm selector를 identity에 별도 필드로 보존한다.

## 2. 경로 결정 계약

`project_root`는 `src/v16` package 위치에서 부모를 따라 올라가 `pyproject.toml`과 `docs/specs/v16/SPEC.md`를 함께 가진 첫 디렉터리로 결정한다. current working directory는 root 결정에 사용하지 않는다.

설정 경로 우선순위는 다음 하나의 규칙으로 고정한다.

1. CLI에 `--config PATH`가 있으면 그 경로
2. 없으면 `<project_root>/config.yaml`

상대 `--config`는 current working directory가 아니라 `project_root` 기준으로 해석한다. `resolve()`한 설정 경로가 root 밖이거나 symlink를 통해 root 밖으로 나가면 `CONFIG_PATH_OUTSIDE_ROOT`로 거부한다. 파일 없음, directory, unreadable, 확장자가 `.yaml` 또는 `.yml`이 아님도 거부한다. 환경변수나 home directory fallback은 없다.

## 3. 설정과 정책 Identity

설정은 YAML을 읽은 뒤 strict schema로 parse한다. 허용된 key와 enum 밖의 값, duplicate YAML key, implicit timestamp·set·binary tag, non-finite number는 거부한다. Secret 값은 v16 schema에 존재하지 않으며 credential처럼 보이는 key도 `UNKNOWN_CONFIG_KEY`다.

Canonical config는 다음 규칙을 사용한다.

- UTF-8, Unicode NFC, object key lexicographic sort
- JSON separators `,`와 `:`에 공백 없음
- integer와 decimal string을 schema가 지정한 타입으로 유지
- 경로는 project-root-relative POSIX string
- SHA-256 표기는 `sha256:<lowercase hex>`

`RuntimeIdentity`는 `identity_schema_version`, canonical config hash, `policy_version`, calendar version, input manifest hash, runtime Python version, dependency lock hash를 canonical JSON으로 묶은 SHA-256이다. 주석, YAML key 순서, 절대 checkout 경로는 identity를 바꾸지 않지만 의미 값, 정책 버전, calendar/data hash는 반드시 바꾼다.

`config_schema_version`과 `policy_version`은 필수 문자열이다. 지원하지 않는 schema 또는 알 수 없는 policy version은 추정·downgrade하지 않고 fail closed 한다.

## 4. Calendar 계약

KR과 US calendar는 독립 versioned artifact다. 각 record는 `market`, `session_date`, `status`, timezone, open/close, early-close 여부를 가진다.

- KR timezone은 `Asia/Seoul`, currency는 `KRW`다.
- US timezone은 `America/New_York`, currency는 `USD`다.
- `OPEN`, `CLOSED`, `EARLY_CLOSE` 외 status는 거부한다.
- Open session은 UTC 변환 후 open < close여야 한다.
- 동일 market·session_date 중복이나 상충 record는 전체 해당 시장 health 실패다.
- Calendar version과 content hash가 manifest와 일치하지 않으면 실패한다.

한 시장 calendar 실패는 다른 시장을 정상으로 바꾸지 않는다. 요청 범위가 `ALL`이면 둘 중 하나의 실패로 전체 요청이 실패하고 시장별 세부 verdict를 함께 보고한다.

## 5. Data Health 계약

각 dataset descriptor는 `dataset_kind`, market, currency, session, source, source version, observed cutoff, expected interval, row count, min/max timestamp, content hash를 가진다. Health 판정 순서는 schema→identity→hash→ordering/duplicate→coverage→freshness다.

| 상태 | 의미 | 사용 가능 여부 |
| --- | --- | --- |
| `HEALTHY` | 모든 계약 통과 | 가능 |
| `STALE` | `as_of` 기준 freshness 한도 초과 | 불가 |
| `INCOMPLETE` | expected coverage 또는 필수 symbol 누락 | 불가 |
| `HASH_MISMATCH` | descriptor와 bytes 불일치 | 불가 |
| `UNKNOWN` | 지원하지 않는 source, kind, version, market 또는 status | 불가 |
| `INVALID` | schema, timestamp, ordering, duplicate, currency 불일치 | 불가 |

Freshness threshold는 versioned config에 dataset kind·market별 duration으로 명시한다. replay는 기록된 `as_of`와 `observed_at`만 사용한다. 데이터가 미래 timestamp를 가지거나 market/currency가 `KR/KRW`, `US/USD` 짝과 다르면 실패한다.

## 6. Fail-Closed와 격리

- Unknown config, policy, source, calendar status, dataset kind는 기본값으로 처리하지 않는다.
- Stale, hash mismatch, calendar conflict, manifest mismatch는 warning이 아니라 요청 실패다.
- KR fixture를 US 결과에, USD를 KR account selector에, 한 arm identity를 다른 arm에 재사용하지 않는다.
- `runtime_identity`가 다른 두 artifact를 한 run에서 섞지 않는다.
- JSON report는 관측 결과일 뿐 상태나 복구 입력이 아니다.
- 어떤 v16 명령도 `data/portfolio.json`을 생성·수정·삭제하지 않는다.

## 7. Leaf CLI 계약

모든 명령은 `uv run python -m src.v16.cli <command>` 형태다.

| Command | 입력 | 성공 출력 |
| --- | --- | --- |
| `config-check` | `--config`, 선택 fixture root | config·policy·runtime identity report |
| `data-health` | manifest, `--as-of`, market | market별 calendar·data health report |
| `prd01-acceptance` | 내장 fixture | PRD 01 check report |
| `prd02-acceptance` | 내장 fixture | PRD 02 check report |
| `prd03-acceptance` | 내장 fixture | PRD 03 check report |
| `prd04-acceptance` | 내장 fixture | PRD 04 check report |
| `acceptance` | 내장 fixture | v16 전체 report |

성공과 예상된 검증 실패 모두 stdout에 canonical JSON 한 줄을 출력한다. 사람용 설명과 예기치 않은 runtime error는 stderr로 보낸다. Exit code는 성공 0, 계약상 입력 실패 2, 내부 오류 1이다. Key order와 배열 order는 계약으로 고정하며 locale, CWD, wall clock에 영향받지 않는다.

## 8. Acceptance 출력

Version acceptance report는 최소 다음 필드를 가진다.

```json
{"schema_version":"v16.acceptance.1","version":"v16","status":"PASS","runtime_identity":"sha256:...","checks":[],"mutations":[],"boundaries":[]}
```

`checks`, `mutations`, `boundaries`는 `id` 오름차순이다. 각 항목은 `id`, `status`, `expected`, `actual`, `evidence_hash`를 가진다. Timestamp와 임시 절대경로는 출력하지 않는다. 동일 입력의 두 실행은 byte-identical report를 만든다.

## 9. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `cwd_independence` | repo 밖 CWD에서 canonical CLI 실행 | 같은 root·report hash |
| `config_escape` | root 밖 absolute path 또는 escaping symlink | `CONFIG_PATH_OUTSIDE_ROOT`, exit 2 |
| `unknown_config_policy` | unknown key·schema·policy version 주입 | fail closed |
| `semantic_config_change` | 의미 값만 변경 | config·runtime identity 변경 |
| `cosmetic_config_change` | 주석·key 순서만 변경 | identity 불변 |
| `calendar_conflict` | session open/close 또는 version hash 상충 | 해당 market 실패 |
| `stale_at_replay_cutoff` | observed_at을 threshold 밖으로 이동 | `STALE` |
| `data_hash_forgery` | bytes 변경 후 descriptor hash 유지 | `HASH_MISMATCH` |
| `market_currency_swap` | KR/USD 또는 US/KRW 조합 | `INVALID` |
| `unknown_source_kind` | 미등록 source·dataset kind | `UNKNOWN` |
| `report_nondeterminism` | locale·CWD·wall clock 변경 | byte-identical report |
| `portfolio_mutation` | acceptance 전후 portfolio path 감시 | 존재·bytes·hash 불변 |
| `network_attempt` | socket/DNS/HTTP를 차단하고 기록 | 호출 0건, acceptance PASS |
| `later_version_import` | v17 이후 package를 import trap으로 교체 | import 0건, acceptance PASS |

## 10. 의존성과 비목표

의존성은 Python 표준 라이브러리, 현재 lockfile의 YAML parser, v16 package와 `docs/specs/v16/fixtures`로 제한한다. v15 runtime 상태나 후속 SQLite schema는 의존성이 아니다.

다음은 v16 비목표다.

- live broker, 주문 destination, credential 수집·검증
- SQLite 계좌, event append, projection, reconciliation
- web UI, multi-user, multi-host, daemon
- 새 데이터 vendor, 새 전략, vendor fallback 정책
- network가 필요한 acceptance
- 기존 `data/portfolio.json` migration 또는 mutation

## 11. Acceptance Criteria

- CWD와 무관한 project root와 root 내부 config path가 결정된다.
- Strict config, versioned policy와 canonical runtime identity가 구체적으로 정의된다.
- KR/US calendar와 data가 market·currency별로 독립 검증된다.
- Unknown, stale, hash mismatch, 잘못된 market/currency가 fail closed 한다.
- Leaf CLI의 command, JSON, stderr, exit code가 안정된 계약을 가진다.
- Canonical acceptance가 offline·deterministic이며 v17 이후를 import하지 않는다.
- 모든 mutation이 기대 실패를 만들고 acceptance 자체는 tracked state와 portfolio를 바꾸지 않는다.
- v16이 검증된 입력을 산출하면 책임이 끝나며 durable account state는 v17 책임이다.
