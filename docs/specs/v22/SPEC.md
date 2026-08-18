# Trading Oracle v22 SPEC: Independent Black-Box Release Qualification And Outer Containment
> **상태**: 📋 구현 예정

v22는 [v21](../v21/SPEC.md)의 공개 운영자 CLI를 설치 가능한 paper product로 간주하고, 제품 내부를 신뢰하지 않는 별도 process에서 release qualification과 release attestation을 수행한다. 검증기는 clean temporary environment에서 오직 `uv run --frozen --offline python -m src.v21.cli ...`만 호출해 운영자 여정, failure semantics, durability와 외부 경계를 관측한다. v22는 v16~v21 business logic을 고치거나 대신 판정하지 않는 terminal roadmap stage다.

## 0. 구현 완결성 계약

- Canonical release 명령은 `uv run --frozen --offline python -m src.v22.cli qualify --output DIR`와 `uv run --frozen --offline python -m src.v22.cli attest --artifact-root DIR --release-trust-anchor PATH --signature PATH`다. `qualify`는 unsigned qualification artifact와 `qualification-binding.json`을 만들고 qualification verdict만 판정한다. 외부 release signer가 binding을 서명한 뒤 `attest`가 최종 release verdict를 판정한다.
- `uv run --frozen --offline python -m src.v22.cli acceptance`는 위 두 명령과 그 사이의 두 local test signer subprocess를 실제로 구동하는 bounded local acceptance다. Release 절차를 하나의 in-process command로 축약하거나 `qualify`가 final release verdict를 내리게 하지 않는다.
- Harness가 product를 실행하는 유일한 경로는 child process의 `uv run --frozen --offline python -m src.v21.cli <command>`다. `src.v16`~`src.v21`의 Python symbol import, direct SQLite query, repository 호출과 in-process `main()` 호출은 금지한다.
- V22는 product reducer, canonicalizer, repository, migration helper, fixture builder, error registry 또는 expected-result builder를 import·복사·호출하지 않는다.
- V22는 Python 표준 라이브러리만으로 문서화된 `v21.cli-response.1`을 독립 parse하고 manually authored semantic expectation과 비교한다. Product output으로 expected output을 다시 계산하지 않는다.
- Input fixture는 원인 bytes와 public test trust anchors만 제공한다. Dynamic approval signature는 완성된 canonical body를 받은 독립 local operator signer subprocess가 생성하고, release signature는 완성된 `qualification-binding.json`을 받은 별도 release signer subprocess가 생성한다. Expected ID/hash, run result, kill scope, approval/recovery outcome, report hash와 미리 서명한 dynamic body를 fixture에 넣지 않는다.
- 각 scenario는 새 temp root, temp `HOME`, 명시 config/state/export root, 최소 environment allowlist와 offline trap을 사용한다. Repository, real home, credential, live broker와 temp root 밖은 관측 대상일 뿐 쓰기 대상이 아니다.
- Wall-clock timeout은 scenario와 suite에 고정한다. Timeout 시 child process group 전체를 단계적으로 종료하고 descendant가 남지 않았음을 확인한다.
- macOS와 Linux 일반 CI에서 가능한 portable process·file·socket 증거를 수집한다. Kernel namespace, mandatory access control 또는 완전한 syscall isolation을 제공했다고 주장하지 않는다. 필수 증거를 수집할 수 없으면 `BLOCKED`이지 `PASS`가 아니다.
- Crash, restart, file corruption과 schema upgrade는 공개 v21 CLI의 다음 호출에서 관측되는 response, exit, files와 process 상태만으로 판정한다. Database 내부를 query해 성공을 증명하지 않는다.
- V22에서 발견한 business mismatch는 해당 v16~v21 owning spec의 failure로 귀속한다. V22는 product state나 business code를 repair·rewrite하지 않는다.
- Qualification은 두 clean run에서 normalized evidence와 readiness payload가 byte-identical해야 하며 suite hard deadline 안에 끝난다.

## Local PRD Map

| PRD | Local document | Implementation owner | Produces |
| --- | --- | --- | --- |
| PRD 01 | [Subprocess-Only Black-Box Harness And Independent Oracle](prds/prd01-black-box-harness-and-oracle.md) | `src/v22/harness.py`, `src/v22/oracle.py`, `src/v22/schema.py` | subprocess transcript와 independent semantic verdict |
| PRD 02 | [Runtime Containment](prds/prd02-runtime-containment.md) | `src/v22/sandbox.py`, `src/v22/processes.py`, `src/v22/boundaries.py` | temp runtime, network/write/process containment evidence |
| PRD 03 | [Failure, Restart, Corruption And Upgrade Matrix](prds/prd03-failure-and-upgrade-matrix.md) | `src/v22/scenarios.py`, `src/v22/fault_driver.py`, `src/v22/mutations.py` | deterministic failure·upgrade qualification matrix |
| PRD 04 | [Release Gate And Readiness](prds/prd04-release-gate-and-readiness.md) | `src/v22/release_gate.py`, `src/v22/attestation.py`, `src/v22/packaging.py`, `src/v22/reporting.py`, `src/v22/cli.py` | unsigned qualification artifacts와 별도 attestation final verdict |

