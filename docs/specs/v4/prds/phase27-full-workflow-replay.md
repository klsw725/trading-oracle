# PRD: Phase 27 full workflow replay
> **상태**: ✅ 완료
> **SPEC 참조**: [../SPEC.md](../SPEC.md)

## 문제

기존 시그널 백테스트는 LLM 호출 없이 시그널 레이어만 재생한다. 이 레이어는 빠르고 비용이 없지만, 실제 추천 품질을 결정한 universe, candidate selection, 다관점 LLM, consensus, deliberation, portfolio risk gate, operator decision, trade, outcome event를 같은 입력으로 다시 걸어 보지 않는다.

Phase 23 snapshot은 재현 가능한 native v4 입력과 raw/parsed 결과를 저장하고, Phase 26 attribution은 후보부터 체결과 outcome까지 denominator를 보존한다. Phase 27은 두 계약을 소비해 전체 워크플로우를 감사 가능한 방식으로 replay한다. 단, 이 문서는 replay 계약과 실패 검증만 정의하며 실제 replay 실행, 데이터 수집, LLM 호출, portfolio 상태 변경은 하지 않는다.

## 목표

1. `verbatim replay`, `outcome replay`, `recompute replay`를 서로 다른 산출물로 정의한다.
2. replay eligibility를 snapshot, attribution, raw prompt, raw LLM, data cutoff, market context, portfolio state, ledger 연결 기준으로 판정한다.
3. full workflow state machine을 universe/candidate selection부터 signal, five perspectives, consensus/deliberation, portfolio/risk constraints, action, operator/trade, outcome/risk event까지 연결한다.
4. Phase 23 `snapshot_id`/`recommendation_id`와 Phase 26 `candidate_id`/`attribution_event_id`/ledger event를 변경하지 않고 참조한다.
5. benchmark excess, absolute, net execution, MAE/MFE, exposure, turnover, risk-rule attribution, denominator report를 표준 출력으로 정의한다.
6. 장기 실행 replay의 cancellation, resume, checkpoint, idempotence를 계약화한다.
7. stale state, dirty worktree, misleading success output, malformed input, cancel/resume, repeated interruptions, hung commands를 failing-first probe로 고정한다.

## 비목표

1. 기존 시그널 백테스트를 대체하지 않는다.
2. legacy snapshot을 native v4 verbatim 또는 recompute 가능 데이터로 승격하지 않는다.
3. 실제 LLM 호출, broker 주문, portfolio mutation, data/config/source 파일 변경을 요구하지 않는다.
4. prompt injection, external vendor license enforcement, broker secret handling은 이 문서의 fixture 범위 밖이다. 해당 class는 Phase 23 redaction과 execution adapter 문서에서 다루며 여기서는 N/A다.

## 선행 계약

