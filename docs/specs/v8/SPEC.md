# Trading Oracle v8: Paper To Limited Automation Safety
> **상태**: ✅ 구현 완료

v8은 추천이 실제 주문으로 흐르지 않도록 paper ledger, operator approval dry-run, order reconciliation, risk controls, limited automation promotion을 하나의 안전 계약으로 묶는다. 이 SPEC은 v8 로컬 PRD 01부터 PRD 05까지만 종합한다. 다른 SPEC의 작성 상태, gate 결과, 구현 여부는 v8 판단 입력이 아니다.

## Local PRD Links

| PRD | PRD 문서 | 상태 | 계약 |
| --- | --- | --- | --- |
| PRD 01 | [Paper Portfolio Ledger](prds/prd01-paper-portfolio-ledger.md) | ✅ 구현 완료 | Paper 전용 recommendation, order, fill, cash, position, fee, corporate action, reconciliation을 append-only hash chain으로 남기고 live boundary를 차단한다. |
| PRD 02 | [Operator Approval Dry-run](prds/prd02-operator-approval-dry-run.md) | ✅ 구현 완료 | Proposed order, operator checklist, approval lifecycle, idempotency, quote freshness, broker dry-run response, permission을 정의하고 live submit을 금지한다. |
| PRD 03 | [Order State Reconciliation](prds/prd03-order-state-reconciliation.md) | ✅ 구현 완료 | Redacted broker truth와 내부 artifact를 비교해 order_status, partial fill, cash delta, position delta, retry recovery를 fail closed로 대사한다. |
| PRD 04 | [Risk Controls Kill Switch](prds/prd04-risk-controls-kill-switch.md) | ✅ 구현 완료 | Cash, position, concentration, correlation, market hours, stale quote, daily loss, acknowledgement, kill switch를 dry-run 전 안전 gate로 고정한다. |
| PRD 05 | [Limited Automation Promotion](prds/prd05-limited-automation-promotion.md) | ✅ 구현 완료 | Paper, dry-run, approval_required, limited_automation 승격과 cap, observation window, incident rollback, re-promotion 조건을 제한 자동화 계약으로 묶는다. |

The first cells of this table are exactly `PRD 01`, `PRD 02`, `PRD 03`, `PRD 04`, and `PRD 05`. Each local PRD file is linked exactly once in this SPEC.

## Exact Evidence

| Evidence | Exact observation | Contract impact |
| --- | --- | --- |
| `docs/specs/v8/prds/prd01-paper-portfolio-ledger.md:13` to `:18` | PRD 01 requires independent paper recommendation identity, virtual cash, position, order, fill, fee, corporate action, reconciliation, deterministic fill, hash chain, namespace split, and replay fixture. | v8 starts with paper artifacts that can be replayed without broker destination, credential fields, or `data/portfolio.json` mutation. |
| `docs/specs/v8/prds/prd01-paper-portfolio-ledger.md:59` | `paper_recommendation_id` is independent and does not require a previous recommendation ID in the seed. | Recommendation evidence can enter v8 without depending on an older live or recommendation identity contract. |
| `docs/specs/v8/prds/prd02-operator-approval-dry-run.md:38` to `:46` | Destination is limited to `broker_dry_run` or `internal_dry_run`; live order IDs, account fields, credentials, and portfolio mutation are forbidden. | Operator approval is permission to validate intent, not permission to create a real order. |
| `docs/specs/v8/prds/prd02-operator-approval-dry-run.md:89` to `:104` | Approval moves through `approval_status` values and terminal statuses cannot move to another terminal status. | A stale, rejected, expired, passed, or failed approval cannot be revived by replay wording. |
| `docs/specs/v8/prds/prd03-order-state-reconciliation.md:74` to `:88` | Order lifecycle uses `order_status`; `unknown` is terminal unless later same-reference broker truth proves a status. | Lost or contradictory broker truth blocks reorder and blocks portfolio mutation. |
| `docs/specs/v8/prds/prd03-order-state-reconciliation.md:152` to `:159` | Partial BUY of 4 shares at `10000.00` has gross notional `40000.00`, fee `40.00`, cash delta `-40040.00`, and remaining quantity `6`. | Reconciliation arithmetic is decimal string accounting, not float portfolio mutation. |
| `docs/specs/v8/prds/prd04-risk-controls-kill-switch.md:74` to `:91` | Risk matrix covers cash, cash floor, position, max positions, single-name weight, sector, pair correlation, market hours, stale quote, daily loss, risk acknowledgement, and kill switch. | Risk controls are the safety gate before dry-run, and acknowledgement can only handle warning-only cases. |
| `docs/specs/v8/prds/prd04-risk-controls-kill-switch.md:182` to `:212` | Kill switch can be manual or automatic; unreadable or unverifiable switch evidence behaves as a global active switch. | Safety fails closed when the switch stream is corrupt, missing, or contradictory. |
| `docs/specs/v8/prds/prd05-limited-automation-promotion.md:47` to `:59` | Promotion lifecycle has `paper`, `dry_run`, `approval_required`, `limited_automation`, and `rolled_back`; no status can skip a prior status and no unlimited status exists. | Limited automation is a capped dry-run automation path, not live execution. |
| `docs/specs/v8/prds/prd05-limited-automation-promotion.md:120` to `:129` | Critical, high, and medium incidents roll back automatically, may activate kill switch, and never submit or cancel a real order or mutate portfolio cash or position. | Incident handling terminates unsafe automation first and records evidence after stopping scope inside the SLA. |

