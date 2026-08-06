# PRD: v9 PRD 04 accessibility responsive errors
> **상태**: 📝 초안
> **SPEC 참조**: [v9 SPEC](../SPEC.md)

## 문제

v9 PRD 01은 dashboard 입력 계약을 정의했고, v9 PRD 02는 replay 정보 구조를 정의했으며, v9 PRD 03은 risk health 표면을 정의했다. 하지만 운영자가 키보드만 쓰거나, 화면 폭이 작거나, 보조 기술을 쓰거나, 일부 데이터가 빠진 상태에서 같은 판단을 할 수 있는 계약은 아직 없다.

Trading Oracle dashboard는 투자 판단을 다루므로 접근성 실패가 단순 사용성 문제가 아니다. focus가 사라지면 위험 항목을 건너뛸 수 있고, 색만으로 BUY와 blocked를 구분하면 위험을 놓칠 수 있다. stale, degraded, partial, missing 상태가 좁은 화면에서 접히거나 screen reader에서 빠지면 사용자는 일부 데이터 성공을 전체 성공으로 오해할 수 있다.

이 PRD는 접근성, 반응형 정보 우선순위, 오류 상태, 복구 경로, 로컬라이즈된 숫자와 통화 표기, reduced motion 표면 계약을 정의한다. 화면 구현, visual token, client cache, 서버 API, 브라우저 빌드는 만들지 않는다.

## 목표

1. WCAG 목표와 keyboard, focus, contrast, screen-reader semantics 계약을 고정한다.
2. terminal formatter의 정보 우선순위를 dashboard read model에 맞게 보존한다.
3. CJK 이름, 한글 copy, 숫자, 원화, 달러, 환율 보조 표기의 읽기 규칙을 정의한다.
4. responsive breakpoint별 필수 정보와 접힘 금지 정보를 정의한다.
5. loading, empty, partial, error 상태가 성공처럼 보이지 않게 한다.
6. error recovery와 localization fixture를 제공한다.
7. happy keyboard-only fixture와 misleading partial data failure fixture를 제공한다.
8. parse matrix, fixture matrix, mutation probe로 작성 계약을 검증할 수 있게 한다.

## 범위 밖

1. 화면 component, route, CSS, animation 구현은 다루지 않는다.
2. backend 조회 API, database schema, queue, cache, broker 연동은 새로 정의하지 않는다.
3. 추천, replay, risk, performance, portfolio 값을 재계산하지 않는다.
4. `scripts/**`, `src/**`, `data/**`, `config.yaml`, `README.md` 변경을 요구하지 않는다.
5. Rich terminal markup, emoji, localized prose를 business data로 파싱하지 않는다.
6. browser UI build, screenshot QA, Lighthouse, Playwright 실행을 이 문서 작성 산출물로 요구하지 않는다.

## 선행 입력

| 입력 | 이 PRD에서 쓰는 부분 | 경계 |
| --- | --- | --- |
| v9 PRD 01 dashboard input contract | envelope, query result, freshness, quality, risk state, adapter boundary, error envelope | 입력 계약만 소비한다. |
| v9 PRD 02 replay information architecture | navigation node, list, detail, timeline, drilldown, conditions | 정보 구조와 상태 의미만 소비한다. |
| v9 PRD 03 risk health calibration surfaces | risk inbox, source health, confidence reliability, divergence, severity, acknowledgement | risk visibility와 actionability 의미만 소비한다. |
| `src/output/formatter.py` | header, warning, error, signal, portfolio, price and PnL display ordering | Rich presentation은 파싱하지 않는다. 정보 우선순위만 참고한다. |
| `src/common.py` display helpers | KRW, USD, approximate KRW, exchange rate, cash display examples | display string은 보조 표기다. typed numeric field가 source of truth다. |

## 용어

| 용어 | 의미 |
| --- | --- |
| accessibility contract | renderer가 충족해야 하는 keyboard, focus, contrast, semantic, reduced motion 규칙 |
| responsive contract | viewport 폭이 바뀌어도 보존해야 하는 정보 우선순위와 상태 노출 규칙 |
| condition | loading, empty, partial, error 같은 view model 상태 |
| recovery action | 사용자가 오류나 부분 상태에서 안전하게 다음 행동을 고를 수 있는 read-safe action |
| CJK-safe display | 한글, 숫자 grouping, 원화, 달러, 환율, 긴 종목명이 잘리거나 오해되지 않는 표시 |
| misleading partial | 일부 section만 성공인데 전체 화면이 성공처럼 보이는 실패 |

