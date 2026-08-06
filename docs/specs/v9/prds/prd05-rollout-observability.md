# PRD: v9 PRD 05 rollout observability
> **상태**: 📝 초안
> **SPEC 참조**: [v9 SPEC](../SPEC.md)

## 문제

v9 PRD 01은 dashboard 입력 계약을 정의했고, v9 PRD 02는 replay 정보 구조를 정의했으며, v9 PRD 03은 risk health 표면을 정의했고, v9 PRD 04는 접근성과 오류 상태를 정의했다. 하지만 이 계약을 운영자에게 안전하게 넓히는 기준, 관측해야 할 신호, rollback 기준, 감사 접근, privacy 경계는 아직 분리되어 있지 않다.

Trading Oracle dashboard는 투자 판단, stale source, blocked risk, partial outcome을 다룬다. 새 표면이 일부 사용자에게만 켜져도 오류율, freshness, fallback, 사용 성공, 감사 접근이 보이지 않으면 안전한 확장인지 알 수 없다. 특히 canary에서 error rate가 상승했는데 기본 화면처럼 유지되면 운영자는 위험 차단을 놓칠 수 있다.

이 PRD는 feature rollout, audit access, latency, error, freshness telemetry, usage success metrics, incident fallback, deprecation, privacy boundary, SLO, telemetry events를 정의한다. 화면 구현, 서버 구현, source 수집, broker 호출, portfolio 변경, config 변경은 만들지 않는다.

## 목표

1. rollout stage와 stage 전환 기준을 값으로 고정한다.
2. canary, limited, default rollout에서 관측해야 할 latency, error, freshness, usage success SLO를 정의한다.
3. 감사 접근과 operator event를 권한, reason, redaction 경계와 함께 정의한다.
4. incident, fallback, rollback, deprecation 경로를 안전하게 정의한다.
5. privacy boundary가 telemetry와 audit log 전체에 적용되게 한다.
6. happy canary fixture와 error-rate rollback failure fixture를 제공한다.
7. JSON, threshold, stale, privacy, interruption mutation으로 문서 계약을 검증할 수 있게 한다.

## 범위 밖

1. 화면 component, route, CSS, animation, browser build는 다루지 않는다.
2. backend API, database schema, queue, cache, deployment system, feature flag service는 구현하지 않는다.
3. 추천, replay, risk, performance, portfolio 값을 재계산하지 않는다.
4. `scripts/**`, `src/**`, `data/**`, `config.yaml`, `README.md` 변경을 요구하지 않는다.
5. Rich terminal markup, localized prose, account identifier, credential, raw config를 telemetry나 audit data로 파싱하지 않는다.
6. 작업 기록, plan, state, staging, commit은 이 문서 산출물에 포함하지 않는다.

## 선행 입력

| 입력 | 이 PRD에서 쓰는 부분 | 경계 |
| --- | --- | --- |
| v9 PRD 01 dashboard input contract | envelope, query result, freshness, quality, risk state, error envelope, adapter boundary | 입력 상태와 error code만 소비한다. |
| v9 PRD 02 replay information architecture | navigation node, drilldown, conditions, missing outcome | usage success event의 대상만 소비한다. |
| v9 PRD 03 risk health calibration surfaces | risk inbox, source health, severity, acknowledgement, stale behavior | risk와 actionability 의미만 소비한다. |
| v9 PRD 04 accessibility responsive errors | keyboard path, focus, recovery, localization, partial and error states | 사용 성공과 recovery 관측 기준만 소비한다. |
| future rollout or telemetry system | stage, flag, event sink examples | 필수 선행 산출물이 아니다. |

## 용어

| 용어 | 의미 |
| --- | --- |
| rollout stage | 기능 노출 범위와 guardrail을 함께 가진 상태 |
| canary | 제한된 운영자나 세션에만 노출하는 관측 stage |
| guardrail | stage 승격, 정지, rollback을 결정하는 측정 기준 |
| telemetry event | latency, error, freshness, usage, fallback, privacy 상태를 기록하는 typed event |
| audit access | 운영자가 어떤 surface와 risk를 열람했는지 남기는 redacted event |
| usage success | 운영자가 의도한 안전한 읽기 흐름을 끝냈다는 측정 결과 |
| incident fallback | incident 동안 더 안전한 read path나 이전 계약으로 이동하는 정책 |
| deprecation | 오래된 reader나 payload version을 끄기 전에 관측, 공지, 차단하는 정책 |

