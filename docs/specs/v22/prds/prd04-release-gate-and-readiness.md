# PRD: v22 PRD 04 Final Release Gate, Packaging, Documentation And Readiness
> **상태**: 📋 구현 예정
> 상위 SPEC: [v22 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-black-box-harness-and-oracle.md)의 independent transcript/oracle verdict
- [PRD 02](prd02-runtime-containment.md)의 environment/network/write/process evidence
- [PRD 03](prd03-failure-and-upgrade-matrix.md)의 crash/corruption/upgrade verdict
- [v21 public CLI](../../v21/SPEC.md)와 [v21 operator runbook](../../v21/prds/prd04-operator-journey-acceptance.md)

## 목표

실제 운영자가 clean environment에서 paper product를 설치·초기화·실행·조사·복구할 수 있음을 끝까지 검증한다. `qualify`는 package/docs/source/lock identity와 evidence를 unsigned qualification artifact로 묶고 qualification verdict를 내며, 외부 release signing 뒤 `attest`만 최종 release `PASS|FAIL|BLOCKED`를 결정한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v22/release_gate.py` | mandatory gate aggregation과 qualification verdict |
| `src/v22/attestation.py` | release anchor/domain/signature 검증과 final release verdict |
| `src/v22/operator_journey.py` | public CLI end-to-end journey driver |
| `src/v22/test_signers.py` | acceptance-only bounded operator/release signer subprocess IPC |
| `src/v22/packaging.py` | clean package/import/executable inventory checks |
| `src/v22/docs_check.py` | documented command/link/runbook readiness |
| `src/v22/reporting.py` | canonical evidence/readiness artifacts |
| `src/v22/cli.py` | `qualify`, `attest`와 bounded acceptance entrypoint |

## Canonical Release Orchestration

```bash
uv run --frozen --offline python -m src.v22.cli qualify --output <artifact-root>
# external release signer: domain + completed qualification-binding.json -> qualification-binding.sig
uv run --frozen --offline python -m src.v22.cli attest --artifact-root <artifact-root> --release-trust-anchor <release-public-key.json> --signature <qualification-binding.sig>
```

`qualify`는 repository의 frozen v22 scenario inventory를 사용하고 지정한 새 output directory에 unsigned artifact를 만든다. Qualification PASS는 exit 0, evaluated product FAIL은 exit 1, infrastructure/capability BLOCKED는 exit 2다. `attest`는 artifact root, 별도 release trust anchor와 detached signature만 입력받아 final release PASS/FAIL/BLOCKED를 같은 exit 0/1/2에 mapping한다. 두 command stdout는 각각 `v22.qualification-response.1`, `v22.attestation-response.1` canonical JSON 한 줄이고 expected FAIL/BLOCKED의 stderr는 비운다. Internal v22 defect만 exit 3과 redacted fixed diagnostic을 사용한다.

`uv run --frozen --offline python -m src.v22.cli acceptance`는 release command가 아니다. Bounded test orchestration으로 두 clean `qualify`, local test release signer, 각각의 `attest`를 순서대로 별도 process에서 실행하며 suite 12분과 PRD 02 budget을 지킨다. Test release private key는 release signer child에만 주입되고 acceptance parent와 모든 v21/v22 Python process는 key bytes/path/env를 받지 않는다. 두 clean qualification readiness payload hash와 두 attestation 결과가 같아야 한다. Acceptance parent가 qualification과 attestation 판정을 합치거나 signer private key를 읽지 않는다.

## End-to-End Operator Journey

다음 command를 각각 canonical v21 subprocess로 호출한다. 각 `<id>`는 바로 앞 public response에서만 가져온다.

1. Missing state `doctor`: exit 3 `NOT_INITIALIZED`, path write 0
2. `init`: designated temp DB, config와 public trust anchor로 성공
3. Exact `init` retry: same receipt/heads, extra semantic write 0
4. Ready `doctor`와 repeated `status`: READY, read-only bytes 동일
5. Normal KR paper `run`: terminal public receipt와 source heads
6. `events` pagination과 `report`: stable refs, stdout/export canonical bytes equality
7. Close/reopen 후 `status/report`: pre-close public projection/hash equality
8. Recorded safety cause `run`: approval 대기 없이 containment, OPEN incident 공개
9. `incidents list/show`: exact recovery mode/action identity를 public output에서 획득
10. Approval 없는/unresolved `recover`: exit 7, all relevant public heads/write-set 불변
11. Incident output으로 complete canonical approval body를 만든 뒤 independent local operator signer subprocess/port가 반환한 detached signature로 `approval issue/show`: ACTIVE, no private-key access
12. Exact `recover`: v20 authorization, approval consume, incident RESOLVED
13. Final `doctor/status/events/report`: READY/CONSUMED/RESOLVED와 heads 상호 일치
14. 별도 root approval issue→signed revoke→use: REVOKED, source action 0
15. 별도 root named crash→new process `status`→`RESUME_SESSION`: uninterrupted baseline relation

운영자 여정 중 SQLite, report JSON 또는 source package를 직접 편집하지 않는다. Approval request의 manually authored immutable body에서 action identity 자리만 public incident output으로 채운 뒤 완성된 canonical body를 signer에 보낸다. Operator private test key는 signer subprocess에만 존재하고 v21/v22 Python process의 argv/env/file/address space에 노출되지 않는다. Signer port/capability 부재는 BLOCKED다. Operator signer/domain/trust anchor는 release signer/domain/trust anchor와 별개이며 어떤 key/signature도 재사용하지 않는다.

## Packaging Gate

Packaging은 repository source tree 우연성에 기대지 않음을 검사한다.

- Lockfile와 `pyproject.toml` bytes hash를 manifest에 binding한다.
- Clean temp checkout/package view에서 `uv sync --frozen --offline`이 성공하고 모든 v21 product child와 v22 command가 `uv run --frozen --offline`로 실행되어야 한다. Cache miss나 network download가 필요하면 qualification은 BLOCKED다.
- Installed/isolated environment에서 canonical `uv run --frozen --offline python -m src.v21.cli --help`와 v22 `qualify`/`attest`/`acceptance` entrypoint를 찾을 수 있어야 한다.
- Package inventory에 `src.v21`, required migrations/static fixtures와 public docs가 포함되고 developer real HOME/config에 의존하지 않는다.
- V22 package는 v16~v21을 import dependency로 선언하거나 module import하지 않는다. Runtime product 실행은 executable artifact boundary다.
- Untracked local file, editable external path, current CWD 밖 source와 build cache가 result에 필요하면 FAIL이다.
- Wheel/sdist를 release한다면 둘의 source/spec/lock manifest identity와 installed CLI behavior가 같아야 한다. 이 repository가 해당 artifact type을 선언하지 않았다면 `NOT_APPLICABLE`이며 mandatory clean-installed CLI check는 남는다.

Dependency를 gate 중 network로 설치하지 않는다. Release candidate가 required dependency artifact/cache를 제공하지 않아 clean offline setup이 불가능하면 BLOCKED다.

## Documentation Gate

다음 문서 사실을 static link/command inventory와 실제 `--help`/journey로 교차 검증한다.

- V21 public command와 option syntax, response schema와 exit 0~8
- Fresh init, pre-run doctor, normal run, status/events/report 조사 순서
- Incident show, approval issue/show/revoke, recover와 private key 비취급
- Integrity exit 6에서 mutation 중단 및 automatic SQL/JSON repair 금지
- Explicit `--as-of`, request ID, paper-only/offline/temp-root 제약
- Report가 state/recovery input이 아니며 SQLite가 product durable truth라는 경고
- V22 `PASS|FAIL|BLOCKED`, evidence capability와 kernel isolation 비보장
- Canonical release command와 artifact 위치/검증 절차

모든 local Markdown link가 존재하고 SPEC↔각 PRD backlink가 해소되어야 한다. Documented command는 parser help와 일치해야 하며 실행 불가능하거나 존재하지 않는 remediation은 FAIL이다.

## Gate Inventory와 판정

| Gate | Mandatory evidence | Failure class |
| --- | --- | --- |
| `independence` | static/runtime/provenance audit | 위반 FAIL |
| `public_contract` | schema/exit/stderr/redaction mutation | mismatch FAIL |
| `operator_journey` | complete command lineage | mismatch FAIL |
| `containment` | env/network/write/process capability | violation FAIL, unavailable BLOCKED |
| `durability` | crash/restart baseline relation | mismatch FAIL |
| `corruption` | fail-closed and no-repair bytes | mismatch FAIL |
| `schema_upgrade` | prior/current/future matrix | missing fixture/capability BLOCKED, behavior mismatch FAIL |
| `packaging` | frozen clean offline executable | missing candidate/cache BLOCKED, package defect FAIL |
| `documentation` | links/help/runbook checks | mismatch FAIL |
| `determinism` | two clean normalized hashes | mismatch FAIL |
| `qualification_binding` | unsigned artifact hashes와 candidate identity | mismatch FAIL |
| `attestation` | separate release anchor/domain/signature verification | missing signer/input BLOCKED, invalid FAIL |

Aggregation 우선순위는 FAIL > BLOCKED > PASS다. 하나의 product FAIL이 있는 상태에서 infrastructure block도 있으면 final FAIL이며 blocked 목록도 보존한다. Mandatory gate를 skip/waive하는 option은 없다.

## Owning-Spec Routing

각 failed check는 `owner_spec`, public command, error/exit actual/expected, minimal transcript ref와 external evidence hash를 기록한다.

| Failure area | Owner |
| --- | --- |
| Config/path/data health | v16 |
| SQLite migration/event/projection durability | v17 |
| Measurement report semantics | v18 |
| Session/resume/risk/fill/close | v19 |
| Adapter/lifecycle/kill/authorization | v20 |
| Public CLI/incident/approval/recovery/redaction | v21 |
| Harness/containment/evidence/gate defect | v22 |

V22 report는 owner를 지정할 뿐 product source를 patch하거나 pass threshold를 낮추지 않는다.

## Qualification Readiness Report

`readiness-report.json` schema `v22.readiness-report.1` 필수 field:

- qualification contract/version과 `qualification_verdict`
- evaluated git tree/source archive identity, `pyproject.toml`, lockfile, v21/v22 SPEC hashes
- platform/capability matrix와 required evidence status
- gate별 PASS/FAIL/BLOCKED, owner spec와 evidence refs
- operator journey step/invocation/transcript hashes
- crash/corruption/upgrade/mutation inventory와 counts
- package/docs/link/command inventory hashes
- network attempts, outside writes, leak matches, timeouts와 surviving descendants counts
- deterministic run A/B normalized payload hashes
- artifact inventory inputs; manifest/binding은 이 report가 완성된 뒤 생성되므로 self-reference 없음, release signer fingerprint/status도 포함하지 않음

Dynamic absolute path, PID, wall-clock completion time, username, host, raw signature/key/account/provider payload는 없다. `evaluated_as_of`가 필요하면 scenario inventory의 fixed release epoch를 사용한다.

`readiness-report.json`은 qualification `PASS|FAIL|BLOCKED`만 소유하며 release authorization이나 final release verdict를 표현하지 않는다. Release trust anchor/signature가 아직 없는 것은 qualify 결과를 BLOCKED로 바꾸지 않는다.

## Release Trust Anchor와 Signature

Release trust-anchor document schema는 `v22.release-trust-anchor.1`이고 exact field는 `{schema_version,algorithm,public_key,key_id}`다. Algorithm은 Ed25519, public key는 32-byte base64url-no-padding이며 `key_id = sha256("trading-oracle:v22:release-trust-anchor:1" || raw_public_key)`다. 이 key ID와 bytes는 v21 `v21.trust-anchor.1`, operator ID와 approval database metadata에 사용할 수 없다.

Release signature document schema는 `v22.release-detached-signature.1`이고 exact field는 `{schema_version,key_id,algorithm,domain,binding_hash,signature}`다. Domain은 exact `trading-oracle:v22:release-attestation:1`; `binding_hash`는 completed `qualification-binding.json` bytes의 SHA-256다. `attest`는 anchor key ID, domain, binding hash와 Ed25519 signature를 모두 검증한 뒤에만 final release PASS를 허용한다.

Top-level acceptance의 operator/release private test keys는 서로 다른 bounded test key pair다. 각 key는 해당 signer child가 inherited read-only descriptor로만 받고 child 종료 시 폐기한다. Acceptance parent, `qualify`, `attest`, v21 child, artifact root와 transcript에는 private key bytes/path가 없다. Signer child 시작 또는 IPC isolation capability가 없으면 acceptance는 BLOCKED다.

## Hash-Bound Artifact Manifest

`artifact-manifest.json` schema `v22.artifact-manifest.1`은 `qualification-report.json`, `write-set.json`, `process-network-evidence.json`, `readiness-report.json`과 evaluated source/lock/spec bytes의 path label, media/schema type, byte length와 SHA-256를 path 순으로 가진다. Manifest 자신, binding, signature와 attestation은 inventory에 넣지 않는다. Cycle을 피하기 위해 readiness report는 manifest body hash를 포함하지 않고 `qualification-binding.json`이 readiness와 manifest exact hashes, release candidate identity를 묶는다.

Binding 순서:

1. Evidence/report artifacts canonical write
2. Artifact manifest canonical write
3. `qualification-binding.json`에 candidate, readiness, manifest hash 기록
4. External release signer가 `trading-oracle:v22:release-attestation:1` domain과 exact binding bytes에 detached signature 생성
5. `attest`가 v21 operator anchor와 다른 `--release-trust-anchor`로 signature를 검증하고 `attestation.json`에 algorithm, release signer fingerprint, domain, binding/signature hash와 final `release_verdict` 기록

Private release key는 v22 option/env/file read 대상이 아니다. `attest`는 qualification artifacts를 수정하거나 readiness verdict를 재계산하지 않는다. Signature/anchor가 없으면 final release verdict는 BLOCKED다. Artifact/signature byte mutation, 다른 candidate report swap, operator key 재사용과 release signer mismatch는 FAIL이다. `attestation.json`이 final release verdict의 유일한 owner다.

## Readiness Artifact Set

```text
qualification-report.json
write-set.json
process-network-evidence.json
readiness-report.json
artifact-manifest.json
qualification-binding.json
qualification-binding.sig
attestation.json
```

각 파일은 temp output directory의 new file로 fsync+atomic rename하고 overwrite하지 않는다. Partial generation은 PASS를 만들지 않는다. `qualify` console response는 qualification verdict, `attest` response는 final release verdict와 artifact hashes만 포함하며 raw transcript는 노출하지 않는다.

`qualify`는 앞의 첫 여섯 파일만 만들며 `qualification-binding.sig`와 `attestation.json`을 만들지 않는다. External release signer가 `.sig`를 만든 뒤 `attest`가 마지막 파일만 추가한다. `attest` 실행 전 artifact root에 `attestation.json`이 있거나 qualification file이 바뀌면 FAIL이다.

## Failure와 Mutation

| ID | Mutation | Required result |
| --- | --- | --- |
| `journey_skip_recovery` | mandatory recovery step 제거 | gate FAIL |
| `self_certified_pass` | v21 acceptance PASS만 evidence | independence gate FAIL |
| `packaging_missing_migration` | installed artifact asset 누락 | packaging FAIL |
| `lockfile_drift` | lock bytes 변경 후 old binding | hash binding FAIL |
| `broken_doc_link` | PRD/local link 변경 | docs FAIL |
| `help_doc_drift` | option name 불일치 | docs FAIL |
| `mandatory_gate_waive` | containment을 skip | final BLOCKED/FAIL, PASS 금지 |
| `report_byte_flip` | readiness artifact 1 byte 변경 | manifest/attestation FAIL |
| `candidate_swap` | 다른 tree의 report 재사용 | binding FAIL |
| `signature_wrong_key` | unknown signer signature | attestation FAIL |
| `signature_missing` | `attest` signature/anchor 없음 | final release BLOCKED; readiness qualification verdict 불변 |
| `operator_release_key_reuse` | v21 operator key/domain으로 binding 서명 | attestation FAIL |
| `nondeterministic_path_pid` | temp path/PID가 payload에 포함 | run A/B hash FAIL |
| `fail_plus_blocked` | product mismatch와 capability 부재 동시 | final FAIL, blocked details 유지 |

## Release Criteria

Release candidate는 다음을 모두 만족할 때만 PASS다.

- Readiness qualification gate 전부 PASS, failed/blocked/skipped 0
- Operator journey와 secondary journeys complete
- Network attempt, credential/private-key access, outside write, process survivor와 leak 0
- Crash/restart, corruption/no-repair, supported upgrade와 future fail-closed matrix PASS
- Clean offline installed executable과 docs/runbook PASS
- Two-run normalized payload byte identity PASS
- Manifest/binding과 별도 release-domain signature verification PASS

FAIL artifact는 재실행으로 덮지 않고 owner spec 수정 후 새 candidate identity로 qualification한다. BLOCKED artifact는 missing infrastructure/input을 명시하며 release할 수 없다.

## CLI

```bash
uv run --frozen --offline python -m src.v22.cli prd04-acceptance
uv run --frozen --offline python -m src.v22.cli acceptance
```

## 완료 조건

- Public v21 output만 연결한 complete operator journey가 normal, incident, approval, recovery와 restart를 포함한다.
- Packaging과 docs가 clean offline operator 사용을 실제 executable과 교차 검증한다.
- Readiness가 qualification PASS/FAIL/BLOCKED를 자기인증 없이 결정하고 failure를 owning spec으로 route한다.
- Readiness/evidence/source/lock/package identity가 qualification binding과 separate external release signature에 binding되고 attestation만 final release verdict를 소유한다.
- Final release mode에서 unsigned, unavailable 또는 skipped mandatory evidence는 PASS가 아니다.

## 비목표

- Deployment service, installer 제작과 release upload/publish
- Live broker/provider smoke test와 credential custody
- Web UI, daemon, monitoring backend와 on-call automation
- Performance/load/soak benchmark
- 새 strategy/vendor/business rule 또는 v16~v21 bug fix