## WCAG 목표

기본 목표는 WCAG 2.2 AA다. 투자 위험, blocked action, critical alert, destructive-looking recovery copy는 더 엄격한 내부 기준을 적용한다.

| 항목 | 목표 | 계약 |
| --- | --- | --- |
| Keyboard | 모든 read surface와 recovery action은 키보드만으로 도달 가능 | Tab, Shift Tab, Enter, Space, Escape, Arrow key 동작을 정의한다. |
| Focus visible | focus 위치는 항상 보인다 | focus ring은 색만으로 의존하지 않고 두께, outline, offset 중 하나 이상으로 드러난다. |
| Contrast | 일반 텍스트 4.5:1 이상, 큰 텍스트 3:1 이상 | risk, error, stale, blocked, selected 상태는 색 외에 text label을 가진다. |
| Non-text contrast | focus indicator, icon, chart marker, divider 상태 3:1 이상 | 상태 아이콘만으로 의미를 전달하지 않는다. |
| Screen reader | landmark, heading, list, table, status, alert semantics가 존재 | visual order와 accessible name order가 다르면 실패다. |
| Target size | primary action과 recovery action은 최소 24 by 24 CSS px | 좁은 화면에서도 touch target 사이 간격이 유지된다. |
| Motion | reduced motion 선호 시 의미 없는 transition은 꺼진다 | status change는 motion 없이 text와 live region으로 전달된다. |
| Language | document와 dynamic region은 한국어 기본, 코드와 ticker는 code token | 한글 조사나 통화 단위가 screen reader에서 숫자를 숨기지 않는다. |

AA 미달이면 release-ready 상태가 아니다. 이 문서는 구현을 만들지 않지만, 후속 renderer가 이 표를 충족하지 못하면 접근성 계약 실패다.

## 정보 우선순위

터미널 formatter는 header, warning 또는 error, portfolio summary, signal card, analysis card처럼 사용자가 먼저 볼 위험과 정체성을 앞에 둔다. Dashboard renderer도 같은 우선순위를 보존해야 한다.

| Priority | 정보 | Required behavior | Must not do |
| --- | --- | --- | --- |
| 1 | blocking error, critical alert, stale health falsely normal, risk blocked | 화면 폭과 보조 기술 모두에서 가장 먼저 탐색된다. | 접힌 secondary panel 안에 숨긴다. |
| 2 | selected subject identity, ticker, market, action, risk level | 제목, breadcrumb, row accessible name에 포함한다. | ticker만 남기고 action이나 risk를 숨긴다. |
| 3 | freshness, quality, partial, missing, degraded caveat | 상태 label을 행과 detail 상단에 반복한다. | 색, icon, hover text에만 둔다. |
| 4 | decision, consensus, confidence, action plan, source cutoff | typed field label과 함께 읽힌다. | formatted prose에서 값을 복구한다. |
| 5 | source, outcome, evidence, recovery, drilldown | 링크와 button 이름이 목적을 말한다. | `자세히` 같은 중복 이름만 쓴다. |
| 6 | secondary metrics, visual grouping, historical context | 좁은 화면에서 접을 수 있지만 요약과 상태는 남긴다. | 접힌 상태에서 위험 count를 줄인다. |

Rules:

1. Priority 1부터 3까지는 모든 breakpoint에서 visible 또는 screen-reader reachable이어야 한다.
2. Priority 4는 좁은 화면에서 section으로 접을 수 있지만 accessible summary에 남아야 한다.
3. Priority 5 recovery action은 error와 partial 상태에서 keyboard로 바로 닿아야 한다.
4. Priority 6은 접을 수 있으나 summary count와 condition state를 바꾸지 않는다.
5. Rich terminal emoji나 색 이름은 우선순위 근거가 아니다. 구조화된 status, severity, condition, risk field만 근거다.

## Keyboard 계약