## Rollout stage taxonomy

Rollout stage는 feature flag 값 하나가 아니라 audience, allowed surfaces, SLO gate, fallback behavior를 묶은 계약이다.

| Stage | Audience | Allowed surfaces | Entry criteria | Exit criteria | Fallback |
| --- | --- | --- | --- | --- | --- |
| `off` | none | none | default safe state | manual enable request exists | existing terminal or current command output |
| `internal_dogfood` | maintainers only | read-only dashboard contract samples | PRD parser and privacy checks pass | no blocking contract errors for 2 trading sessions | turn flag off |
| `canary_5` | up to 5 percent of eligible operator sessions | PRD 01 through PRD 04 read surfaces | dogfood exit met, telemetry sink healthy | all canary SLOs met for 5 trading sessions | rollback to `internal_dogfood` or `off` |
| `limited_25` | up to 25 percent of eligible sessions | same as canary plus wider replay browsing | canary exit met, no privacy incident | SLOs met for 10 trading sessions | rollback to `canary_5` |
| `default_on` | all eligible sessions | all read surfaces covered by v9 | limited exit met and deprecation notice active for old readers | stable operations review accepts evidence | fallback to `limited_25` or command output |
| `deprecated_read_only` | users still on old reader or unsupported version | read-only old reader with warning | replacement has `default_on` evidence | usage below deprecation threshold for 20 trading sessions | old reader remains read-only until cutoff |

Stage rules:

1. A stage cannot widen audience when required telemetry is missing.
2. `canary_5` and wider stages must emit rollout, latency, error, freshness, usage success, fallback, and audit events.
3. `risk_state.blocking=true`, stale health falsely normal, privacy violation, or malformed event schema blocks promotion.
4. Fallback must preserve read access to audit and risk explanations. It must not make blocked action look safe.
5. Rollback narrows exposure and records a reason. It does not delete incident, telemetry, or audit evidence.

## Feature flag contract

The feature flag read model describes rollout state. It is not a runtime service definition.

Required fields:

| Field | Rule |
| --- | --- |
| `flag_id` | Stable identifier for the dashboard rollout flag. |
| `stage` | One of the stage taxonomy values. |
| `audience_rule` | Percentage, role, market, or session scope with no raw account ID. |
| `enabled_surfaces` | List of v9 surface identifiers allowed in the stage. |
| `guardrails` | SLO and threshold names that must pass before widening. |
| `fallback_policy` | Target stage or read path when guardrail fails. |
| `privacy_mode` | `redacted`, `aggregate_only`, or `blocked`. |
| `updated_at` | ISO 8601 timestamp with timezone. |
| `updated_by_ref` | Redacted actor or automation reference. |

Flag rules:

1. `audience_rule` must not contain account number, broker credential, OAuth token, raw IP address, or device fingerprint.
2. `enabled_surfaces` must name read surfaces only.
3. A stage change requires a telemetry snapshot reference and a reason code.
4. Unsupported reader versions move to typed unsupported version error or deprecated read-only, not silent success.

## Audit access contract

Audit access proves what was read and why. It does not prove investment correctness.

| Access event | Required fields | Privacy rule |
| --- | --- | --- |
| `surface_viewed` | event ID, stage, surface, subject ID, condition, timestamp | subject ID is allowed. Raw account data is forbidden. |
| `risk_detail_opened` | risk item ID, severity, actionability, reason code, timestamp | reason codes only. No free text with secrets. |
| `replay_drilldown_opened` | node, subject ID, linked evidence health, timestamp | link target IDs are typed and redacted. |
| `recovery_action_seen` | error code, action ID, enabled state, timestamp | action result is read-safe only. |
| `acknowledgement_requested` | ack request ID, risk version, reason code, timestamp | follows PRD 03 acknowledgement boundary. |
| `rollout_stage_changed` | from stage, to stage, guardrail snapshot, actor ref, timestamp | actor ref is redacted. |

Audit rules:

1. Audit access can be sampled for aggregate usage, but risk, error, privacy, and rollout change events are not sampled.
2. Free-text comments are not required for rollout telemetry. If present, they are redacted before storage.
3. Audit events must include `correlation_id` when available so incident review can connect surface, error, and fallback.
4. A missing audit event for a rollout stage change blocks widening until reconciled.

## Telemetry dimensions