## Users And Success

| User | Need | v8 success |
| --- | --- | --- |
| Investor using Trading Oracle | See recommendation follow-through without hidden live execution. | Paper fills, dry-run results, risk decisions, and promotion status are visible as redacted artifacts, with no broker live submit. |
| Operator approving orders | Review intent, quote freshness, risk, and dry-run result before any irreversible action. | Checklist, approval, risk, and dry-run artifacts agree on ticker, side, quantity, quote, permission, idempotency key, and forbidden field absence. |
| Maintainer auditing safety | Reconstruct what happened after interruption or incident. | Append-only records, source hashes, idempotency indexes, mutation probes, and rollback records make stale, dirty, malformed, duplicate, or misleading output fail before side effects. |

## Safety Architecture

```text
paper -> approval -> order -> risk -> promotion
```

The PRD order above is the document synthesis order. Runtime safety is stricter: risk evidence can block before approval, again before dry-run, and during limited automation. No layer grants permission to create a broker live order, store raw account identifiers, read credentials, write `data/portfolio.json`, or treat a dry-run response as a fill.

PRD 01 owns the paper evidence root. PRD 02 turns a paper order into a human-reviewed dry-run intent. PRD 03 reconciles redacted broker truth and internal artifacts without sending a new order. PRD 04 can stop the flow at any point through risk blocks or kill switch coverage. PRD 05 can reduce manual friction only inside fixed caps, fixed eligible scope, and automatic rollback rules.

## Operating Stages

| Stage | Allowed output | Required guard | Forbidden result |
| --- | --- | --- | --- |
| `paper` | Paper recommendation, order, fill, ledger replay, reconciliation. | Paper namespace, deterministic IDs, hash chain, decimal arithmetic, live boundary proof. | Broker destination, credential key, raw account field, `data/portfolio.json` write. |
| `approval` | Proposed order, checklist, approval, rejection, expiry, dry-run request, dry-run response. | Fresh quote, separate approver, permission snapshot, idempotency, no forbidden fields. | Live submit, revived expired approval, duplicate dry-run response. |
| `order` | Redacted broker truth, fill fragments, reconciliation, portfolio delta artifact. | Same ref hash, fresh truth, matching quantities, decimal cash and position deltas. | Reorder under `unknown`, raw broker order ID, live portfolio mutation. |
| `risk` | `allowed`, `blocked`, `requires_ack`, or `kill_switch_active` decision. | Cash, position, concentration, correlation, market hours, quote, daily loss, acknowledgement, kill switch evidence. | Ack overriding a blocker, stale quote marked safe, unreadable switch ignored. |
| `promotion` | Limited automation decision, automation request, incident, rollback, re-promotion review. | Eligible scope, caps, observation windows, independent approval, inactive kill switch proof. | Unlimited cap, market order automation, margin, short, live order, portfolio mutation. |

## Happy Limited Automation Trace