Keyboard contract는 renderer surface가 충족할 동작 규칙이다. 이 문서는 routing이나 component를 만들지 않는다.

| Interaction | Required behavior | Failure code |
| --- | --- | --- |
| Tab order | Skip link, global status, primary navigation, selected list, detail, recovery actions 순서 | `keyboard_order_invalid` |
| Shift Tab | 역방향 이동이 같은 순서를 보존 | `keyboard_reverse_order_invalid` |
| Enter | link, disclosure, selected row, recovery action을 실행 | `keyboard_activation_missing` |
| Space | button, checkbox-like filter, disclosure를 실행 | `keyboard_activation_missing` |
| Arrow keys | table, tablist, segmented filter 안에서만 roving focus 허용 | `keyboard_roving_scope_invalid` |
| Escape | transient panel, filter popover, local error detail을 닫고 opener로 focus 반환 | `focus_return_missing` |
| Skip link | main content 또는 active risk list로 이동 | `skip_link_missing` |
| No trap | modal dialog가 아닌 곳에서 focus trap 금지 | `focus_trap_invalid` |

Keyboard-only happy path:

1. Skip link로 risk inbox 또는 replay list에 진입한다.
2. Tab으로 stale 또는 blocked caveat을 읽는다.
3. Arrow key로 selected row를 바꾼다.
4. Enter로 detail을 연다.
5. Tab으로 source health, outcome status, recovery action에 닿는다.
6. Escape로 local panel을 닫으면 opener row로 focus가 돌아간다.
7. Shift Tab으로 이전 control에 돌아가도 focus 위치와 selected identity가 유지된다.

## Focus 계약

| State | Focus rule | Announcement rule |
| --- | --- | --- |
| Initial load | main heading 또는 selected node summary에 focus를 두지 않는다. User initiated navigation일 때만 focus 이동 | loading status는 polite live region |
| Query success | focus를 강제로 첫 row로 빼앗지 않는다 | returned count와 condition을 status region에 알림 |
| Error | typed error summary가 focus target이 된다 | error code, affected node, recovery action을 assertive region에 알림 |
| Partial | 현재 focus 유지. 새 caveat summary가 status region에 추가 | missing field와 degraded section을 알림 |
| Drilldown open | detail heading으로 이동하고 return context를 저장 | selected subject, action, caveat을 heading label에 포함 |
| Panel close | opener control로 focus 반환 | 닫힌 panel 이름을 알림 |

Focus visible requirements:

1. Focus indicator는 background, row selection, alert severity color와 구분된다.
2. Focused disabled action은 설명 text를 가진다. disabled만 있고 이유가 없으면 실패다.
3. Focus 이동은 condition change와 분리된다. partial data arrival이 사용자의 keyboard 위치를 잃게 하면 실패다.
4. Focusable row와 nested link가 둘 다 있으면 accessible name은 중복되지 않는다.

## Contrast와 색 의존 금지

| Meaning | Required visible text | Color-only forbidden example |
| --- | --- | --- |
| Fresh | `fresh` 또는 `최신` plus age | green dot only |
| Stale | `stale` 또는 `오래된 데이터` plus age and max age | yellow background only |
| Degraded | `degraded` 또는 `부분 데이터` plus failed check count | dim text only |
| Blocked | `blocked` 또는 `현재 사용 차단` plus reason code | red icon only |
| Missing | `missing` 또는 `자료 없음` plus neutral reason | blank cell |
| BUY, SELL, HOLD | action text plus consensus | green, red, gray color only |
| Positive or negative PnL | signed value plus label | green or red number without sign |

Contrast rules:

1. Critical, blocking, error, selected, and focused states must each remain distinguishable in high contrast mode.
2. Disabled actions must meet readable contrast and include disabled reason.
3. Chart or sparkline data cannot be the only source for risk, confidence, or outcome meaning.
4. If color token fails contrast, renderer must use a compliant fallback token while preserving the same text and order.

## Screen-reader semantics

Required semantic map:

