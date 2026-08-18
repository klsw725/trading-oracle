# PRD: v16 PRD 01 Config Path And Identity
> **상태**: ✅ 구현 완료
> 상위 SPEC: [v16 SPEC](../SPEC.md)

Canonical PRD acceptance report hash:
`sha256:a44990bc3898e6199ffd6863ef50f4b039310b4b79fbd97691db494f99548f6b`

## 의존성

- 저장소의 `pyproject.toml`, dependency lock, `config.yaml` 형식
- v16 로컬 config fixture
- 후속 버전 의존성 없음

## 목표

CWD에 좌우되지 않는 project root와 config 경로를 결정하고, strict·versioned config를 canonical `RuntimeIdentity`로 변환한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v16/models.py` | `RuntimeConfig`, `RuntimeIdentity`, typed failure code |
| `src/v16/paths.py` | Package 기준 root 탐색과 root 내부 path 검증 |
| `src/v16/config.py` | Duplicate를 거부하는 YAML load와 strict schema parse |
| `src/v16/canonical.py` | Canonical JSON bytes와 SHA-256 |
| `src/v16/identity.py` | Config·policy·runtime·lock·input identity 조립 |

## 경로 계약

- Root marker는 `pyproject.toml`과 `docs/specs/v16/SPEC.md`의 동시 존재다.
- `--config`가 없으면 `<root>/config.yaml`, 있으면 root 기준으로 해석한다.
- `resolve()` 결과가 root 밖이면 absolute·relative·symlink 여부와 무관하게 거부한다.
- 환경변수, home, CWD config를 fallback으로 읽지 않는다.
- Missing, directory, unreadable, `.yaml`/`.yml` 외 확장자는 typed input failure다.

## 설정 Schema

최소 top-level key는 `config_schema_version`, `policy_version`, `runtime`, `markets`, `data`다. `markets`는 `KR`과 `US`를 분리하며 각각 currency, timezone, calendar version을 가진다. `runtime`은 paper mode만 허용한다. Unknown key와 unknown enum을 보존하거나 무시하지 않는다.

Credential, token, broker account ID는 schema에 없다. 발견하면 unknown key로 실패하고 출력에 원문 값을 포함하지 않는다.

## Identity 계약

Canonicalization은 UTF-8/NFC, key sort, compact JSON, root-relative POSIX path를 사용한다. `RuntimeIdentity`에는 다음이 필수다.

- `identity_schema_version=v16.runtime-identity.1`
- canonical config hash
- explicit policy version
- calendar version map
- input manifest hash
- Python major.minor.micro
- lockfile content hash

YAML 표현상 차이는 identity를 바꾸지 않고 의미 변경은 바꾼다. 지원하지 않는 version은 migration을 추측하지 않고 실패한다.

## Failure 계약

| Code | 조건 |
| --- | --- |
| `PROJECT_ROOT_NOT_FOUND` | 두 root marker를 찾지 못함 |
| `CONFIG_PATH_OUTSIDE_ROOT` | resolved path가 root 밖 |
| `CONFIG_NOT_READABLE` | 없음·directory·권한 오류 |
| `CONFIG_PARSE_ERROR` | duplicate key·금지 tag·문법 오류 |
| `UNKNOWN_CONFIG_KEY` | schema 밖 key |
| `UNSUPPORTED_CONFIG_SCHEMA` | 알 수 없는 schema version |
| `UNKNOWN_POLICY_VERSION` | 등록되지 않은 policy version |

모든 실패는 config raw value나 host 절대경로를 canonical report에 노출하지 않는다.

## CLI

```bash
uv run python -m src.v16.cli config-check
uv run python -m src.v16.cli prd01-acceptance
```

`config-check` 성공은 identity report와 exit 0, 계약상 실패는 failure code report와 exit 2다.

## Acceptance와 Mutation

- 서로 다른 CWD에서 동일 root·config hash·identity
- 주석·YAML key order 변경 시 identity 불변
- 정책 값·calendar version·lock hash 변경 시 identity 변경
- `config_escape`, `unknown_config_policy`, duplicate key와 symlink escape 거부
- secret-like unknown key의 값이 stdout·stderr에 나타나지 않음

## 완료 조건

- 모든 경로와 identity 결과가 deterministic typed value다.
- Unknown 또는 root 밖 config를 허용하는 fallback이 없다.
- 구현이 v17 이후 package를 import하지 않는다.

## 비목표

- 설정 editor, 자동 migration, 환경변수 override
- credential 또는 live broker 설정
- runtime state 저장
