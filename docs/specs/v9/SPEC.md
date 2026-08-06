# Trading Oracle v9 SPEC: Dashboard Read Contract
> **상태**: 📝 초안

v9 defines the read contract for a Trading Oracle dashboard. It does not build a screen, route, browser bundle, server API, database, cache, broker bridge, source fetcher, calibration job, portfolio mutation, or commit artifact. It joins five draft PRDs into one parser-ready contract for inputs, replay structure, risk surfaces, accessibility, and rollout observation.

Other SPEC payloads, v4 replay payloads, measurement artifacts, paper order artifacts, rollout systems, and telemetry sinks are adapter examples only. They can show how an adapter might fill the v9 shapes, but v9 must not wait for them and must not treat them as a gate.

## Local PRD Map

| PRD | Local document | Contract focus | Reads | Produces |
| --- | --- | --- | --- | --- |
| PRD 01 | [Dashboard Input Contract](prds/prd01-dashboard-input-contract.md) | Typed envelope, query result, version negotiation, adapter boundary, stale and degraded behavior, parser mutations. | Existing command output and future artifacts through adapters only. | `dashboard.event_envelope`, `dashboard.query_result`, and `dashboard.error`. |
| PRD 02 | [Replay Information Architecture](prds/prd02-replay-information-architecture.md) | Replay navigation, list, detail, timeline, filters, comparison, drilldown, and view model conditions. | PRD01 envelopes, query results, links, and adapter examples. | `dashboard.replay_view_model` plus replay fixtures and link mutation rules. |
| PRD 03 | [Risk Health Calibration Surfaces](prds/prd03-risk-health-calibration-surfaces.md) | Risk inbox, source health, confidence reliability, divergence, alerts, acknowledgement, and risk metrics. | PRD01 input state and PRD02 navigation context. | `dashboard.risk_health_view_model`, risk fixtures, and stale health failure rules. |
| PRD 04 | [Accessibility Responsive Errors](prds/prd04-accessibility-responsive-errors.md) | WCAG target, keyboard, focus, contrast, screen-reader semantics, CJK display, breakpoints, conditions, recovery. | PRD01 input state, PRD02 IA, PRD03 risk visibility, terminal information priority. | `dashboard.accessibility_responsive_view_model`, accessibility fixtures, and mutation probes. |
| PRD 05 | [Rollout Observability](prds/prd05-rollout-observability.md) | Rollout taxonomy, feature flag read model, audit, telemetry, SLOs, incidents, fallback, deprecation, privacy. | PRD01 through PRD04 read surfaces and usage events. | `dashboard.rollout_observability_view_model`, telemetry event schema, and guardrail fixtures. |

The table above is the only local PRD link table in this SPEC. A parser must fail if any v9 PRD row is missing, the row order changes, or a local PRD file link appears more than once in this file.

## Exact Evidence