| 계약 | Phase 27에서 소비하는 부분 |
| --- | --- |
| 기존 시그널 백테스트 | signal-only backtest는 기존 독립 레이어로 유지한다. |
| [Phase 22 측정 계약](phase22-measurement-contract.md) | entry/exit session, benchmark excess, absolute return, net execution, `pending`/`matured`/`insufficient_data`/`insufficient_context`. |
| [Phase 23 snapshot 재현성](phase23-snapshot-reproducibility.md#snapshot-v4-envelope) | snapshot envelope, recommendation record, deterministic hash, raw prompt/result retention, data cutoff. |
| [Phase 23 recommendation record](phase23-snapshot-reproducibility.md#recommendation-record) | replay input/output 경계와 fixed perspective order. |
| [Phase 23 legacy compatibility](phase23-snapshot-reproducibility.md#legacy-snapshot-compatibility) | legacy는 audit-only이며 native v4로 승격 금지. |
| [Phase 26 identity 계약](phase26-recommendation-attribution.md#identity-계약) | `candidate_id`, `recommendation_id`, `attribution_event_id`, `portfolio_trade_id`, `order_id` 연결. |
| [Phase 26 action taxonomy](phase26-recommendation-attribution.md#action-taxonomy) | `BUY`, `SELL`, `HOLD`, `BLOCKED`, `CANDIDATE_REJECTED` denominator 보존. |
| [Phase 26 ledger event schema](phase26-recommendation-attribution.md#ledger-event-schema) | append-only event stream과 immutable hash. |
| [Phase 26 denominator eligibility](phase26-recommendation-attribution.md#denominator-eligibility) | 체결 BUY만 denominator로 보는 선택 편향 차단. |

## Replay modes

| mode | 질문 | 필수 입력 | LLM 호출 | 산출물 |
| --- | --- | --- | --- | --- |
| `verbatim` | 저장된 입력과 raw/parsed 결과를 같은 순서로 다시 읽으면 동일한 recommendation/ledger를 만들 수 있는가 | native v4 snapshot, raw prompt, raw provider result 또는 code-based raw token, parser/config/scorer version, data cutoff | 금지 | stored output과 replayed parsed output/hash 비교 |
| `outcome` | 당시 추천과 operator/trade가 Phase 22 horizon에서 어떤 결과를 냈는가 | Phase 22 price/benchmark/corporate action/calendar provenance, Phase 26 denominator | 금지 | horizon별 decision/execution/selection outcome |
| `recompute` | 같은 cutoff 입력으로 현재 provider/model/parser를 다시 돌리면 결정이 얼마나 drift하는가 | native v4 input bundle, prompt bundle, provider eligibility, explicit cost budget | 허용 가능하지만 별도 opt-in | drift report, cost report, nondeterminism annotation |

`verbatim`과 `recompute`는 같은 것이 아니다. `verbatim`은 저장된 raw 결과를 재파싱하는 감사이고, `recompute`는 같은 cutoff 입력을 현재 실행 환경에서 새로 평가하는 실험이다. `outcome`은 LLM과 무관하게 가격, benchmark, execution, risk event를 성숙시키는 측정 replay다.

## Signal-only backtest preservation

기존 `src/backtest/engine.py` 경로는 `signal-only backtest`로 계속 남는다. 해당 레이어는 OHLCV와 `compute_signals()`를 사용해 `bull_votes`, `bear_votes`, stop loss, cash floor, slippage, commission을 시뮬레이션한다. Phase 27 full workflow replay는 이 결과를 대체하거나 합치지 않는다.

| layer | 입력 | 범위 | 허용 비교 |
| --- | --- | --- | --- |
| `signal_only_backtest` | OHLCV, signal config, optional forex/correlation | 코드 기반 technical signal 매매 시뮬레이션 | 전략 민감도, 비용 없는 fast regression |
| `full_workflow_replay` | Phase 23 snapshot, Phase 26 ledger, Phase 22 outcome inputs | 실제 추천 파이프라인 감사와 denominator 평가 | 결정 품질, 실행 품질, 선택 품질, drift |

두 레이어의 보고서는 서로 링크할 수 있지만 같은 denominator로 합산하면 실패다. `signal_only_backtest`가 성공해도 full workflow replay 성공으로 표시하면 `misleading_success_output` probe 실패다.

## Eligibility

### Native v4 eligibility

| replay mode | eligible 조건 | ineligible 조건 |
| --- | --- | --- |
| `verbatim` | Phase 23 native snapshot, `recommendation_id`, `data_cutoff_at`, prompt hash, redacted prompt messages, raw result 또는 code-based raw token, parser version, consensus/deliberation fields가 모두 있음 | raw prompt 없음, raw result hash-only인데 parser input 복원 불가, data cutoff 없음, fixed perspective order 훼손 |
| `outcome` | Phase 22 calendar/price/benchmark/corporate action provenance와 Phase 26 denominator eligibility가 있음 | target horizon 미성숙, benchmark context 없음, corporate action provenance 없음, malformed horizon |
| `recompute` | native v4 input bundle, data cutoff, prompt bundle, allowed provider/model, explicit budget, nondeterminism policy 있음 | legacy snapshot, missing cutoff, no budget, dirty worktree, provider unavailable, model disallowed |

### Legacy eligibility

Legacy fixture는 audit overlay만 가능하다. raw prompt, raw provider result, parser version, data cutoff, market context, candidate universe가 없으면 `verbatim` 또는 `recompute`를 주장하지 않는다. legacy record는 `legacy_audit_only=true`, `verbatim_eligible=false`, `recompute_eligible=false`를 명시해야 한다.

## Full workflow state machine

Replay state는 append-only evidence를 읽고 deterministic transition assertion을 수행한다. 상태 전이는 Phase 23 recommendation record와 Phase 26 ledger ID를 참조한다.

| state | input refs | output refs | required assertion |
| --- | --- | --- | --- |
| `RUN_CREATED` | replay request, mode, budget, worktree cleanliness proof | `replay_run_id`, first checkpoint | mode와 scope가 고정되고 dirty worktree면 recompute가 시작되지 않는다. |
| `UNIVERSE_BUILT` | Phase 23 `candidate_universe`, Phase 26 `CANDIDATE_SEEN` | `universe_id`, `candidate_id[]` | members hash와 candidate seen count가 denominator와 일치한다. |
| `CANDIDATE_SELECTED` | selection metadata, `CANDIDATE_SELECTED`/`CANDIDATE_REJECTED` | selected/rejected candidate refs | 탈락 후보가 사라지지 않는다. |
| `SIGNAL_EVALUATED` | `signals`, signal engine version | signal replay section | `bull_votes`, `bear_votes`, threshold, `trailing_stop_10pct`가 보존된다. |
| `PERSPECTIVE_REPLAYED` | fixed order `kwangsoo`, `ouroboros`, `quant`, `macro`, `value`; raw/parsed results | per-perspective replay result | provider failure는 `N/A`로 남고 perspective가 삭제되지 않는다. |
| `CONSENSUS_REPLAYED` | `vote_summary`, scorer version, weights | final consensus hash | `BUY`, `SELL`, `HOLD`, `DIVIDED`, `INSUFFICIENT`, `N/A` count가 일치한다. |
| `DELIBERATION_REPLAYED` | `initial_consensus`, `deliberation` | before/after consensus refs | Phase 23 `initial_consensus`와 Phase 26 action이 연결된다. |
| `RISK_GATE_REPLAYED` | `portfolio_state`, `risk_state`, Phase 26 `risk_component` | `BLOCKED` or actionable result | cash floor, concentration, correlation, stale quote, FX degradation attribution이 구조화된다. |
| `ACTION_EMITTED` | consensus, action plan, Phase 26 action taxonomy | `RECOMMENDATION_EMITTED` | BUY/SELL/HOLD/BLOCKED/CANDIDATE_REJECTED 중 하나이며 HOLD는 trade를 만들지 않는다. |
| `OPERATOR_DECISION_REPLAYED` | `operator_decision` | `OPERATOR_DECISION_RECORDED` | accepted/rejected/ignored/partial_execution/not_applicable가 recommendation action을 바꾸지 않는다. |
| `TRADE_LINKED` | `ORDER_LINKED`, `FILL_RECORDED`, portfolio hashes | `portfolio_trade_id`, `order_id`, `fill_id` | idempotency key 중복은 같은 order로 수렴한다. |
| `OUTCOME_REPLAYED` | Phase 22 entry/exit, Phase 26 `OUTCOME_MATURED` | outcome metrics | stale latest close가 N-session 결과를 대체하지 않는다. |
| `RISK_EVENT_REPLAYED` | portfolio alerts, risk rules, close events | `STOP_LOSS`, `TRAILING_STOP`, risk attribution | risk event는 outcome과 별도 timestamp/provenance를 가진다. |
| `REPORT_WRITTEN` | all replay sections | report hashes | denominator와 failure states가 함께 표시된다. |

## Inputs

```json
{
  "schema_version": "v4.full_workflow_replay.phase27.1",
  "replay_run_id": "replay_v4_phase27_fixture",
  "mode": "verbatim",
  "snapshot_ref": {
    "snapshot_id": "snap_v4_0a2f8e16c90db7a3e2d1",
    "snapshot_content_hash": "sha256:content-fixture"
  },
  "ledger_ref": {
    "ledger_id": "ledger_v4_phase26_fixture",
    "last_event_hash": "sha256:ledger-tail-fixture"
  },
  "scope": {
    "recommendation_ids": ["rec_v4_7f3c2a99d1f04e18a43b"],
    "candidate_ids": ["cand_v4_241d2519920a4d36d3da"],
    "horizons": [5, 20]
  },
  "reproducibility": {
    "canonical_json_version": "phase23-canonical-json.1",
    "parser_version": "perspective-parser-v2026.08",
    "scorer_version": "consensus-scorer-v2026.08",
    "sizer_version": "portfolio-sizer-v2026.08"
  },
  "data_cutoff": {
    "decision_data_cutoff_at": "2026-06-02T10:00:00+09:00",
    "max_source_as_of": "2026-06-02T10:00:00+09:00",
    "allow_future_data": false
  },
  "recompute_policy": {
    "enabled": false,
    "provider": "not_applicable",
    "model": "not_applicable",
    "max_cost_usd": 0,
    "temperature": "not_applicable",
    "nondeterminism_note_required": true
  },
  "long_running": {
    "checkpoint_every_events": 50,
    "resume_from_checkpoint": null,
    "cancel_token": "cancel_v4_fixture",
    "idempotency_key": "idem_phase27_fixture_1"
  }
}
```

## Outputs

Replay output is a report envelope plus per-mode sections. It never mutates source snapshot, attribution ledger, portfolio, config, or data files.

| output | required fields |
| --- | --- |
| `replay_summary` | `replay_run_id`, `mode`, `state`, `started_at`, `completed_at`, `checkpoint_count`, `input_hash`, `output_hash` |
| `eligibility` | `verbatim_eligible`, `outcome_eligible`, `recompute_eligible`, `ineligible_reasons[]` |
| `state_transitions[]` | state name, input refs, output refs, assertion result, checkpoint id |
| `verbatim_report` | parsed equality, hash equality, perspective order, consensus/deliberation equality |
| `outcome_report` | Phase 22 horizon states and metrics |
| `recompute_report` | drift matrix, cost, provider/model, nondeterminism warning |
| `failure_states[]` | probe name, severity, expected result, observed result |
| `denominator_report` | decision, execution, selection cohort counts and exclusions |

## Reports

### Outcome metrics

| metric | denominator | rule |
| --- | --- | --- |
| `gross_benchmark_excess_return_N` | Phase 26 decision quality denominator where Phase 22 context is sufficient | primary decision-quality metric |
| `gross_absolute_return_N` | same recommendation outcome where instrument price path is sufficient | auxiliary absolute move |
| `net_execution_return_N` | execution quality denominator with fill/order linkage | secondary execution metric only |
| `net_execution_benchmark_excess_return_N` | execution quality denominator with benchmark context | execution quality relative to benchmark |
| `MAE_N` | recommendations with path data from entry to exit | worst adverse excursion after entry |
| `MFE_N` | recommendations with path data from entry to exit | best favorable excursion after entry |
| `exposure` | execution quality denominator | notional and portfolio weight over time |
| `turnover` | execution quality denominator | traded notional / average portfolio value |
| `risk_rule_attribution` | all actions with `risk_component` | cash floor, concentration, correlation, stale quote, FX degradation, blocked market context |

### Denominator report

The denominator report must include all five Phase 26 cohorts: emitted `BUY`, emitted `SELL`, emitted `HOLD`, emitted `BLOCKED`, and `CANDIDATE_REJECTED`. It must show:

1. `decision_quality_total` including selected, blocked, held, sold, and rejected denominator members.
2. `execution_quality_total` only where execution intent exists.
3. `selection_quality_total` including selected and rejected candidates.
4. `excluded_from_primary_reason` only for structural invalidity, duplicate correction superseded, or insufficient measurement context.
5. `blocked_or_rejected_preserved=true` for `BLOCKED` and `CANDIDATE_REJECTED`.

## Reproducibility

1. Canonical JSON uses Phase 23 key ordering, array order preservation, redaction-before-hash, and hash-field exclusion.
2. Replay must store `input_hash`, `checkpoint_hash`, and `output_hash` using `sha256:<lowercase hex>`.
3. `verbatim` replay compares stored parsed results and recomputed parser output from retained raw text. It does not call the provider.
4. `outcome` replay uses only source values whose `as_of <= decision_data_cutoff_at` for decision inputs and Phase 22 allowed outcome data for future price measurement.
5. `recompute` replay must write provider, model, prompt bundle, temperature or sampling policy, run count, random seed if supported, token count, and cost.
6. LLM non-determinism is never hidden. If two recompute runs differ, the output is `drift_detected`, not flaky success.
7. Cost is bounded before recompute starts. Missing budget means `recompute_eligible=false`.

## Long-running execution

Replay can be long-running because it may scan many snapshots, ledger events, horizons, price paths, and optional recompute calls. The implementation must support cancellation, resume, checkpoint, and idempotence before any real replay executor is accepted.

| concern | contract |
| --- | --- |
| cancellation | A cancel token moves the run to `cancelled` after the current atomic event, writes a checkpoint, and does not mark success. |
| resume | Resume requires the same `input_hash`, mode, scope, and idempotency key. Mismatch fails with `resume_input_mismatch`. |
| checkpoint | Each checkpoint stores completed state, last entity ref, last ledger hash, output section hashes, and failure probes observed so far. |
| idempotence | Re-running the same request with the same idempotency key returns the existing complete or cancelled run instead of duplicating reports. |
| repeated interruptions | More than one interruption resumes from the latest valid checkpoint and proves skipped states by hash, not by log text. |
| hung commands | A per-stage heartbeat and timeout convert the stage to `hung_command_detected`; misleading success output is forbidden. |

## Failure states

| probe | detection rule | expected result |
| --- | --- | --- |
| `stale_state` | decision input has `source.as_of > emitted_at`, stale source lacks affected fields, or latest close replaces Phase 22 N-session exit | fail replay QA |
| `dirty_worktree` | recompute mode starts while source/config/data worktree differs from declared input hash or has untracked executor-affecting files | block recompute before provider call |
| `misleading_success_output` | output says success while any required state is skipped, pending, cancelled, stale, or hung | fail report validation |
| `malformed_input` | invalid JSON, missing schema_version, invalid horizon, duplicate ID, broken hash chain, HOLD with order, BLOCKED missing risk reason | fail before replay state machine advances |
| `cancel_resume` | cancellation fails to write checkpoint or resume changes input hash | fail long-running contract |
| `repeated_interruptions` | second or later resume repeats completed side-effect or skips assertion without hash proof | fail idempotence contract |
| `hung_commands` | stage heartbeat exceeds timeout and process still reports running or success | mark run `failed` with `hung_command_detected` |

Other failure classes are N/A for this PRD unless a later implementation adds new external surfaces. In particular, no actual replay, provider call, browser, broker, or network fixture is required here.

## Fixtures

### F1. Native happy verbatim fixture

```json
{
  "fixture": "native_happy_verbatim",
  "mode": "verbatim",
  "snapshot_id": "snap_v4_0a2f8e16c90db7a3e2d1",
  "recommendation_id": "rec_v4_7f3c2a99d1f04e18a43b",
  "data_cutoff_at": "2026-06-02T10:00:00+09:00",
  "raw_prompt_available": true,
  "raw_results_available": true,
  "fixed_perspective_order": ["kwangsoo", "ouroboros", "quant", "macro", "value"],
  "expected_state": "REPORT_WRITTEN",
  "expected_verbatim_eligible": true,
  "expected_recompute_eligible": false,
  "expected_assertions": {
    "parsed_hash_equal": true,
    "consensus_hash_equal": true,
    "deliberation_equal": true
  }
}
```

### F2. Native happy outcome fixture

```json
{
  "fixture": "native_happy_outcome",
  "mode": "outcome",
  "recommendation_id": "rec_v4_62ec99717d763a8550d0",
  "candidate_id": "cand_v4_241d2519920a4d36d3da",
  "action": "BUY",
  "horizon": 5,
  "entry_session": "2026-06-03",
  "target_exit_session": "2026-06-10",
  "instrument_entry_tr_close": 100000.0,
  "instrument_exit_tr_close": 106000.0,
  "benchmark_entry_tr_close": 2500.0,
  "benchmark_exit_tr_close": 2575.0,
  "cost_model_version": "kr-equity-v2026.1",
  "execution_fill_ratio": 0.4,
  "expected_metrics": {
    "gross_absolute_return_5": 0.06,
    "gross_benchmark_excess_return_5": 0.03,
    "net_execution_return_5": 0.0569,
    "net_execution_benchmark_excess_return_5": 0.0269
  },
  "expected_denominator": {
    "decision_quality_denominator": true,
    "execution_quality_denominator": true,
    "selection_quality_denominator": true
  }
}
```

### F3. Legacy audit-only fixture

```json
{
  "fixture": "legacy_audit_only_no_verbatim_no_recompute",
  "legacy_snapshot_path": "data/snapshots/2026-08-05.json",
  "legacy_audit_only": true,
  "raw_prompt_available": false,
  "raw_results_available": false,
  "decision_data_cutoff_at": "unknown",
  "market_context_state": "insufficient_context",
  "expected_verbatim_eligible": false,
  "expected_recompute_eligible": false,
  "expected_outcome_state": "audit_overlay_only",
  "must_not_claim": ["verbatim", "recompute", "native_v4"]
}
```

### F4. Recompute drift fixture

```json
{
  "fixture": "native_recompute_drift",
  "mode": "recompute",
  "snapshot_id": "snap_v4_0a2f8e16c90db7a3e2d1",
  "recommendation_id": "rec_v4_7f3c2a99d1f04e18a43b",
  "data_cutoff_at": "2026-06-02T10:00:00+09:00",
  "recompute_policy": {
    "enabled": true,
    "provider": "codex",
    "model": "gpt-5.1-codex",
    "max_cost_usd": 1.25,
    "nondeterminism_note_required": true
  },
  "stored_consensus_verdict": "BUY",
  "recomputed_consensus_verdict": "HOLD",
  "expected_state": "REPORT_WRITTEN",
  "expected_recompute_result": "drift_detected",
  "expected_failure": false
}
```

### F5. Cancellation and resume fixture

```json
{
  "fixture": "cancel_resume_checkpoint_idempotence",
  "mode": "outcome",
  "idempotency_key": "idem_phase27_cancel_resume_1",
  "cancel_after_state": "SIGNAL_EVALUATED",
  "checkpoint_id": "chk_v4_phase27_0002",
  "resume_input_hash": "sha256:input-fixture",
  "expected_cancelled_state": "cancelled",
  "expected_resume_state": "REPORT_WRITTEN",
  "expected_duplicate_run_count": 0
}
```

## Manual read trace

Task 6 verification must manually read these paths before claiming completion:

1. `AGENTS.md` for repository constraints.
2. `docs/specs/v4/prds/phase22-measurement-contract.md` for Phase 22 outcome metrics and stale-state failure.
3. `docs/specs/v4/prds/phase23-snapshot-reproducibility.md` for snapshot envelope, recommendation record, raw prompt/result, legacy compatibility.
4. `docs/specs/v4/prds/phase26-recommendation-attribution.md` for IDs, action taxonomy, ledger events, denominator.
5. Existing v3 backtest PRD and `src/backtest/engine.py` to preserve signal-only backtest as a distinct layer.
6. `src/common.py`, `src/consensus/voter.py`, `src/consensus/deliberator.py`, and `src/portfolio/sizer.py` or equivalent exploration evidence for the full workflow state names.

## Deterministic uv assertions

Implementation tasks downstream must add a deterministic `uv run` assertion surface before real replay. The first target is JSON/state transition validation only, not actual replay.

Required assertions:

1. Fixture JSON parses with the standard library.
2. `mode` decides eligibility exactly as documented.
3. State transitions follow the table order and cannot skip required states.
4. Phase 26 hash chain and denominator references are read-only and not rewritten.
5. `cancelled` never reports success.
6. Re-running a completed fixture with the same idempotency key returns the same `replay_run_id` and `output_hash`.
7. `stale_state`, `dirty_worktree`, `misleading_success_output`, `malformed_input`, `cancel_resume`, `repeated_interruptions`, and `hung_commands` probes fail as specified.

## Acceptance criteria

1. The PRD defines `verbatim`, `outcome`, and `recompute` replay as separate modes with distinct eligibility, inputs, outputs, cost, and nondeterminism rules.
2. Full workflow state machine covers universe/candidate selection, signal, five perspectives, consensus/deliberation, portfolio/risk constraints, action, operator/trade, outcome/risk event, and links to Phase 23/26 IDs.
3. Existing signal-only backtest is explicitly preserved as a separate existing layer and is not merged into full workflow replay.
4. Reports include benchmark excess, absolute, net execution, MAE/MFE, exposure, turnover, risk-rule attribution, and denominator definitions.
5. Fixtures cover native happy outcome, native happy verbatim, legacy audit-only without verbatim/recompute claims, recompute drift, and cancellation/resume/checkpoint/idempotence.
6. Failure probes include stale state, dirty worktree, misleading success output, malformed input, cancel/resume, repeated interruptions, and hung commands.
7. The PRD requires manual read trace and deterministic `uv run` JSON/state transition assertions, but does not require or perform actual replay.