Telemetry must separate latency, error, freshness, and usage success. One healthy dimension cannot hide failure in another.

| Dimension | Metrics | Required behavior |
| --- | --- | --- |
| Latency | `query_latency_ms_p50`, `query_latency_ms_p95`, `detail_latency_ms_p95`, `telemetry_lag_seconds_p95` | Measured per surface and stage. Null means not measured. |
| Error | `error_rate`, `blocked_error_rate`, `malformed_event_rate`, `unsupported_version_rate` | Error rate excludes operator cancellations but includes typed dashboard errors. |
| Freshness | `fresh_count`, `stale_count`, `expired_count`, `stale_false_normal_count`, `max_source_age_seconds` | Stale and expired never count as fresh. |
| Usage success | `risk_detail_success_rate`, `replay_drilldown_success_rate`, `recovery_path_success_rate`, `keyboard_path_success_rate` | Success means the expected safe event sequence occurred. |
| Fallback | `fallback_invocation_count`, `fallback_success_rate`, `rollback_count`, `time_to_fallback_seconds_p95` | Fallback is visible and typed. It is not a silent redirect. |
| Privacy | `privacy_violation_count`, `redaction_failure_count`, `forbidden_field_count` | Any count greater than zero blocks widening. |

Metric rules:

1. Stage summary must include event counts and denominator definitions.
2. Percentages use decimal strings with a named denominator.
3. A metric cannot be marked healthy when its sample count is below `minimum_sample_count`.
4. Freshness metrics use PRD 01 freshness and PRD 03 source health labels.
5. Usage success metrics cannot be inferred from page load alone. They require the expected event sequence.

## SLO and threshold contract

SLOs are rollout guardrails. They do not claim the investing model is correct.

| SLO | Canary threshold | Wider threshold | Rollback threshold |
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

Threshold rules:

1. Canary promotion requires all canary thresholds to pass and no privacy violation.
2. Error-rate rollback triggers immediately when typed dashboard error rate is greater than or equal to 3.00 percent in one evaluation window.
3. A stale false normal count greater than zero triggers rollback or off, depending on severity.
4. A privacy violation count greater than zero triggers incident handling before any new stage decision.
5. Missing telemetry for a required metric is `guardrail_unknown`, not pass.

## Telemetry event schema

All events use the same top-level shape. Event-specific fields live in `attributes`.

```json
{
  "schema_name": "dashboard.telemetry_event",
  "schema_version": "1.0.0",
  "event_id": "tel_20260806_canary_latency_001",
  "event_type": "latency_observed",
  "correlation_id": "corr_operator_dashboard_20260806_001",
  "stage": "canary_5",
  "surface": "/dashboard/risk",
  "subject_ref": {
    "subject_type": "risk_item",
    "subject_id": "risk_20260806_cash_floor_005930",
    "market": "KR",
    "ticker": "005930"
  },
  "observed_at": "2026-08-06T10:05:00+09:00",
  "producer": {
    "name": "dashboard_rollout_observer",
    "version": "1.0.0"
  },
  "attributes": {
    "latency_ms": 842,
    "condition": "partial",
    "freshness_status": "fresh",
    "quality_status": "ok",
    "risk_level": "blocking"
  },
  "privacy": {
    "mode": "redacted",
    "forbidden_fields_present": false,
    "redaction_status": "pass"
  }
}
```

Event type catalog:

| Event type | Required attributes | Must not include |
| --- | --- | --- |
| `rollout_stage_evaluated` | current stage, candidate stage, guardrail result, sample count | raw account ID, credentials |
| `rollout_stage_changed` | from stage, to stage, reason code, snapshot ID | unredacted actor identity |
| `latency_observed` | latency ms, surface, condition | browser fingerprint or raw IP |
| `error_observed` | error code, retryable, affected node, recovery action visible | stack trace with secrets |
| `freshness_observed` | freshness status, age seconds, max age seconds, source health label | raw source payload |
| `usage_success_observed` | journey ID, expected steps, completed steps, success boolean | keystroke content or free text input |
| `fallback_invoked` | fallback policy, from surface, target path, reason code | hidden redirect without reason |
| `privacy_guardrail_failed` | field class, event type, redaction status | secret value itself |
| `incident_opened` | incident ID, severity, trigger event, affected stage | raw credential, raw config |
| `deprecation_warning_seen` | reader version, cutoff date, replacement version | account identifier |