| Surface element | Semantics | Accessible name source |
| --- | --- | --- |
| Page shell | landmark: banner, navigation, main, complementary when present | node label and current condition |
| Risk inbox | table or list with row count | risk item count and selected filter |
| Replay list | table or list with row count | recommendation count, filter, sort |
| Detail header | h1 or h2 | ticker, market, action, risk level, condition |
| Caveat summary | status or alert depending severity | freshness, quality, risk, missing reason |
| Error summary | alert | error code, affected node, retryable, recovery actions |
| Loading region | status with busy state | node and query ID when known |
| Partial section | group with labelled condition | section name, missing fields, recovery path |
| Numeric metric | text plus machine value where available | display label, value, unit, timestamp |
| Recovery action | button or link | verb, target, safe effect |

Screen-reader rules:

1. Heading order must not skip levels within the active node.
2. Every table has a caption or labelled group that names current filters and condition.
3. Every row accessible name includes identity, action, condition, and primary caveat.
4. `aria-live` equivalent behavior is polite for loading and success, assertive for blocking error and critical alert.
5. `aria-busy` equivalent behavior must clear when condition stops loading.
6. Hidden visual content that carries priority 1 to 3 information must remain accessible, or the visual surface must keep it visible.
7. Decorative icons are hidden from assistive tech only when their meaning is duplicated in text.

## CJK number and currency 계약

The data source of truth is typed numeric value plus currency and timestamp. Display strings are derived. Renderer must not parse a localized string to recover amount, price, percentage, date, or action.

| Value type | Required fields | Display example | Screen-reader intent |
| --- | --- | --- | --- |
| KRW price | numeric value, `currency="KRW"`, market, timestamp | `79,000원` | `79,000 원` |
| USD price with KRW estimate | numeric USD, exchange rate, estimated KRW, timestamp | `$120.50 (약 166,892원, 환율 1,385.00원/USD)` | dollar value, approximate KRW, exchange rate |
| Cash mixed currency | KRW cash, USD cash, estimated KRW, exchange rate | `5,000,000원 + $100.00 (약 138,500원)` | separate currencies, then estimate |
| Percent | signed numeric value, unit `%`, basis | `+4.2%` | positive 4.2 percent |
| Ratio | numerator, denominator, label | `Bull 5/6` | Bull votes 5 of 6 |
| Korean ticker name | name, ticker, market | `삼성전자 (005930)` | name then ticker |
| Long CJK name | full name, short display label | `한국전력...` only if full accessible name exists | full name reachable without hover |

Localization rules:

1. `N/A`, null, missing, and zero are different. Null or missing cannot display as `0원`.
2. Approximate KRW is labelled as approximate and must include exchange rate timestamp or source caveat when available.
3. Negative values keep a visible sign and must not rely on red color.
4. Percent values must name basis, such as return, cash ratio, confidence gap, or source lag.
5. Korean copy must not split ticker, currency unit, or percent sign across inaccessible fragments.
6. Numbers copied to clipboard or exported from a cell use typed numeric fields, not localized display strings.

## Responsive breakpoints

Breakpoints define information behavior, not pixel-perfect layout.

| Breakpoint ID | Width range | Required behavior |
| --- | --- | --- |
| `compact` | 320 to 479 CSS px | One-column reading order, priority 1 to 3 visible, priority 4 summarized, recovery actions reachable without horizontal scroll. |
| `phone` | 480 to 767 CSS px | One-column with expandable sections, selected identity sticky within node, caveat summary visible. |
| `tablet` | 768 to 1023 CSS px | Two-pane allowed. List and detail can sit side by side if focus order stays logical. |
| `desktop` | 1024 to 1439 CSS px | Multi-column allowed. Risk, replay, and detail preserve heading and table semantics. |
| `wide` | 1440 CSS px and above | Additional comparison columns allowed. Priority order and keyboard path cannot change. |

Responsive state matrix:

| State | Compact | Phone | Tablet | Desktop and wide |
| --- | --- | --- | --- | --- |
| Normal ready | Show identity, action, risk, freshness, quality, primary metric | Same plus collapsible decision summary | List/detail split allowed | Full columns allowed |
| Loading | Show skeleton only after text status names node | Same | Same | Same |
| Empty | Show filter summary and reset action | Same | Same plus empty panel | Same |
| Partial | Show partial banner before data cards | Same plus missing section links | Same plus section markers | Same plus full failed check list |
| Error | Show error summary, code, affected node, recovery action first | Same | Same | Same |
| Critical risk | Pinned top alert and row caveat | Same | Same | Same |