PRD 01→04 순서로 구현한다. PRD 01은 verifier independence, PRD 02는 outer containment, PRD 03은 durability/failure evidence, PRD 04는 operator journey와 release decision만 소유한다.

## 1. 신뢰 경계와 금지 의존성

V22가 신뢰하는 것은 repository에 version-controlled된 v21 public 문서 계약, manually authored v22 expectation, Python 표준 라이브러리 semantics와 OS가 반환한 process/file 관측값뿐이다. V21이 stdout에 `PASS`라고 쓴 사실은 증거 하나일 뿐 release verdict가 아니다.

금지 import prefix는 `src.v16`~`src.v21`과 그 alias다. Static source scan, isolated import audit hook, child invocation ledger가 모두 금지를 확인한다. 다음은 자기인증이므로 release `FAIL`이다.

- V21 response model, canonical JSON 함수 또는 error enum import
- Product SQLite schema/repository로 row·head·migration을 직접 읽기
- Product reducer로 restart 전후 expected state 계산
- Product fixture builder로 expected output·ID·hash 생성
- V21 acceptance 결과를 v22 verdict로 그대로 승격
- 이전 golden stdout 전체를 expected response로 복사

V22는 `json`, `hashlib`, `subprocess`, `tempfile`, `pathlib`, `os`, `signal`, `socket`, `sqlite3`를 사용할 수 있다. `sqlite3`는 독립적으로 authored upgrade/corruption input file을 준비하거나 file-level header/integrity fixture를 만드는 데만 사용하고 product 성공 판정 시 table/query를 읽지 않는다.

## 2. 공개 관측 계약

각 child invocation은 command argv, allowlisted environment key 이름, cwd label, stdin hash, start/end monotonic offset, timeout phase, raw stdout/stderr bytes hash, exit/signal, descendant termination 결과와 before/after write-set을 기록한다. Product child argv에는 `uv run --frozen --offline`이 반드시 포함되고 dependency resolution의 network fallback은 금지된다. Absolute temp path, PID와 wall-clock timestamp는 final deterministic report에서 stable label로 normalize한다.

Independent parser는 다음만 허용한다.

- stdout UTF-8, JSON object 한 개, trailing newline 정확히 하나
- top-level key 순서와 exact set: `schema_version,command,request_id,status,exit_code,data,error,meta`
- `schema_version=v21.cli-response.1`, documented enum/type와 actual process exit equality
- expected failure의 empty stderr, exit 1의 redacted fixed diagnostic 예외
- safe identifier/hash/timestamp lexical shape와 금지 token leak 0건

Command별 `data`는 v21 문서에 기재된 required field와 semantic relation만 독립 검사한다. Undocumented internal field를 요구하거나 product model로 deserialize하지 않는다.

## 3. Manual Semantic Oracle

Expectation inventory는 scenario ID별 input facts, command sequence, allowed exit/status/error code, required/forbidden relation, expected write class와 owner version을 사람이 명시한다. Oracle은 다음 relation을 직접 비교한다.

- Exact retry의 public IDs, receipt와 logical heads가 같고 허용 write-set이 증가하지 않음
- Changed request body가 exit 4이며 이전 public state/report hash가 같음
- Read-only command 전후 write-set과 stable public snapshot이 같음
- Incident output의 action identity만 다음 approval request input으로 전달됨
- Approval 없거나 unresolved root cause면 source state가 변하지 않음
- Recovery 후 incident `RESOLVED`, approval `CONSUMED`, doctor `READY`가 각각 공개 조회에서 합의함
- Restart 결과와 uninterrupted baseline의 public report/head 관계가 같음

Oracle은 opaque product ID의 구체 hash 값을 예측하지 않는다. Prefix/lexical form, 같은 입력에서의 equality, 다른 semantic input에서의 inequality, cross-response reference consistency를 검증한다.

## 4. Clean Runtime와 Outer Containment

각 scenario root는 `home/`, `work/`, `config/`, `state/`, `exports/`, `traps/`, `evidence/`로 고정한다. Product database, config, public trust anchor와 request files는 이 root 아래에만 materialize한다. Real `HOME`, repository tracked files와 `data/portfolio.json`은 suite 전후 path/type/mode/size/content hash inventory가 같아야 한다.

