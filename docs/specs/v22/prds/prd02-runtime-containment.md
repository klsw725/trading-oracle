# PRD: v22 PRD 02 Temporary Runtime And Outer Containment
> **상태**: 📋 구현 예정
> 상위 SPEC: [v22 SPEC](../SPEC.md)

## 의존성

- [PRD 01](prd01-black-box-harness-and-oracle.md)의 invocation/transcript와 independence 계약
- [v21 SPEC](../../v21/SPEC.md)의 path, redaction, offline, paper-only 경계
- macOS/Linux의 portable process group, filesystem과 local socket facilities

## 목표

각 qualification scenario를 clean temp HOME/state/config에서 실행하고 environment, network, file write, descendant process와 시간을 외부에서 통제·관측한다. 일반 CI가 제공하지 않는 kernel isolation을 과장하지 않고, 어떤 증거가 enforced/observed/unavailable인지 readiness qualification verdict에 반영한다.

## 구현 표면

| 경로 | 책임 |
| --- | --- |
| `src/v22/sandbox.py` | Temp root, environment allowlist와 write-set inventory |
| `src/v22/processes.py` | Process group, timeout, output·resource bound와 reap |
| `src/v22/boundaries.py` | Network trap, filesystem 경계와 platform capability evidence |

## Temp Root Layout

```text
<scenario>/home
<scenario>/work
<scenario>/config
<scenario>/state
<scenario>/exports
<scenario>/traps
<scenario>/evidence
```

Scenario 시작 시 root는 새로 생성되고 mode 0700이다. Fixture source bytes는 `config/` 또는 `work/inputs/`에 copy하며 repository fixture를 직접 product input으로 넘기지 않는다. Database는 `state/paper.sqlite3`, export는 `exports/`만 사용한다. Scenario 종료 후 evidence hash를 확정하고 temp root를 제거하며 cleanup failure도 FAIL이다.

## Environment Allowlist

Child environment는 empty map에서 다음만 구성한다.

| Key | 값/목적 |
| --- | --- |
| `HOME` | scenario `home/` |
| `PATH` | runner가 검증한 `uv`/system binary 경로 |
| `TMPDIR`, `TMP`, `TEMP` | scenario `work/tmp/` |
| `LANG`, `LC_ALL` | `C.UTF-8` 또는 platform verified UTF-8 locale |
| `TZ` | `UTC` |
| `PYTHONHASHSEED` | `0` |
| `PYTHONDONTWRITEBYTECODE` | `1` |
| `TRADING_ORACLE_ACCEPTANCE_ROOT` | scenario root, v21 documented acceptance mode만 |
| `TRADING_ORACLE_V21_FAULT_CHECKPOINT` | v21 PRD 04 enum; crash scenario에서만 |
| operator signer endpoint | scenario-local signer port label; approval/revoke step에서만 |

`PYTHONPATH`, `PYTHONHOME`, proxy variables, cloud metadata, CI token, SSH agent, keychain, broker/provider/LLM credential와 `*_TOKEN|*_SECRET|*_PASSWORD|*_API_KEY`는 전달하지 않는다. Parent에 canary credential env를 심고 child response/file/trap에서 부재를 확인한다.

## Offline Network Trap

Mandatory network evidence는 product process tree에 적용되는 외부 deny-all monitor와 append-only attempt ledger다. Monitor는 DNS와 outbound/loopback connect를 차단·기록하되, harness가 명시적으로 연 operator signer local endpoint만 step-scoped allowlist로 분리 기록한다. Product 내부 monkeypatch나 credential 부재는 증거가 아니다. Platform별 monitor command/version, 적용된 process identity, deny policy hash와 ledger hash를 capability evidence에 남긴다.

Network attempt 0건이어야 PASS다. Deny-all이 차단했더라도 attempt가 있으면 FAIL이다. 일반 CI에서 portable하고 완전한 syscall 관측을 제공한다고 주장하지 않는다. 외부 monitor가 process tree에 적용됐음과 ledger 완전성을 증명할 capability가 없으면 `NETWORK_EVIDENCE_UNAVAILABLE`, 전체 BLOCKED다. Namespace/firewall/socket audit 중 어느 구현을 쓰든 같은 capability contract를 충족해야 한다.

## Write-Set Inventory

Suite 시작 전 repository root, real HOME의 selected sentinel, `data/portfolio.json`과 scenario root를 `lstat` 기반으로 inventory한다. Entry는 relative label, type, symlink target, mode, size와 regular-file SHA-256를 가진다. Symlink는 따라가지 않는다.

허용 write class:

| Root | 허용 |
| --- | --- |
| `state/` | 해당 mutating scenario의 SQLite/WAL/SHM와 atomic temp |
| `exports/` | 명시한 report/readiness target만 |
| `work/tmp/` | interpreter/uv temp, 종료 후 잔존 금지 |
| `evidence/` | v22 parent만 작성, product child 쓰기 금지 |
| repository/real HOME | 쓰기·삭제·mode·symlink 변화 0 |

새 path, 삭제, content/mode/type 변경을 모두 diff한다. SQLite physical bytes는 mutation command에서 허용된다. Read-only command는 main DB와 WAL의 frame count/size를 증가시키지 않고 호출 전후 logical heads/report가 같아야 하며 non-SQLite write는 0건이어야 한다. SHM와 lock bytes는 SQLite의 volatile coordination state라 byte invariance에서 제외하지만 새 durable state로 해석하지 않는다. Expected failure별 allowed write-set은 PRD 03 matrix가 명시하며 미등록 write는 FAIL이다.