| Evidence | Exact observation | Contract impact |
| --- | --- | --- |
| `docs/specs/v9/prds/prd01-dashboard-input-contract.md:18` to `:24` | PRD01 excludes UI, broker, portfolio mutation, source changes, config changes, and any other SPEC payload as a required upstream artifact. | v9 is a read contract and adapter boundary, not an implementation request. |
| `docs/specs/v9/prds/prd01-dashboard-input-contract.md:36` to `:110` | PRD01 fixes envelope identity, timestamp separation, freshness, quality, risk state, payload type, links, redaction, and secret exclusion. | Every downstream surface reads explicit state instead of inferring from shape, prose, Rich output, or nulls. |
| `docs/specs/v9/prds/prd01-dashboard-input-contract.md:111` to `:186` | PRD01 requires query results with pagination and version negotiation, and typed errors for unsupported or missing versions. | Lists never consume bare arrays, and version mismatch is a structured error. |
| `docs/specs/v9/prds/prd01-dashboard-input-contract.md:187` to `:207` | PRD01 says adapters are the only path from scripts, formatter records, or future artifacts into the contract. | Other SPEC payloads are adapter examples only. |
| `docs/specs/v9/prds/prd01-dashboard-input-contract.md:446` to `:457` | Stale, expired, degraded, blocked, and malformed cases stay explicit and cannot be counted as fresh or actionable. | Degraded input remains readable for audit but never becomes hidden success. |
| `docs/specs/v9/prds/prd01-dashboard-input-contract.md:459` to `:492` | Validation must parse JSON, check the happy recommendation payload, check unsupported version error, and run schema, pagination, version, stale, dirty, misleading, and malformed mutations. | Parser evidence starts at PRD01 and feeds every later surface. |
| `docs/specs/v9/prds/prd02-replay-information-architecture.md:49` to `:70` | PRD02 fixes replay nodes from `/dashboard` through replay lists, details, comparison, sources, and outcomes. | IA is a named read model, not route implementation. |
| `docs/specs/v9/prds/prd02-replay-information-architecture.md:71` to `:129` | PRD02 requires identity, decision, time, freshness, quality, outcome, links, header, decision summary, source summary, timeline, outcome summary, drilldown, and quality notes. | Replay preserves source to decision to outcome reading order. |
| `docs/specs/v9/prds/prd02-replay-information-architecture.md:338` to `:484` | PRD02 provides happy drilldown and missing outcome fixtures. | Happy replay and absent outcome are both required parser surfaces. |
| `docs/specs/v9/prds/prd02-replay-information-architecture.md:486` to `:524` | PRD02 requires JSON, link, condition, stale, dirty, misleading, malformed, and broken link checks. | Replay evidence must catch bad links and misleading missing outcome display. |
| `docs/specs/v9/prds/prd03-risk-health-calibration-surfaces.md:52` to `:70` | PRD03 fixes risk screens and says risk surfaces consume PRD01 envelopes or PRD02 links, not source files directly. | Risk surfaces sit after input and IA, not beside them. |
| `docs/specs/v9/prds/prd03-risk-health-calibration-surfaces.md:71` to `:127` | PRD03 fixes risk item fields, status rules, safe actions, severity taxonomy, and escalation rules. | Open risk remains visible and actionability stays explicit. |
| `docs/specs/v9/prds/prd03-risk-health-calibration-surfaces.md:128` to `:189` | PRD03 separates healthy, degraded, stale, expired, blocked, and missing source health, and separates hit rate from calibrated reliability. | Source health and confidence reliability cannot hide stale or small-sample risk. |
| `docs/specs/v9/prds/prd03-risk-health-calibration-surfaces.md:190` to `:259` | PRD03 keeps paper and live namespaces separate and says acknowledgement does not change risk facts. | Read actions never mutate broker, portfolio, source health, or severity. |
| `docs/specs/v9/prds/prd03-risk-health-calibration-surfaces.md:393` to `:445` | PRD03 provides happy open risk and stale health falsely normal failure fixtures. | Happy risk flow and critical stale labeling failure are required evidence. |
| `docs/specs/v9/prds/prd03-risk-health-calibration-surfaces.md:479` to `:514` | PRD03 requires JSON, view-state, acknowledgement, stale, dirty, misleading, malformed, and forbidden mutation probes. | Risk parser evidence must catch hidden open risk and unsafe acknowledgement effects. |
| `docs/specs/v9/prds/prd04-accessibility-responsive-errors.md:53` to `:90` | PRD04 fixes WCAG 2.2 AA, keyboard, focus, contrast, screen reader, target size, motion, language, and information priority. | Accessibility is part of the contract before visual work starts. |
| `docs/specs/v9/prds/prd04-accessibility-responsive-errors.md:91` to `:179` | PRD04 defines keyboard, focus, contrast, and semantics rules with failure codes. | The read surface must preserve risk and partial caveats for keyboard and assistive tech users. |
| `docs/specs/v9/prds/prd04-accessibility-responsive-errors.md:180` to `:289` | PRD04 fixes typed numeric source of truth, breakpoints, condition precedence, read-safe recovery, and reduced motion. | CJK, currency, partial, error, and recovery behavior cannot depend on display strings or motion. |
| `docs/specs/v9/prds/prd04-accessibility-responsive-errors.md:391` to `:570` | PRD04 provides keyboard, localization, misleading partial fixtures, parse matrix, fixture matrix, and mutation probes. | Accessibility evidence covers happy flow and degraded input failures. |
| `docs/specs/v9/prds/prd05-rollout-observability.md:54` to `:99` | PRD05 fixes rollout taxonomy, feature flag fields, promotion blockers, fallback, and unsupported reader behavior. | Exposure widening is tied to measured read safety, not a naked flag. |
| `docs/specs/v9/prds/prd05-rollout-observability.md:100` to `:164` | PRD05 fixes audit, telemetry dimensions, SLO thresholds, and guardrail rules. | Success requires typed latency, error, freshness, usage, fallback, privacy, and audit evidence. |
| `docs/specs/v9/prds/prd05-rollout-observability.md:165` to `:298` | PRD05 defines telemetry event schema and rollout observability view model. | Rollout observation is a read model with privacy checks, not a service definition. |
| `docs/specs/v9/prds/prd05-rollout-observability.md:299` to `:371` | PRD05 defines usage success journeys, happy canary, and error-rate rollback fixtures. | Success is an event sequence, and high typed error rate blocks promotion. |
| `docs/specs/v9/prds/prd05-rollout-observability.md:373` to `:491` | PRD05 fixes incidents, fallback, rollback, deprecation, privacy boundary, parse matrix, fixture matrix, and mutation probes. | Rollout evidence must catch stale false normal, privacy leaks, silent fallback, interruption misuse, and unsafe cutoff. |