Responsive rules:

1. Horizontal scroll is allowed only for secondary metric tables. It is forbidden for primary identity, condition, caveat, and recovery actions.
2. Column hiding must follow information priority, never DOM order alone.
3. Cards converted from rows must preserve row accessible name, count, sort, and selected identity.
4. Split panes must not create two active keyboard tab orders that skip status or recovery.
5. Any collapsed section with error, missing, stale, degraded, or blocked status must show that status in the collapsed label.

## Loading, empty, partial, and error contract

| Condition | Meaning | Required behavior | Forbidden result |
| --- | --- | --- | --- |
| `loading` | query or linked payload has not arrived | Name node, query ID when known, and pending section | Show stale previous result as current |
| `empty` | valid query returned no items | Show filters, sort, and reset path | Treat valid empty as error |
| `partial` | base surface is readable but section is missing, stale, or degraded | Show readable sections plus caveat summary | Count partial as ok or fresh |
| `error` | malformed query, unsupported version, broken identity, forbidden data, or blocked required source | Show typed error code, affected node, retryable, recovery actions | Show success summary or hide failed section |

Condition precedence:

1. `error` overrides `partial`, `empty`, and `loading` for the affected node.
2. `critical` risk alert appears above local `error` when it affects current use.
3. `partial` can coexist with ready sections, but summary must say partial.
4. `empty` applies only to valid list queries.
5. `loading` cannot keep `aria-busy` equivalent true after final content is shown.

## Error recovery contract

Recovery actions are read-safe. They never mutate recommendation, portfolio, broker, source, config, calibration, or acknowledgement facts unless a later PRD defines that mutation.

| Error code family | Required copy | Recovery actions | Disabled reason |
| --- | --- | --- | --- |
| `unsupported_*_version` | requested and supported versions | change accepted version, open contract details | no compatible reader |
| `malformed_query` | invalid field and node | reset filters, return to list | query cannot be repaired locally |
| `malformed_source_payload` | adapter and affected payload type | open source health, retry source read if provided as safe action | source shape invalid |
| `source_stale` | age, max age, affected fields | open source health, switch to audit view | current use blocked |
| `risk_blocked` | reason codes and actionability | open risk detail, acknowledge if allowed by risk PRD | action blocked by risk |
| `broken_drilldown_link` | rel, target, missing reason | return to parent, open link health | target unavailable |
| `localization_invalid` | field, locale, expected type | show raw typed value, report formatter issue | display string unsafe |

Recovery rules:

1. Error summary must include one primary safe action and one return path when possible.
2. Retryable false errors must not show retry as the primary action.
3. Recovery action labels must be unique in the active node.
4. Disabled recovery actions must include reason and required evidence, not just disabled styling.
5. A partial recovery must not clear error state for unaffected required fields.

## Reduced motion contract

| Motion source | Default | Reduced motion behavior |
| --- | --- | --- |
| Loading skeleton | Optional visual placeholder with text status | Text status only or static placeholder |
| Panel open | Short transform or opacity allowed | Instant open with focus change and status text |
| Row selection | Non-layout highlight allowed | Static focus and selected text only |
| Alert appearance | No flashing | Static assertive announcement |
| Chart update | Transition allowed if data change remains readable | Instant update plus changed value summary |

Reduced motion rules:

1. No essential meaning may depend on animation.
2. No flashing or repeated pulse is allowed for risk, error, or stale state.
3. Motion must not move focus or reorder content.
4. Reduced motion preference must keep all status text, caveat summaries, and recovery actions intact.

## Accessibility view model

This read model describes what a renderer must know. It is not a backend API contract.