Ordinary CI의 repository 밖 전체 filesystem을 완전 감시했다고 주장하지 않는다. Product에 제공한 path와 inherited descriptors를 제한하고, repository/real HOME/temp boundary의 mandatory sentinel/inventory 증거를 수집한다. 더 강한 audit facility 부재는 capability에 명시한다.

## File Descriptor와 Input Boundary

Child stdin은 명시한 bytes 또는 `/dev/null`, stdout/stderr만 pipe다. Inherited file descriptor는 0~2와 runner가 명시한 trap descriptor 외 close한다. Product input file은 root 내부 regular file이며 symlink/hardlink escape fixture를 별도 거부 scenario로 검증한다. Named pipe, device와 socket을 config/database/export path로 허용하지 않는다.

## Wall-Clock Timeout와 Process Group Kill

Child는 POSIX 새 session으로 시작한다. Monotonic deadline은 invocation마다 20초, crash/upgrade 30초다. Suite deadline은 720초이며 남은 시간이 invocation budget보다 작으면 새 step을 시작하지 않고 BLOCKED가 아니라 deterministic suite timeout FAIL을 낸다.

Timeout 절차:

1. Process group에 `SIGTERM`
2. stdout/stderr를 drain하면서 최대 2초 wait
3. Group 생존 시 `SIGKILL`
4. 최대 2초 reap
5. group existence, known child tree와 trap connection 종료 확인

Parent 자체 cancellation도 같은 cleanup을 수행한다. Exit 전 모든 child를 reap한다. Signal unsupported platform은 v22 지원 대상이 아니다. Timeout, orphan, zombie, background daemon/thread가 process 종료를 막는 경우 FAIL이다.

## Output와 Resource Bounds

- stdout/stderr stream 각각 1 MiB
- input file 64 KiB, signature 4 KiB라는 v21 public limit 보존
- Scenario file count 2,000, total temp bytes 256 MiB
- Process descendants 16개 초과 즉시 FAIL
- Polling/sleep 기반 business wait 금지; explicit `as_of`만 바꿔 호출

한도 초과 시 process group을 kill하고 partial evidence hash와 reason을 남긴다. Truncated output을 parse해 PASS하지 않는다.

## Platform Evidence

`platform-evidence`는 OS family/release, filesystem capability, process-group support, trap method와 각 capability의 `ENFORCED|OBSERVED|UNAVAILABLE`를 기록한다. macOS와 Linux 모두 같은 semantic checks를 요구하되 구현 명령은 다를 수 있다. OS별 optional evidence가 달라도 normalized verdict/report는 같아야 한다.

`ENFORCED`는 runner가 operation을 차단하고 event를 기록함, `OBSERVED`는 before/after로 확인함, `UNAVAILABLE`은 증명하지 못함이다. Mandatory network, process kill, repository/real HOME/temp write-set 중 하나라도 unavailable이면 release BLOCKED다.

## Failure와 Mutation

| ID | Mutation | Required result |
| --- | --- | --- |
| `inherit_api_key` | parent env에 canary API key | child env/output/files에 0건 |
| `home_write` | product가 `$HOME/.cache` 생성 | observed outside allowed set, FAIL |
| `repository_write` | tracked fixture 1 byte 변경 | hash diff, FAIL |
| `portfolio_delete_recreate` | same bytes로 path 교체 | inode/type inventory diff, FAIL |
| `symlink_escape` | DB/export가 root 밖을 가리킴 | v21 exit 2, target 불변 |
| `dns_attempt` | resolver 호출 | trap attempt와 FAIL |
| `socket_attempt` | localhost/external connect | trap attempt와 FAIL |
| `network_trap_disabled` | mandatory trap unavailable | BLOCKED |
| `stdout_flood` | 1 MiB 초과 | group kill, FAIL |
| `timeout_child` | deadline 초과 | TERM/KILL/reap evidence, FAIL |
| `orphan_grandchild` | detached sleeper 생성 | survivor detection, FAIL |
| `readonly_wal_growth` | status가 main DB 또는 WAL frame/size 증가 | write-set FAIL |
| `cleanup_leak` | temp process/file 잔존 | FAIL |

## CLI

```bash
uv run --frozen --offline python -m src.v22.cli prd02-acceptance
uv run --frozen --offline python -m src.v22.cli acceptance
```

## 완료 조건

- 모든 scenario가 새 temp HOME/config/state/export root와 allowlisted environment를 사용한다.
- Network attempt, inherited secret, temp 밖 write와 descendant process를 외부 evidence로 판정한다.
- Timeout이 process group 전체를 bounded TERM→KILL→reap하고 output/resource limit을 지킨다.
- macOS/Linux capability가 명시되고 kernel isolation을 주장하지 않는다.
- Mandatory containment evidence 부재는 BLOCKED이며 PASS로 축소되지 않는다.

## 비목표

- 악성 product에 대한 security sandbox
- Container/VM/firewall 의무화와 kernel syscall 완전성 인증
- Windows 지원
- Live endpoint smoke test와 credential validation
- Daemon lifecycle 또는 deployment isolation