환경은 `HOME`, `PATH`, locale, timezone, Python hash seed, temp variables와 v21이 문서화한 acceptance-root/fault key, v22가 문서화한 local operator-signer endpoint만 전달한다. Proxy, credential, token, cloud, broker/provider와 user Python injection 변수는 제거한다. Offline zero-attempt는 capability가 확인된 외부 deny-all network monitor와 append-only attempt ledger로 증명한다. 일반 CI에서 portable complete syscall observation을 주장하지 않으며 monitor/ledger capability가 없으면 `BLOCKED`, attempt가 하나라도 있으면 `FAIL`이다.

Containment evidence 수준은 `ENFORCED`, `OBSERVED`, `UNAVAILABLE`로 기록한다. Mandatory probe가 `UNAVAILABLE`이면 전체 `BLOCKED`; trap이 실제 attempt를 잡거나 write/process leak를 발견하면 `FAIL`이다.

## 5. Bounded Process 계약

- 단일 CLI 기본 timeout 20초, crash/upgrade scenario 30초, 전체 suite 12분으로 고정한다.
- Child는 새 process session/group leader로 시작한다.
- Deadline은 monotonic clock으로 측정한다. Timeout 후 group에 graceful termination, 2초 bounded wait, force kill, 2초 reap를 수행한다.
- Parent는 stdout/stderr pipe를 동시에 drain하고 각 stream 1 MiB를 넘으면 output-limit failure로 group을 kill한다.
- 종료 뒤 process group, known descendants와 trap listener를 확인한다. Survivor, zombie 미회수 또는 background child는 `FAIL`이다.
- Timeout은 expected business failure가 아니라 `QUALIFICATION_TIMEOUT`, release `FAIL`이다. Runner infrastructure 자체가 child를 시작하지 못하면 `BLOCKED`다.

## 6. Qualification Journeys

필수 journey는 서로 독립 clean roots에서 실행한다.

1. Fresh install: `doctor` not initialized→`init`→ready `doctor`→`status`
2. Normal operation: `run`→`status`→`events`→`report` stdout/export→close/reopen 조회
3. Safety and recovery: incident trigger→approval 없는 blocked recovery→completed canonical body를 independent local operator signer에 전달→detached signature로 approval issue/show→recover→final doctor/report
4. Interrupted operation: named crash boundary→new process status→public `recover --mode RESUME_SESSION`→baseline comparison
5. Approval revoke: issue→show→signed revoke→rejected use
6. Corruption: copied state mutation→doctor integrity failure→run/recover blocked, automatic repair 없음
7. Upgrade: initial release는 v20 global head `006`, 후속 release는 last shipped v21 head `008` fixture copy→`init`/doctor public upgrade→restart→idempotent second open

각 step의 다음 input은 prior public output, manually authored source fixture 또는 documented constant에서만 온다. SQLite 조회나 product function 결과를 끼워 넣지 않는다.

Operator signer는 loopback/Unix local port의 별도 process이며 request마다 complete canonical v21 approval/revoke body bytes와 expected v21 domain을 받아 detached signature document만 반환한다. Operator private test key는 그 process memory/전용 unreadable fixture descriptor에만 존재하고 v21 또는 v22 Python process의 argv, env, filesystem input과 address space에 들어가지 않는다. Signer port/capability 부재는 qualification `BLOCKED`다. 이 signer와 v21 operator trust anchor/domain은 release signer와 v22 release trust anchor/domain과 서로 다르며 key나 signature를 재사용하지 않는다.

## 7. Qualification과 Release 판정

| Verdict | 의미 |
| --- | --- |
| `PASS` | 모든 mandatory scenario/check/mutation이 실행되어 expected semantics와 containment를 충족함 |
| `FAIL` | Product response/state/file/process/network behavior가 계약과 다르거나 mandatory mutation이 결함을 검출하지 못함 |
| `BLOCKED` | Product를 평가할 수 없는 qualification infrastructure/capability/input 부재; product success로 간주하지 않음 |

`readiness-report.json`이 소유하는 `qualification_verdict`의 `PASS`는 fail 0, blocked 0, skipped mandatory 0을 요구한다. Expected product failure를 정확히 반환한 scenario check는 PASS다. Flaky retry로 verdict를 덮지 않으며 scenario 자동 retry는 없다. 이 값은 release 허가가 아니다. `attestation.json`만 별도 release signature 검증을 포함한 최종 `release_verdict`를 소유한다.

## 8. Final Artifact Set

`qualify --output DIR`은 성공 여부와 무관하게 지정한 새 artifact root에 다음 unsigned artifact를 원자적으로 생성한다.