## Integrated Flow

```text
input contract -> replay IA -> risk surfaces -> accessibility and recovery -> rollout observation
```

Input owns the envelope, query result, typed errors, version negotiation, and adapter boundary. Replay IA turns those envelopes and links into lists, details, timelines, filters, comparison, drilldown, and conditions. Risk surfaces read the same input and replay context to expose open risk, source health, reliability, divergence, alerts, and acknowledgement without changing facts. Accessibility and responsive rules keep the same identity, risk, freshness, quality, partial, missing, and error states visible or announced across devices and input methods. Rollout observation measures whether the read paths are safe enough to widen, hold, fallback, or roll back.

## Roles And Outcomes

| Role | Needs | v9 outcome |
| --- | --- | --- |
| Operator | See current recommendation context, open risk, stale source, partial outcome, and safe recovery before acting. | The dashboard read model keeps blocked, stale, degraded, missing, and error states visible. |
| Maintainer | Check whether adapter output, links, risk facts, accessibility state, and rollout telemetry obey the contract. | Parser and mutation evidence names the exact failing contract instead of relying on manual review alone. |
| Auditor | Reconstruct what was read, what was blocked, what was acknowledged, and why exposure changed. | Audit and telemetry events keep redacted subject refs, correlation IDs, reason codes, and guardrail snapshots. |
| Renderer implementer | Build a later UI from stable read models without redefining backend or data contracts. | The SPEC defines roles, screens, states, SLOs, success paths, and recovery rules but not components or routes. |

## Screens And Read Models

| Screen or surface | Source model | Required states | Primary checks |
| --- | --- | --- | --- |
| Dashboard entry | PRD01 query result and PRD02 navigation node | loading, empty, partial, error, fresh, degraded, blocked | No bare arrays, no stale previous result as current, no blocked item as actionable. |
| Replay list | PRD02 recommendation list | fresh, stale, expired, ok, degraded, blocked, matured, pending, missing | Identity first, timestamp separation, outcome missing is neutral. |
| Replay detail | PRD02 detail and timeline | ready, partial, error, missing timestamp, broken link | Timeline order is source observed, decision cutoff, decision emitted, outcome matured. |
| Replay comparison | PRD02 comparison | typed missing, stale, degraded, active filter | Values compare as typed fields, not display strings. |
| Source and outcome drilldown | PRD02 links plus PRD03 source health | ok, missing, stale, expired, blocked | Broken link is local error, detail remains readable when possible. |
| Risk inbox | PRD03 risk health view model | open, acknowledged, snoozed, resolved by source, blocked, stale | Open and stale risk remain counted even when collapsed or acknowledged. |
| Source health | PRD03 source health | healthy, degraded, stale, expired, blocked, missing | Counts stay separate, stale never counts as healthy. |
| Confidence reliability | PRD03 reliability surface | eligible, insufficient sample, legacy only, pending, malformed | Hit rate is not calibrated reliability without numeric probability and matured outcome. |
| Divergence | PRD03 paper and live divergence | partial, missing live reference, action required, critical | Paper and live namespaces stay separate and account IDs stay out. |
| Accessibility and recovery | PRD04 accessibility view model | compact, phone, tablet, desktop, wide, reduced motion, error | Priority 1 to 3 information stays visible or announced. |
| Rollout observation | PRD05 rollout observability view model | off, internal dogfood, canary 5, limited 25, default on, deprecated read only | Widening requires complete telemetry, audit, privacy, and SLO evidence. |

## State Contract