```json
{
  "schema_name": "dashboard.accessibility_responsive_view_model",
  "schema_version": "1.0.0",
  "source_contracts": [
    "dashboard.query_result.1.0.0",
    "dashboard.replay_view_model.1.0.0",
    "dashboard.risk_health_view_model.1.0.0"
  ],
  "view_id": "accessibility_replay_risk_20260806",
  "locale": "ko-KR",
  "breakpoint": "compact",
  "wcag_target": "WCAG_2_2_AA",
  "information_priority": [
    "blocking_error",
    "selected_identity",
    "freshness_quality_risk_caveat",
    "decision_summary",
    "source_outcome_recovery",
    "secondary_metrics"
  ],
  "keyboard": {
    "skip_links": [
      {"label": "위험 목록으로 건너뛰기", "target": "risk_inbox"},
      {"label": "선택 추천 상세로 건너뛰기", "target": "recommendation_detail"}
    ],
    "tab_order": [
      "skip_to_risk",
      "global_status",
      "risk_row_risk_20260806_cash_floor_005930",
      "open_risk_detail",
      "recommendation_detail_heading",
      "source_health_link",
      "outcome_status_link",
      "return_to_list"
    ],
    "escape_returns_to": "risk_row_risk_20260806_cash_floor_005930"
  },
  "focus": {
    "current_focus_id": "risk_row_risk_20260806_cash_floor_005930",
    "visible_indicator_required": true,
    "return_context": {
      "node": "/dashboard/risk",
      "selected_id": "risk_20260806_cash_floor_005930"
    }
  },
  "semantics": {
    "main_heading": "Trading Oracle risk dashboard",
    "active_landmarks": ["banner", "navigation", "main"],
    "live_regions": [
      {"id": "global_status", "politeness": "polite", "text": "위험 2건, 차단 1건, 부분 데이터 2건"},
      {"id": "critical_alerts", "politeness": "assertive", "text": "현재 매수 실행은 현금 하한 위험으로 차단됨"}
    ],
    "row_accessible_names": [
      "삼성전자 005930, BUY, risk blocked, fresh source, cash floor breach"
    ]
  },
  "responsive_visibility": {
    "visible_priorities": [1, 2, 3],
    "summarized_priorities": [4],
    "collapsed_priorities": [5, 6],
    "horizontal_scroll_allowed_for": ["secondary_metrics_table"]
  },
  "conditions": {
    "loading": false,
    "empty": false,
    "partial": true,
    "error": false,
    "reduced_motion": true
  },
  "localization": {
    "numbering_system": "latn",
    "currency_displays": [
      {"field": "price", "numeric_value": 79000, "currency": "KRW", "display": "79,000원"},
      {"field": "us_price", "numeric_value": 120.5, "currency": "USD", "display": "$120.50 (약 166,892원, 환율 1,385.00원/USD)", "approximate_krw": 166892, "exchange_rate": 1385.0}
    ],
    "missing_values": [
      {"field": "outcome_metrics", "display": "자료 없음", "reason": "outcome_not_available", "must_not_display_as_zero": true}
    ]
  },
  "recovery_actions": [
    {"id": "open_risk_detail", "label": "현금 하한 위험 상세 열기", "safe_effect": "read_detail", "enabled": true},
    {"id": "return_to_list", "label": "추천 목록으로 돌아가기", "safe_effect": "navigate_back", "enabled": true}
  ]
}
```

View model rules:

1. `information_priority` must include the six priority groups in order.
2. `breakpoint` must be one of `compact`, `phone`, `tablet`, `desktop`, or `wide`.
3. `tab_order` must include skip link, status, selected item, detail, recovery, and return path when those regions exist.
4. `conditions.partial=true` requires a visible or announced partial caveat.
5. `conditions.error=true` requires at least one recovery action or explicit no-recovery reason.
6. `localization.currency_displays[]` must keep numeric value and display string separate.
7. Missing values must include reason and must not display as zero unless the typed value is numeric zero.

## Fixture A: happy keyboard-only flow

This fixture proves that a compact dashboard surface can be used without a pointer while preserving risk and partial caveats.

