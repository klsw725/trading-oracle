# PRD: v22 PRD 01 Subprocess-Only Black-Box Harness And Independent Oracle
> **상태**: 📋 구현 예정
> 상위 SPEC: [v22 SPEC](../SPEC.md)

## 의존성

- [v21 Unified Operator CLI](../../v21/prds/prd01-unified-operator-cli.md)의 executable, `v21.cli-response.1`과 exit 0~8 계약
- [v21 Operator Journey](../../v21/prds/prd04-operator-journey-acceptance.md)의 공개 command 순서와 failure message intent
- Python 표준 라이브러리 JSON, subprocess, hash와 filesystem API

## 목표

제품 구현과 expected-result 계산을 공유하지 않는 black-box harness를 만든다. Harness는 v21 executable의 argv/stdin/stdout/stderr/exit와 외부 file/process 관측만 수집하고, 독립 oracle은 사람이 작성한 의미 관계로 release 품질을 판정한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v22/harness.py` | v21 subprocess 호출과 transcript capture |
| `src/v22/schema.py` | 표준 라이브러리 기반 public response parser |
| `src/v22/oracle.py` | manually authored expectation 평가 |
| `src/v22/expectations.py` | frozen scenario/command/semantic relation inventory |
| `src/v22/independence.py` | import/source/provenance audit |

## Hard Independence

V22 production/test source에서 `src.v16`~`src.v21` import는 모두 금지한다. 동적 import, module string 조립, `sys.path`로 product module loading, monkeypatch를 통한 내부 trap 설치도 같은 위반이다. 허용되는 product reference는 argv의 module string `src.v21.cli`, 문서 schema version과 public command/error name뿐이다.

독립성 검사는 세 겹이다.

1. V22 source AST를 표준 `ast`로 scan해 import/call/path 금지 패턴을 검사한다.
2. Acceptance parent의 import audit hook가 금지 prefix load를 기록하고 즉시 실패시킨다.
3. Expectation artifact마다 `authoring=manual`, reviewer, source document section과 content hash를 요구하고 product builder provenance를 거부한다.

Product reducer/canonicalizer/repository/fixture builder를 복제한 소스도 금지다. Oracle은 product 알고리즘을 재구현하지 않고 외부에서 확인 가능한 equality, inequality, containment, state transition만 기술한다.

## Invocation 계약

모든 product 호출 argv prefix는 정확히 다음 네 token이다.

```text
uv run --frozen --offline python -m src.v21.cli
```

Shell은 사용하지 않고 argv array로 실행한다. Alternate Python, console script, v16~v20 leaf CLI와 v21 in-process call은 허용하지 않는다. Invocation record는 `invocation_id`, scenario/step ID, normalized argv, cwd label, stdin hash/length, env key inventory, stdout/stderr hash/length, actual exit/signal과 timeout state를 가진다.

Harness는 stdout/stderr를 bytes로 보존하고 parser가 성공하기 전에 trim, key sort 또는 error 복구를 하지 않는다. Secret scan은 raw bytes와 parsed safe string 모두에 실행한다.

## Independent Response Parser

Parser는 `json.JSONDecoder`와 duplicate-key hook를 사용한다. 다음 중 하나면 transport FAIL이다.

- UTF-8 오류, BOM, leading/trailing whitespace, newline 0개/2개 이상
- JSON object 외 top-level, duplicate key, trailing JSON
- top-level exact key set/order 변경
- schema, command 또는 request ID가 invocation과 불일치
- response `exit_code`와 actual process exit 불일치
- `status`/`data`/`error` 조합이 documented shape와 불일치
- expected failure stderr non-empty 또는 internal stderr에 forbidden value 포함

Command data는 required public field와 primitive/container type만 parse한다. Unknown optional evolution은 contract가 허용한다고 명시된 map 위치에서만 허용하며 top-level extra는 항상 실패다.

## Expectation DSL

Expectation은 executable Python function이 아니라 immutable data와 작은 고정 evaluator enum으로 표현한다.

| Relation | 의미 |
| --- | --- |
| `EXACT` | 문서상 constant enum/schema/error/exit와 같음 |
| `PRESENT` / `ABSENT` | required/forbidden field 또는 file |
| `SAME_AS` / `DIFFERS_FROM` | 두 공개 response path의 equality/inequality |
| `MATCHES` | documented lexical pattern |
| `CONTAINS_REF` | prior public ID/hash를 후속 response가 참조 |
| `WRITESET_EQUALS` | before/after inventory equality |
| `COUNT_DELTA` | 외부 관측 가능한 file/process 개수 변화 |
| `HASH_BINDS` | manifest field가 exact artifact bytes hash |

Arbitrary expression, Python callback과 product object adapter는 허용하지 않는다. Opaque ID의 exact 값은 expectation에 쓰지 않고 lexical form과 cross-step consistency만 검증한다.

## Scenario Transcript

각 step은 prior response에서 allowlisted JSON pointer만 추출한다. 추출값은 다음 argv/request fixture에 치환되며 transcript가 lineage를 기록한다. Product DB, report export 또는 internal event payload에서 hidden ID를 찾아서는 안 된다.

Transcript schema `v22.transcript.1`은 scenario ID, ordered invocation refs, extraction lineage, oracle check refs, input/output evidence hashes와 terminal verdict를 가진다. Raw absolute path, PID, secret/signature bytes와 wall time은 final artifact에 넣지 않는다.

## 자기인증 방지

- V21 `acceptance` command는 compatibility observation으로 한 번 호출할 수 있으나 그 `PASS`를 v22 check PASS로 사용하지 않는다.
- V21 `doctor READY`는 doctor contract check만 통과시킨다. Write-set, network와 restart check는 별도 외부 증거가 필요하다.
- Report의 self-declared hash는 독립 SHA-256로 다시 계산하고 다른 public response와 관계를 확인한다.
- Product가 출력한 expected error 목록, migration head 또는 scenario inventory를 oracle source로 사용하지 않는다.
- Golden file은 manually authored request/cause만 허용한다. 전체 successful stdout golden은 금지한다.

## 독립 Oracle 예시

Fresh init exact retry는 product ID를 미리 계산하지 않는다. 첫 `init`의 `runtime_identity`, `operator_id`, `account_refs`, `receipt_id`와 heads를 capture하고 두 번째 `init`에서 `SAME_AS`를 적용하며 database file write-set의 허용되지 않은 변화가 없음을 확인한다.

Recovery는 incident `show`가 공개한 `required_action_identity`를 manually authored approval request template에 채운 뒤 complete canonical body를 independent local operator signer subprocess에 전달한다. 반환된 detached signature만 v21 `approval issue`에 입력한다. Oracle은 action hash를 계산하지 않고 issue/show/recover 간 동일 reference, approval ACTIVE→CONSUMED, incident OPEN→RESOLVED와 final doctor READY를 독립적으로 요구한다. 미리 서명한 fixture로 dynamic action identity를 우회할 수 없다.

Operator signer port는 loopback 또는 scenario-local Unix socket만 사용하며 request schema는 `{domain,canonical_body}`이고 response는 v21 detached signature document다. Private test key는 signer child에만 주입되고 harness, v21 child와 v22 qualification process는 key bytes/path/env를 받지 않는다. Capability 부재, body completion 전 signing, domain mismatch 또는 signer와 product trust-anchor 불일치는 `BLOCKED` 또는 semantic FAIL로 기록한다. 이 port는 v22 release binding을 서명하지 않는다.

## Failure와 Mutation

| ID | Mutation | Expected result |
| --- | --- | --- |
| `import_product_model` | `src.v21.schemas` import 추가 | independence FAIL before product run |
| `direct_database_oracle` | SELECT로 head 비교 | source audit FAIL |
| `product_expected_builder` | fixture builder가 expected JSON 생성 | provenance FAIL |
| `trust_acceptance_pass` | 모든 oracle check를 self status로 대체 | mutation survives, suite FAIL |
| `stdout_key_reorder` | top-level order 변경 | parser FAIL |
| `exit_payload_mismatch` | process exit와 JSON exit 변경 | parser FAIL |
| `duplicate_json_key` | response에 중복 key | parser FAIL |
| `opaque_id_golden` | exact product-generated ID를 expectation에 삽입 | inventory validation FAIL |
| `lineage_swap` | 다른 incident의 action ID 사용 | semantic oracle FAIL |
| `stderr_secret` | fixed error에 canary secret 포함 | leak FAIL |

## CLI

```bash
uv run --frozen --offline python -m src.v22.cli prd01-acceptance
uv run --frozen --offline python -m src.v22.cli acceptance
```

PRD acceptance도 v21 command만 child로 실행한다. V22의 own response는 `v22.qualification-response.1`이며 check가 모두 통과하면 exit 0, product/contract mismatch는 exit 1, infrastructure block은 exit 2다.

## 완료 조건

- 모든 product invocation이 canonical v21 argv prefix와 child process를 사용한다.
- Static/runtime/provenance audit가 금지 import와 자기인증을 검출한다.
- 독립 parser가 raw bytes, response schema와 actual exit를 엄격하게 비교한다.
- Manual expectation이 opaque ID를 예측하지 않고 operator journey의 semantic consistency를 판정한다.
- Mutation 하나라도 oracle을 우회하면 PRD acceptance가 실패한다.

## 비목표

- Product Python API compatibility test
- SQLite table/schema 단위 assertion
- V21 canonicalizer/reducer의 독립 재구현
- Business expected value나 strategy result 계산
- V21 결함 수정