| State family | Allowed values | Rule |
| --- | --- | --- |
| Freshness | `fresh`, `stale`, `expired` | Stale and expired stay visible, but current use cannot count them as fresh. |
| Quality | `ok`, `degraded`, `blocked` | Failed checks cannot coexist with ok quality. |
| Risk state | `normal`, `watch`, `blocked` | Blocked can be read for audit but cannot become actionable guidance. |
| View condition | `loading`, `empty`, `partial`, `error` | Error overrides the affected node. Partial can keep readable sections with caveats. |
| Source health | `healthy`, `degraded`, `stale`, `expired`, `blocked`, `missing` | Healthy counts only records that pass healthy rules. |
| Risk item status | `open`, `acknowledged`, `snoozed`, `resolved_by_source`, `blocked`, `stale` | Acknowledgement proves seen state only and does not lower risk. |
| Severity | `info`, `watch`, `action_required`, `blocking`, `critical` | Stale health falsely normal is critical. |
| Rollout exposure | `off`, `internal_dogfood`, `canary_5`, `limited_25`, `default_on`, `deprecated_read_only` | Widening is blocked by missing telemetry, privacy violation, malformed events, stale false normal, or blocking risk. |

## SLO And Success Contract

| Guardrail | Canary threshold | Wider threshold | Rollback threshold |
| --- | --- | --- | --- |
| Query latency p95 | less than or equal to 2500 ms | less than or equal to 2000 ms | greater than 5000 ms for 2 consecutive windows |
| Detail latency p95 | less than or equal to 3000 ms | less than or equal to 2500 ms | greater than 6000 ms for 2 consecutive windows |
| Dashboard typed error rate | less than 1.00 percent | less than 0.50 percent | greater than or equal to 3.00 percent in one window |
| Malformed telemetry event rate | 0.00 percent | 0.00 percent | greater than 0.00 percent |
| Stale false normal count | 0 | 0 | greater than 0 |
| Privacy violation count | 0 | 0 | greater than 0 |
| Risk detail usage success | at least 95.00 percent | at least 98.00 percent | less than 90.00 percent for 2 consecutive windows |
| Fallback success | at least 99.00 percent when fallback runs | at least 99.50 percent when fallback runs | less than 95.00 percent in one window |
| Telemetry lag p95 | less than or equal to 120 seconds | less than or equal to 60 seconds | greater than 300 seconds for 2 consecutive windows |

Success is not a page load, time on page, green label, or visible chart. Success is a typed event sequence that proves the user reached the needed read surface, saw the caveat or risk, had a read-safe recovery or return path, and did not receive stale, partial, missing, blocked, or unsupported data as success.

Required usage success journeys are risk detail review, replay drilldown review, error recovery review, keyboard safe path, and fallback read path. Interrupted journeys cannot count as success unless they resume with a typed resume link and complete the required sequence.

## Happy Replay And Risk Flow

Happy replay starts with a PRD01 recommendation query result containing one typed recommendation envelope. The user selects `rec_20260806_005930_buy`, opens the replay detail, and reads timeline order as `source_observed`, `decision_input_cutoff`, `decision_emitted`, `outcome_matured`. Source and outcome drilldown targets must exist. The detail condition is ready, and missing outcome is false.

Missing outcome replay is also a valid readable path. The selected recommendation remains readable, detail condition is partial, outcome condition is missing, outcome metrics are null, missing outcome is visible, and the absence cannot be counted as win or loss.

Happy risk flow starts with open risk count 2 and selected item `risk_20260806_cash_floor_005930`. The selected item is open, severity is blocking, actions are read-safe, stale source remains visible, divergence remains visible, confidence condition is partial, open risk is not hidden, and current use is not marked actionable.

The risk failure path is stale health falsely normal. A source with `freshness_status="stale"`, `quality_status="degraded"`, `health_label="healthy"`, age above max age, and a summary that counts it as healthy must fail with `stale_health_falsely_normal` and critical severity.

## Degraded Input And Recovery

Degraded input is not an exception path and not success. It is a first-class read state. A stale source, missing outcome, partial adapter recovery, small confidence cohort, missing live reference, unsupported version, broken drilldown, or localization failure can leave unaffected sections readable, but the caveat must stay visible and announced.

Recovery actions are read-safe. They may open contract details, reset filters, return to a list, open source health, switch to audit view, open risk detail, open link health, or show typed raw values. They must not mutate recommendation, portfolio, broker, source, config, calibration, acknowledgement facts, source health, paper/live values, or risk severity unless a later PRD defines that mutation.