## Rollout observability view model

This read model summarizes stage health and guardrails. It is not a runtime API contract.

```json
{
  "schema_name": "dashboard.rollout_observability_view_model",
  "schema_version": "1.0.0",
  "view_id": "rollout_obs_canary_20260806",
  "stage": "canary_5",
  "generated_at": "2026-08-06T10:10:00+09:00",
  "source_contracts": [
    "dashboard.query_result.1.0.0",
    "dashboard.replay_view_model.1.0.0",
    "dashboard.risk_health_view_model.1.0.0",
    "dashboard.accessibility_responsive_view_model.1.0.0"
  ],
  "audience": {
    "eligible_sessions": 200,
    "exposed_sessions": 10,
    "exposure_percent": "5.00",
    "audience_rule": "eligible_operator_sessions_percent_5"
  },
  "slo_summary": {
    "query_latency_ms_p95": 1180,
    "detail_latency_ms_p95": 1420,
    "typed_error_rate": "0.20",
    "malformed_event_rate": "0.00",
    "stale_false_normal_count": 0,
    "privacy_violation_count": 0,
    "risk_detail_success_rate": "97.00",
    "fallback_success_rate": null,
    "telemetry_lag_seconds_p95": 31
  },
  "guardrails": {
    "status": "pass",
    "minimum_sample_count": 100,
    "observed_sample_count": 500,
    "blocking_reasons": [],
    "candidate_next_stage": "limited_25"
  },
  "audit_access": {
    "surface_viewed_events": 120,
    "risk_detail_opened_events": 97,
    "rollout_stage_changed_events": 0,
    "missing_required_audit_events": 0
  },
  "fallback": {
    "active": false,
    "policy": "rollback_to_internal_dogfood_on_guardrail_fail",
    "last_invoked_at": null
  },
  "privacy": {
    "mode": "redacted",
    "forbidden_fields_present": false,
    "redaction_failures": 0
  },
  "deprecation": {
    "old_reader_version": "0.9.0",
    "replacement_version": "1.0.0",
    "warning_active": true,
    "cutoff_at": "2026-09-30T00:00:00+09:00"
  },
  "conditions": {
    "loading": false,
    "partial": false,
    "error": false,
    "guardrail_unknown": false
  }
}
```

View model rules:

1. `stage` must be one of the stage taxonomy values.
2. `exposure_percent` must match exposed sessions divided by eligible sessions, rounded only for display.
3. `guardrails.status="pass"` is invalid when any required SLO is missing, stale, below threshold, or privacy failing.
4. `fallback.active=true` requires fallback policy, reason code, and latest invocation timestamp.
5. `privacy.forbidden_fields_present=true` forces `conditions.error=true` and blocks stage widening.

## Usage success journeys

Usage success is measured as typed event sequences. It is not inferred from page load or time on page.

| Journey | Required sequence | Success rule | Failure code |
| --- | --- | --- | --- |
| `risk_detail_review` | surface viewed, risk detail opened, caveat visible, recovery or return path visible | all required events share correlation ID within one session | `risk_detail_journey_incomplete` |
| `replay_drilldown_review` | replay list viewed, recommendation selected, detail opened, source or outcome link status read | missing outcome must be explicit when absent | `replay_drilldown_incomplete` |
| `error_recovery_review` | error observed, recovery action seen, return path visible, unsafe retry absent when non-retryable | recovery is read-safe and typed | `unsafe_recovery_path` |
| `keyboard_safe_path` | PRD 04 keyboard steps observed as event IDs, focus return observed | sequence keeps selected identity and caveat | `keyboard_path_interrupted` |
| `fallback_read_path` | fallback invoked, fallback target loaded, risk or error reason preserved | fallback has reason and audit event | `silent_fallback` |

Interruption rules:

1. Operator cancellation records `journey_status="interrupted_by_operator"` and is excluded from error rate denominator.
2. Network or event sink loss records `journey_status="interrupted_by_system"` and counts against telemetry health.
3. A resumed journey must keep the same correlation ID or record a typed resume link.
4. An interrupted canary cannot be counted as success unless the required sequence later closes with a resume link.

## Happy fixture A: canary observed

This fixture proves that a canary rollout can be observed without privacy leakage and without hiding partial risk state.