```json
{
  "fixture_name": "happy_keyboard_only_flow",
  "schema_name": "dashboard.accessibility_responsive.fixture",
  "schema_version": "1.0.0",
  "input_view_model_ref": "accessibility_replay_risk_20260806",
  "scenario": {
    "locale": "ko-KR",
    "breakpoint": "compact",
    "input_method": "keyboard_only",
    "reduced_motion": true,
    "steps": [
      {"key": "Tab", "lands_on": "skip_to_risk"},
      {"key": "Enter", "lands_on": "risk_inbox"},
      {"key": "Tab", "lands_on": "risk_row_risk_20260806_cash_floor_005930"},
      {"key": "Enter", "lands_on": "recommendation_detail_heading"},
      {"key": "Tab", "lands_on": "source_health_link"},
      {"key": "Tab", "lands_on": "outcome_status_link"},
      {"key": "Escape", "lands_on": "risk_row_risk_20260806_cash_floor_005930"}
    ]
  },
  "expected": {
    "wcag_target": "WCAG_2_2_AA",
    "priority_1_visible": true,
    "priority_2_visible": true,
    "priority_3_visible": true,
    "focus_visible_every_step": true,
    "blocked_risk_announced": true,
    "partial_caveat_announced": true,
    "recovery_action_reachable": true,
    "escape_returns_to_opener": true,
    "horizontal_scroll_for_primary_info": false,
    "motion_required_for_meaning": false
  }
}
```

## Fixture B: localization recovery

This fixture proves that CJK and currency display are derived from typed values and can recover safely when display formatting fails.

```json
{
  "fixture_name": "localization_recovery",
  "schema_name": "dashboard.accessibility_responsive.fixture",
  "schema_version": "1.0.0",
  "locale": "ko-KR",
  "typed_values": {
    "ticker": "005930",
    "name": "삼성전자",
    "market": "KR",
    "price": {"value": 79000, "currency": "KRW", "timestamp": "2026-08-06T09:05:00+09:00"},
    "us_price": {"value": 120.5, "currency": "USD", "exchange_rate": 1385.0, "estimated_krw": 166892, "timestamp": "2026-08-06T09:05:00+09:00"},
    "outcome_metrics": null
  },
  "display_values": {
    "identity": "삼성전자 (005930)",
    "krw_price": "79,000원",
    "usd_price": "$120.50 (약 166,892원, 환율 1,385.00원/USD)",
    "outcome_metrics": "자료 없음"
  },
  "expected": {
    "display_not_source_of_truth": true,
    "krw_value_not_zero_when_missing": true,
    "missing_outcome_reason_required": "outcome_not_available",
    "screen_reader_identity": "삼성전자 005930 KR",
    "currency_units_visible": true,
    "approximate_krw_label_visible": true
  }
}
```

## Fixture C: misleading partial data failure

This fixture is intentionally invalid. It proves partial data cannot look complete or safe.

```json
{
  "fixture_name": "misleading_partial_data_failure",
  "schema_name": "dashboard.accessibility_responsive.failure_fixture",
  "schema_version": "1.0.0",
  "bad_view_model": {
    "schema_name": "dashboard.accessibility_responsive_view_model",
    "schema_version": "1.0.0",
    "locale": "ko-KR",
    "breakpoint": "compact",
    "information_priority": ["selected_identity", "decision_summary", "secondary_metrics"],
    "conditions": {"loading": false, "empty": false, "partial": false, "error": false, "reduced_motion": false},
    "responsive_visibility": {
      "visible_priorities": [2, 4],
      "summarized_priorities": [6],
      "collapsed_priorities": [1, 3, 5],
      "horizontal_scroll_allowed_for": ["primary_identity", "risk_caveat"]
    },
    "semantics": {
      "row_accessible_names": ["삼성전자 005930 BUY"]
    },
    "localization": {
      "missing_values": [
        {"field": "outcome_metrics", "display": "0원", "reason": null, "must_not_display_as_zero": false}
      ]
    },
    "recovery_actions": []
  },
  "expected_result": "fail",
  "expected_error_codes": [
    "misleading_partial_data",
    "priority_caveat_hidden",
    "missing_value_as_zero",
    "recovery_action_missing"
  ]
}
```

## Parse matrix

| Check | Required pass condition | Failure code |
| --- | --- | --- |
| Title | line 1 exact PRD title | `bad_title` |
| Draft metadata | line 2 exact draft status and only one status line | `bad_status` |
| Forbidden marker | done marker absent | `done_marker_present` |
| Workflow wording | global numbered workflow wording absent | `global_workflow_reference_present` |
| JSON fences | every JSON fence parses | `json_parse_error` |
| View model | schema name, breakpoint, priority, keyboard, focus, semantics, conditions, localization valid | `malformed_accessibility_view_model` |
| Happy fixture | keyboard-only path reaches detail, caveat, recovery, and returns focus | `keyboard_happy_path_failed` |
| Localization fixture | typed values are source of truth and missing is not zero | `localization_contract_failed` |
| Failure fixture | misleading partial data fails with all expected codes | `misleading_partial_not_detected` |