- `qualification-report.json`: scenario/check result와 normalized evidence refs; top-level qualification verdict 없음
- `write-set.json`: root별 before/after file inventory와 allowed/observed classification
- `process-network-evidence.json`: invocation, timeout/kill, descendant와 network trap 결과
- `readiness-report.json`: release identity, dependency/docs/package checks와 qualification verdict
- `artifact-manifest.json`: 위 artifact와 evaluated source/lock/spec bytes SHA-256
- `qualification-binding.json`: candidate identity, readiness와 manifest exact hash

외부 release signer는 domain separator `trading-oracle:v22:release-attestation:1`과 completed `qualification-binding.json` bytes를 서명해 `qualification-binding.sig`를 만든다. `attest`는 v21 operator trust anchor와 분리된 `--release-trust-anchor` public key로 이를 검증하고 `attestation.json`을 원자 생성한다. Release private key는 v22가 읽지 않는다. Signature/anchor capability 또는 input 부재는 final release `BLOCKED`, invalid signature/domain/binding은 `FAIL`이다.

따라서 complete artifact root는 위 여섯 unsigned 파일에 external `qualification-binding.sig`와 `attest`가 만든 `attestation.json`을 더한 정확히 여덟 파일이다. Readiness report 자체를 직접 서명하는 별도 artifact는 만들지 않는다.

## 9. Failure와 Mutation 계약

| Probe | Mutation | Required result |
| --- | --- | --- |
| `forbidden_product_import` | oracle이 v21 canonicalizer/reducer import | static/runtime independence FAIL |
| `self_report_trust` | v21 status만 PASS로 바꿈, exit/state 불일치 | independent oracle FAIL |
| `response_schema_drift` | key/type/order/exit mismatch | FAIL |
| `expected_golden_from_product` | expected fixture provenance가 product builder | FAIL |
| `env_secret_inheritance` | parent에 credential/token 주입 | child env에서 부재, leak 0 |
| `network_connect_attempt` | DNS/socket/connect probe | trap evidence와 FAIL |
| `outside_write` | temp root 밖 create/modify/delete | FAIL |
| `timeout_descendant` | child가 sleeping descendant 생성 | group kill/reap, scenario FAIL |
| `crash_restart_duplicate` | commit boundary crash 후 resume | baseline-equivalent public heads, duplicate 0 |
| `corruption_auto_repair` | corrupted copied DB에 doctor/run | exit 6, write/repair 0 |
| `upgrade_non_idempotent` | upgraded DB 재초기화 | same public schema/head, extra migration effect 0 |
| `report_signature_swap` | report 또는 manifest 1 byte 변경 | `attest` verification FAIL |
| `mandatory_probe_skip` | required OS evidence 누락 | BLOCKED, PASS 금지 |

## 10. 의존성과 비목표

의존성은 Python 표준 라이브러리, `uv`, documented v21 executable, manually authored v22 fixtures/expectations와 local OS process/file facilities다. V22는 v21 package에 대한 Python dependency를 선언하지 않고 executable artifact만 평가한다.

다음은 비목표다.

- V16~v21 business logic, migration, error message 또는 recovery rule 수정
- Live broker, credential, external acknowledgement와 network smoke test
- Web UI, TUI, daemon, deployment service, scheduler와 multi-host failover
- 새 strategy, parameter, vendor, metric, risk·fill·promotion rule
- Kernel-grade sandbox, container security 인증 또는 악성 code 격리 보장
- Performance/load/soak benchmark와 platform별 packaging installer 추가
- Private signing key 생성·보관·사용

## 11. Acceptance Criteria

- 정확히 v21 public CLI만 subprocess로 호출하고 금지 import/direct DB oracle가 정적·동적으로 차단된다.
- Manual independent oracle이 schema, exit, semantic relation과 mutation을 product code 없이 판정한다.
- Temp HOME/state/config, env allowlist, offline trap, write-set과 process-group timeout evidence가 macOS/Linux에서 수집된다.
- Fresh install부터 normal run, incident, approval, recovery와 final report까지 public output만 연결해 완료한다.
- Crash/restart, corruption, schema upgrade와 file boundary matrix가 deterministic하고 mandatory skip이 없다.
- Packaging/docs/source/lock identity와 모든 evidence artifact가 `qualification-binding.json`, 별도 release domain/signature와 `attestation.json`에 binding된다.
- `PASS|FAIL|BLOCKED`가 구별되고 v21 자기 보고나 capability 부재가 PASS로 승격되지 않는다.
- 두 clean qualification의 normalized report가 byte-identical하고 전체 suite가 12분 내 종료한다.
- Top-level acceptance가 bounded test operator signer와 별도 test release signer를 사용해 `qualify`→external sign→`attest`를 모두 실행하되 private key를 v21/v22 Python process에 노출하지 않는다.