```json
{
  "fixture_name": "happy_canary_observed",
  "schema_name": "dashboard.rollout_observability.fixture",
  "schema_version": "1.0.0",
  "input_view_model_ref": "rollout_obs_canary_20260806",
  "expected": {
    "stage": "canary_5",
    "exposure_percent": "5.00",
    "guardrail_status": "pass",
    "query_latency_ms_p95_lte": 2500,
    "typed_error_rate_lt": "1.00",
    "stale_false_normal_count": 0,
    "privacy_violation_count": 0,
    "risk_detail_success_rate_gte": "95.00",
    "telemetry_lag_seconds_p95_lte": 120,
    "audit_events_present": true,
    "fallback_active": false,
    "candidate_next_stage": "limited_25"
  }
}
```

## Failure fixture B: error-rate rollback

This fixture is intentionally invalid as a pass candidate. It proves that high error rate rolls back canary exposure.

```json
{
  "fixture_name": "error_rate_rollback_failure",
  "schema_name": "dashboard.rollout_observability.failure_fixture",
  "schema_version": "1.0.0",
  "bad_stage_snapshot": {
    "stage": "canary_5",
    "window_started_at": "2026-08-06T10:00:00+09:00",
    "window_ended_at": "2026-08-06T10:15:00+09:00",
    "observed_sample_count": 300,
    "typed_error_rate": "3.20",
    "malformed_event_rate": "0.00",
    "stale_false_normal_count": 0,
    "privacy_violation_count": 0,
    "guardrail_status": "pass",
    "candidate_next_stage": "limited_25"
  },
  "expected_result": "fail",
  "expected_error_code": "error_rate_rollback_required",
  "expected_rollout_action": "rollback_to_internal_dogfood",
  "must_not_promote": true
}
```

## Incident, fallback, and rollback

Incident response is tied to observed events and guardrails.

| Trigger | Incident severity | Required fallback | Rollback action |
| --- | --- | --- | --- |
| Typed error rate reaches rollback threshold | `action_required` | show typed error and old read path if available | rollback to prior narrower stage |
| Stale false normal count greater than zero | `critical` | block affected current-use surface | rollback or off until stale labeling is fixed |
| Privacy violation count greater than zero | `critical` | stop telemetry export for affected event class | off or blocked privacy mode |
| Telemetry lag above rollback threshold | `watch` or `action_required` | keep dashboard read path but block promotion | hold or rollback after second window |
| Fallback success below threshold | `action_required` | show incident banner and typed recovery path | rollback to stage with known safe fallback |
| Missing rollout audit event | `watch` | freeze stage widening | hold current stage until reconciled |

Incident rules:

1. Incident events include trigger event, affected stage, severity, fallback policy, and owner reference.
2. Fallback must name what changed for the operator and what did not change about data freshness or risk.
3. Rollback cannot delete canary events, audit access, privacy failures, or stale evidence.
4. A privacy incident blocks promotion even if latency and error SLOs pass.
5. Incident closure requires fresh guardrail evidence. Acknowledgement alone is not closure.

## Deprecation policy

Deprecation protects readers that cannot meet v9 contracts.

| Step | Required condition | Required communication |
| --- | --- | --- |
| Announce | replacement reader has stable schema and privacy guardrails | reader version, cutoff date, replacement version, unsupported version behavior |
| Warn | old reader still emits usage events | typed `deprecation_warning_seen` event |
| Read-only | old reader can still show audit-safe data but cannot claim current v9 support | visible old reader warning and unsupported version error path |
| Cutoff | usage below threshold or exception approved | final unsupported version response and audit event |

Deprecation rules:

1. Old reader usage is measured by reader version and surface, not user identity.
2. Unsupported readers receive typed version errors from PRD 01 or deprecated read-only warnings.
3. Deprecation cannot hide risk, stale, privacy, or error states.
4. A deprecation cutoff cannot happen while the replacement has active critical incidents.

## Privacy boundary

Telemetry and audit events may record typed subject references and redacted operator references. They must not record secrets or account identifiers.

Allowed fields:

1. `subject_id`, `risk_item_id`, `source_health_id`, `ticker`, `market`, surface path, event type, condition, stage, reason code, threshold name, redacted actor ref.
2. Aggregated counts, percentages, latency, lag, freshness age, quality status, risk severity, reader version.
3. Hashes that cannot be reversed and that do not encode raw credential or account identifiers.

Forbidden fields:

1. API key, OAuth token, broker credential, raw `config.yaml`, account number, live account ID, raw IP address, device fingerprint.
2. Raw source payload when it can contain secrets or account identifiers.
3. Free text before redaction.
4. Stack trace, exception context, or URL that embeds secret-bearing query params.

Privacy rules:

1. Privacy guardrail failure blocks stage widening and opens an incident.
2. `redaction_status="fail"` is itself observable, but the forbidden value is not recorded.
3. Aggregates with sample count below the privacy minimum are suppressed as `aggregate_insufficient_sample`.
4. Privacy checks run before telemetry export and before evidence is attached to rollout review.

## Parse matrix

| Check | Required pass condition | Failure code |
| --- | --- | --- |
| Title | line 1 exact PRD title | `bad_title` |
| Draft metadata | line 2 exact draft status and only one status line | `bad_status` |
| Forbidden marker | done marker absent | `done_marker_present` |
| Workflow wording | global numbered workflow wording absent | `global_workflow_reference_present` |
| JSON fences | every JSON fence parses | `json_parse_error` |
| Stage taxonomy | all six stage values and fallback rules exist | `rollout_stage_missing` |
| SLO thresholds | canary, wider, rollback thresholds exist | `slo_threshold_missing` |
| Event schema | telemetry top-level fields and privacy block exist | `telemetry_event_malformed` |
| Happy fixture | canary guardrails pass and audit events are present | `happy_canary_failed` |
| Rollback fixture | 3.20 percent error rate fails and rolls back | `rollback_not_detected` |

## Fixture matrix

| Fixture | Happy or failure | Must prove |
| --- | --- | --- |
| `happy_canary_observed` | happy | canary stage, 5 percent exposure, SLO pass, audit present, no fallback, no privacy violation |
| `error_rate_rollback_failure` | failure | typed error rate above threshold cannot pass and must rollback |

## Mutation probes

| Probe | Mutation | Expected result |
| --- | --- | --- |
| `json` | Remove `schema_name`, make `stage` an unknown value, or make `privacy` a string | fail with `malformed_rollout_observability_view_model` |
| `threshold` | Set `typed_error_rate="3.20"` while guardrail status remains pass | fail with `error_rate_rollback_required` |
| `stale` | Set `stale_false_normal_count=1` while candidate next stage is wider | fail with `stale_false_normal_blocks_promotion` |
| `privacy` | Add forbidden account ID, token, raw config, or unredacted free text | fail with `privacy_boundary_violation` |
| `interruption` | Count interrupted operator or system journey as usage success without resume link | fail with `interrupted_journey_counted_success` |
| `fallback` | Invoke fallback without reason, audit event, or visible typed path | fail with `silent_fallback` |
| `deprecation` | Cut off old reader while replacement has critical incident | fail with `unsafe_deprecation_cutoff` |

## Validation and failing-first evidence

Task 35 evidence must prove target absence before creation, then prove this PRD through manual Read and deterministic parsing.

Required checks:

1. Read this PRD from line 1 and confirm the title and one draft status line.
2. Confirm there is no done marker and no global numbered workflow reference.
3. Parse every fenced JSON block intended as JSON.
4. Validate rollout stages, feature flag fields, audit access events, telemetry dimensions, SLO thresholds, event catalog, view model, usage success journeys, incident fallback, rollback, deprecation, and privacy boundary.
5. Validate happy canary fixture: stage is `canary_5`, exposure is `5.00`, guardrail status is pass, SLOs meet canary thresholds, audit events exist, privacy violation count is zero, and fallback is inactive.
6. Validate error-rate rollback fixture: typed error rate `3.20` fails with `error_rate_rollback_required`, expected action is rollback, and promotion is forbidden.
7. Run JSON, threshold, stale, privacy, interruption, fallback, and deprecation mutation probes.

## Acceptance criteria

1. The document has exact draft metadata directly under the title and no done marker.
2. It defines feature rollout stages, feature flag contract, audit access, telemetry dimensions, SLO thresholds, and telemetry events.
3. It defines latency, error, freshness, usage success, fallback, rollback, incident, deprecation, and privacy behavior.
4. It includes rollout observability view model, happy canary fixture, and error-rate rollback failure fixture.
5. It includes parse matrix, fixture matrix, and JSON, threshold, stale, privacy, interruption mutation probes.
6. It does not require screen implementation, browser build, backend changes, source/data/config changes, portfolio mutation, broker call, worklog, state update, staging, or commit.