An eligible `005930` limit BUY starts as paper evidence with `pord_v8_401fb2527af3008c3980` and `prec_v8_1df70a8e23b72f301477`. Operator approval produces `aprop_v8_f5e78bd2e22f115b7e08`, validates a fresh quote, and reaches `dry_run_passed` with `live_submission: false`, `would_accept: true`, and `portfolio_mutated: false`.

Risk checks then allow the same intent only when required cash is `100100.00` or below available cash after floor, market is open, quote is fresh, daily loss is above the halt threshold, and kill switch coverage is inactive. Promotion may move from `approval_required` to `limited_automation` only when the observation window has at least 20 paper sessions, 30 paper orders, 10 approved dry-run attempts, 5 approval_required sessions, and zero live contamination, hash break, false risk allow, or incident counts.

The limited automation fixture caps the path to KR regular session, symbols `005930` and `000660`, limit orders, per order notional `100000.00` KRW, total daily notional `300000.00` KRW, concurrent requests `1`, traffic share `5.00` percent, and duration `5` trading sessions. The next destination remains `broker_dry_run`; real order creation and portfolio mutation stay false.

## Kill Switch Termination

Kill switch termination means terminating unsafe automation flow, not deleting history. An active, unreadable, or unverifiable switch makes risk behave as covered by an active global switch. It blocks dry-run requests, requires reset authority where applicable, and keeps real order creation and portfolio mutation false.

Reset appends reset request, review, and inactive records. It requires root cause, fresh quote evidence, market calendar evidence, daily loss evidence when applicable, recomputed hash chain, forbidden field absence, cooldown, and independent reviewers. Missing, stale, self-approved, or hash-mismatched reset input keeps the prior active switch in force.

## Executable Acceptance

```bash
uv run python -m src.v8.cli spec-acceptance
```

이 명령은 SPEC과 로컬 PRD 5개만 읽어 canonical JSON 보고서를 출력한다. 문서 변이는 메모리에서만 수행하며 broker, credential, live portfolio, paper artifact를 읽거나 쓰지 않는다.

## Link, JSON, And Mutation QA

Authoring QA for this SPEC must include these checks.

| Check | Required result |
| --- | --- |
| PRD table sequence | First cells are exactly `PRD 01`, `PRD 02`, `PRD 03`, `PRD 04`, and `PRD 05` in order. |
| Forward link count | Each relative v8 PRD link appears exactly once in this SPEC. |
| Backlink count | Each v8 PRD contains exactly one Markdown link target `../SPEC.md`. |
| Implementation marker | This SPEC and PRD 01 to PRD 05 use the exact `✅ 구현 완료` status marker, and every Local PRD row has the same status. |
| JSON parse | Every fenced `json` block in this SPEC and PRD 01 to PRD 05 parses as JSON. |
| Lifecycle field names | PRD 02 to PRD 05 use their explicit lifecycle fields and reject forbidden generic lifecycle field names in artifacts. |
| Mutation coverage | PRD 01 to PRD 05 cover malformed JSON, stale or dirty input, misleading success, forbidden credential or live ID fields, duplicate or conflicting idempotency, hash mismatch, interruption replay, and live order mutation attempts. |
| No live side effect | No v8 PRD or this SPEC requires broker live submit, raw credential access, live account field storage, real order creation, or `data/portfolio.json` mutation. |

## Acceptance Criteria

- The SPEC and PRD 01 to PRD 05 use the exact `✅ 구현 완료` status marker, and the local PRD table status column matches it.
- The local PRD table has rows whose first cells are exactly `PRD 01`, `PRD 02`, `PRD 03`, `PRD 04`, and `PRD 05`.
- Each local PRD file is linked exactly once with the `prds/<filename>` form.
- The paper -> approval -> order -> risk -> promotion synthesis is independent from other SPEC status or gate results.
- Safety architecture states that approval, reconciliation, risk, and promotion never create a real order or mutate `data/portfolio.json`.
- Operating stages define allowed output, required guard, and forbidden result for paper, approval, order, risk, and promotion.
- Users and success criteria cover investor visibility, operator review, and maintainer audit.
- Happy limited automation remains capped, dry-run only, and terminates through rollback or kill switch on incident.
- Link, JSON, and mutation QA requirements cover table sequence, forward links, backlinks, JSON parsing, mutation probes, and live side effect bans.