## Parser And Mutations

A v9 parser must read this SPEC and the five local PRDs, parse every fenced JSON block intended as JSON, verify draft status lines, verify the local PRD table, verify the PRD backlinks, and run deterministic checks against the fixtures and mutation probes.

Required parser checks:

| Check | Required pass condition | Failure code |
| --- | --- | --- |
| SPEC draft | One draft status line under the title, no release marker, no global numbered workflow label | `V9_SPEC_DRAFT_INVALID` |
| PRD table | Rows are exactly PRD01 through PRD05 in order, and each local PRD link appears once | `V9_PRD_TABLE_INVALID` |
| PRD backlinks | Each v9 PRD has exactly one parent SPEC backlink | `V9_PRD_BACKLINK_INVALID` |
| JSON fences | Every JSON fence intended as JSON parses | `V9_JSON_PARSE_ERROR` |
| Input contract | Happy recommendation and unsupported version error satisfy PRD01 rules | `V9_INPUT_CONTRACT_INVALID` |
| Replay IA | Sitemap, happy drilldown, missing outcome, conditions, and links satisfy PRD02 rules | `V9_REPLAY_CONTRACT_INVALID` |
| Risk surfaces | Risk view model, open risk, source health, confidence, divergence, alerts, and ack rules satisfy PRD03 rules | `V9_RISK_CONTRACT_INVALID` |
| Accessibility | WCAG target, keyboard path, focus, contrast, semantics, CJK, breakpoints, reduced motion, and recovery satisfy PRD04 rules | `V9_ACCESSIBILITY_CONTRACT_INVALID` |
| Rollout observation | Taxonomy, telemetry, SLOs, usage journeys, fallback, rollback, deprecation, and privacy satisfy PRD05 rules | `V9_ROLLOUT_CONTRACT_INVALID` |

Required mutations:

| Probe | Mutation | Expected result |
| --- | --- | --- |
| `schema` | Remove envelope identity, timestamp, payload type, risk item ID, severity, or telemetry schema name | fail with malformed contract code for the affected surface |
| `pagination` | Set `limit=0`, `has_more=true` with null cursor, or reuse cursor with changed sort | fail with malformed query or pagination code |
| `version` | Omit accepted versions or request unsupported envelope or payload version | fail with typed unsupported or missing version error |
| `stale` | Mark stale source as fresh or healthy, or widen rollout with stale false normal count above zero | fail with stale false normal or stale mislabeled fresh code |
| `dirty` | Parse Rich markup, emoji, localized prose, config, credential, account ID, raw IP, or untyped source as data | fail with adapter or privacy boundary violation |
| `misleading` | Count stale, blocked, degraded, partial, or missing data as fresh, ok, ready, win, loss, or actionable | fail with misleading summary code |
| `link` | Remove drilldown rel, target, return context, or explicit missing reason | fail with broken drilldown link code |
| `view_state` | Hide open risk, select missing risk without reason, move focus on partial arrival, or keep busy after final content | fail with malformed view model or focus code |
| `acknowledgement` | Snooze blocking risk, clear stale count by ack, or resolve divergence by ack only | fail with forbidden surface mutation code |
| `accessibility` | Hide priority 1 to 3, use color only, remove recovery, show missing as zero, or require motion for meaning | fail with accessibility failure code |
| `threshold` | Keep guardrail pass when typed error rate is `3.20` or required telemetry is missing | fail with rollback or guardrail unknown code |
| `fallback` | Invoke fallback without reason, typed path, or audit event | fail with silent fallback code |
| `deprecation` | Cut off an old reader while replacement has a critical incident | fail with unsafe deprecation cutoff code |

## Acceptance Criteria

| Criterion | Required result |
| --- | --- |
| Draft marker | This SPEC has the draft status directly under the title and no release marker. |
| PRD table | The local PRD table has exactly PRD01 through PRD05 in order and one link to each local PRD file. |
| Backlinks | Each v9 PRD has one parent SPEC backlink. |
| Independence | The flow is input, replay IA, risk surfaces, accessibility and recovery, rollout observation, with other SPEC payloads as adapter examples only. |
| Coverage | Roles, screens, states, SLOs, usage success, happy replay, missing outcome, happy risk, stale false normal, degraded input, parser checks, and mutations are defined. |
| Boundaries | No UI implementation, backend implementation, source refetch, broker call, portfolio mutation, calibration execution, or commit artifact is required. |