## Fixture matrix

| Fixture | Happy or failure | Must prove |
| --- | --- | --- |
| `happy_keyboard_only_flow` | happy | compact keyboard path, focus visibility, caveat announcement, recovery reachability, reduced motion safety |
| `localization_recovery` | happy | CJK name, KRW, USD, approximate KRW, missing outcome reason, display not source of truth |
| `misleading_partial_data_failure` | failure | hidden caveat, partial marked ready, missing as zero, absent recovery all fail |

## Mutation probes

| Probe | Mutation | Expected result |
| --- | --- | --- |
| `keyboard` | Remove skip link, remove Escape return target, or omit recovery from tab order | fail with `keyboard_path_broken` |
| `focus` | Move focus on partial arrival or close panel without opener return | fail with `focus_return_missing` |
| `contrast` | Represent stale, blocked, BUY, or negative PnL with color only | fail with `color_only_state` |
| `screen_reader` | Remove row caveat from accessible name or keep busy true after load | fail with `semantic_state_missing` |
| `responsive` | Hide priority 1 to 3 or require horizontal scroll for primary info | fail with `responsive_priority_violation` |
| `localization` | Show missing numeric value as `0원`, parse display string as source, or omit approximate KRW label | fail with `localization_misleading` |
| `partial` | Set `partial=false` while missing outcome or degraded source exists | fail with `misleading_partial_data` |
| `error_recovery` | Show retry for non-retryable error as primary action or omit return path | fail with `unsafe_recovery` |
| `reduced_motion` | Require animation to understand status change | fail with `motion_required_for_meaning` |
| `dirty` | Use Rich markup, emoji, localized prose, config, credential, or account ID as business data | fail with `adapter_boundary_violation` |
| `malformed` | Invalid JSON, bad breakpoint, missing WCAG target, bad condition type, or missing locale | fail with `malformed_accessibility_view_model` |

## Validation and failing-first evidence

Task 34 evidence must prove target absence before creation, then prove this PRD through manual Read and deterministic parsing.

Required checks:

1. Read this PRD from line 1 and confirm the title and one draft status line.
2. Confirm there is no done marker and no global numbered workflow reference.
3. Parse every fenced JSON block intended as JSON.
4. Validate WCAG target, keyboard contract, focus contract, contrast rules, screen-reader semantics, CJK number and currency contract, responsive breakpoints, reduced motion, conditions, and recovery rules.
5. Validate accessibility view model: source contracts, locale, breakpoint, information priority, keyboard tab order, focus return, semantics, responsive visibility, conditions, localization, and recovery actions.
6. Validate happy keyboard-only fixture: compact breakpoint, keyboard-only steps, focus visible every step, blocked risk announced, partial caveat announced, recovery reachable, Escape returns to opener, and motion not required.
7. Validate localization fixture: typed values stay source of truth, KRW and USD display keep units, approximate KRW is labelled, and missing outcome is not zero.
8. Validate misleading partial data failure fixture: priority caveat hidden, partial marked ready, missing value as zero, and missing recovery actions all fail.
9. Run mutation probes for keyboard, focus, contrast, screen reader, responsive, localization, partial, error recovery, reduced motion, dirty, and malformed cases.

## Acceptance criteria

1. The document has exact draft metadata directly under the title and no done marker.
2. It defines WCAG target, keyboard, focus, contrast, screen-reader semantics, CJK number and currency rules, responsive breakpoints, reduced motion, loading, empty, partial, error, and recovery contracts.
3. It preserves terminal formatter information priority without parsing Rich presentation output.
4. It includes accessibility view model, happy keyboard-only fixture, localization recovery fixture, and misleading partial data failure fixture.
5. It includes parse matrix, fixture matrix, and mutation probes.
6. It does not require screen implementation, browser build, backend changes, portfolio mutation, broker call, source refetch, calibration execution, source/data/config changes, worklog, state update, or staging.
