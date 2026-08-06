# PRD 01: Perspective Candidate Contract
> **상태**: 📝 초안
> **SPEC 참조**: [v6 SPEC](../SPEC.md)

## 문서 범위

이 문서는 Trading Oracle에 새 투자 관점 후보를 제안할 때 필요한 계약을 정의한다. 후보는 기존 `kwangsoo`, `ouroboros`, `quant`, `macro`, `value` 관점과 같은 입력 묶음을 받을 수 있지만, 같은 근거를 다른 말로 반복하면 안 된다.

이 문서는 v6의 로컬 PRD 01이다. 다른 버전 문서의 산출 여부와 무관하게 이 계약만으로 후보 제안서, 검증 fixture, parser를 작성할 수 있어야 한다.

## 문제

현재 합의기는 `src/consensus/voter.py`에서 다섯 관점을 고정 순서로 병렬 실행한다. 각 관점은 `src/perspectives/base.py`의 `PerspectiveInput`을 받고 `PerspectiveResult`를 반환한다.

기존 관점의 책임은 이미 나뉘어 있다.

| 관점 | 현재 목적 | 중복 금지 기준 |
| --- | --- | --- |
| `kwangsoo` | 추적 손절매, 주도주, 모멘텀, 자금관리 | 손절가와 추세 추종만 다른 문장으로 반복하는 후보는 거절한다. |
| `ouroboros` | 희석, 내부자 거래, 기관 수급, 재무 리스크 | 포렌식 리스크 목록만 재배열하는 후보는 거절한다. |
| `quant` | 코드 기반 6 시그널 verdict와 LLM reasoning | 같은 6 시그널 투표를 다시 계산하는 후보는 거절한다. |
| `macro` | 금리, 환율, 섹터 사이클, 인과 체인 | 같은 매크로 변수와 인과 그래프만 다시 설명하는 후보는 거절한다. |
| `value` | PER, PBR, 배당, 상대 밸류에이션 | 같은 valuation threshold만 바꾸는 후보는 거절한다. |

새 후보는 합의 표에 한 표를 더하는 장식이 아니다. 후보는 기존 다섯 관점이 틀리는 경우를 독립 가설로 설명하고, 그 가설이 관측 가능한 입력과 출력으로 검증 가능해야 한다.

## 목표

1. 후보 관점의 목적, 독립 가설, 허용 입력, 출력 schema를 고정한다.
2. 기존 다섯 관점과의 overlap을 수치와 텍스트 근거로 드러낸다.
3. forbidden duplication을 계약 위반으로 정의한다.
4. 비용과 latency 예산을 후보 제안 시점에 기록한다.
5. owner와 version을 붙여 후보 변경 이력을 비교 가능하게 한다.
6. 채택이 아니라 제안서 접수, 거절, 평가 준비까지만 다룬다.

## 비목표

1. 특정 후보를 정식 관점으로 채택하지 않는다.
2. 합의 weight, 승격, rollback, paper cohort 결과는 정의하지 않는다.
3. 기존 `ALL_PERSPECTIVES` 목록이나 제품 코드를 바꾸지 않는다.
4. 기존 다섯 관점의 prompt를 고치지 않는다.
5. 추천 성과 평가식이나 attribution ledger를 새로 정의하지 않는다.

## 후보 목적 계약

후보 목적은 한 문장으로 적되, 다음 네 요소를 모두 포함해야 한다.

| 요소 | 규칙 | 좋은 예 | 거절 예 |
| --- | --- | --- | --- |
| 오류 유형 | 기존 관점이 놓치는 실패를 말한다. | 갑작스러운 수요 붕괴 전 재고와 가격 전가력 악화를 감지한다. | 더 정확한 매수 신호를 만든다. |
| 독립 입력 | 기존 관점의 핵심 입력과 다른 관측값을 말한다. | 재고 회전일, 매출채권 회수일, ASP 변화율 | Bull vote, RSI, MACD |
| 행동 영향 | BUY, SELL, HOLD, N/A 중 어떤 판단을 바꿀 수 있는지 말한다. | BUY를 HOLD 또는 SELL로 낮출 수 있다. | 최종 점수를 높인다. |
| 검증 가능성 | fixture에서 재현 가능한 값을 말한다. | 같은 종목에서 quant BUY지만 working capital 악화로 HOLD | 전문가 감으로 판단 |

## 독립 가설 계약

후보는 `independent_hypothesis` 객체를 제출한다.

```json
{
  "hypothesis_id": "hyp_v6_working_capital_quality_001",
  "summary": "재고 회전일 증가와 매출채권 회수 지연은 가격 모멘텀보다 먼저 이익 품질 악화를 드러낸다.",
  "error_mode_explained": "기존 관점이 모멘텀과 밸류에이션을 좋게 보지만 다음 실적에서 마진이 꺾이는 경우",
  "novel_signal_family": "working_capital_quality",
  "primary_observations": ["inventory_days_change_4q", "receivables_days_change_4q", "gross_margin_delta_4q"],
  "expected_disagreement": {
    "with_existing": ["quant", "value"],
    "direction": "downgrade_buy_to_hold_or_sell"
  },
  "falsifiable_claim": "offline fixture에서 quant BUY 후보 중 working capital 악화 구간의 이후 20 session excess return이 baseline보다 낮아야 한다."
}
```

필수 규칙은 다음과 같다.

| field | required | type | rule |
| --- | --- | --- | --- |
| `hypothesis_id` | yes | string | `hyp_v6_` prefix와 snake case suffix를 쓴다. |
| `summary` | yes | string | 한 문장, 200자 이내. |
| `error_mode_explained` | yes | string | 기존 관점이 실패하는 경우를 구체적으로 쓴다. |
| `novel_signal_family` | yes | string | 기존 다섯 관점의 핵심 family와 달라야 한다. |
| `primary_observations` | yes | array of string | 최소 2개, 최대 8개. |
| `expected_disagreement.with_existing` | yes | array of string | 기존 관점 이름 중 1개 이상. |
| `expected_disagreement.direction` | yes | enum string | `downgrade_buy_to_hold_or_sell`, `upgrade_hold_to_buy`, `upgrade_hold_to_sell`, `na_boundary_only` 중 하나. |
| `falsifiable_claim` | yes | string | 수치 검증으로 참 또는 거짓을 판정할 수 있어야 한다. |

## 입력 schema

후보는 기존 `PerspectiveInput` 필드를 읽을 수 있다. 단, 후보 제안서에서 어떤 필드가 필수인지 명시해야 한다.

| input field | type | candidate rule |
| --- | --- | --- |
| `ticker` | string | 항상 허용. |
| `name` | string | 항상 허용. |
| `ohlcv` | dataframe | 가격 기반 후보는 어떤 파생값을 만들지 명시한다. 단순 6 시그널 복제는 금지한다. |
| `signals` | object | 참고값으로만 허용한다. `signals.verdict`, `bull_votes`, `bear_votes`를 주 판단으로 쓰면 거절한다. |
| `fundamentals` | object | PER, PBR, 배당만으로 판단하면 가치 관점 복제다. 새 회계 품질, 성장 품질, 현금흐름 품질 같은 별도 관측값이 필요하다. |
| `position` | object or null | 보유 포지션 대응만 판단하면 `kwangsoo` 복제다. |
| `market_context` | object | macro 후보는 기존 macro와 다른 관측 family를 증명해야 한다. |
| `config` | object | provider, budget, timeout 같은 실행 정책만 읽는다. secret 값은 읽거나 출력하지 않는다. |
| `web_context` | object | 외부 텍스트를 그대로 근거로 쓰면 안 된다. 출처 품질 검증 없이 새로운 관점 목적이 될 수 없다. |
| `fx_signal` | object | 환율 영향만으로 판단하면 macro 복제다. |

후보가 위 필드 밖의 입력을 요구하면 다음 shape로 선언한다.

```json
{
  "required_extra_inputs": [
    {
      "name": "working_capital_series",
      "type": "object",
      "source_contract": "manual_fixture_or_future_adapter",
      "required_for_verdict": true,
      "missing_behavior": "N/A",
      "freshness_budget_hours": 168
    }
  ]
}
```

`source_contract`가 없거나 freshness budget이 없으면 후보는 접수되지 않는다.

## 출력 schema

후보 출력은 `PerspectiveResult`와 호환되어야 한다.

```json
{
  "perspective": "working_capital_quality",
  "verdict": "HOLD",
  "confidence": 0.71,
  "reasoning": [
    "재고 회전일이 4분기 연속 증가했고 매출채권 회수일도 18일 늘었다.",
    "가격 모멘텀은 좋지만 이익 품질 악화가 다음 실적 하향 위험을 높인다."
  ],
  "reason": "운전자본 악화가 quant BUY를 HOLD로 낮춘다.",
  "action": {
    "type": "hold",
    "watch": "다음 분기 재고 회전일과 gross margin"
  },
  "extra": {
    "contract_version": "perspective_candidate_contract.1",
    "candidate_version": "working_capital_quality.0.1",
    "hypothesis_id": "hyp_v6_working_capital_quality_001",
    "overlap_score": 0.28,
    "novel_evidence": ["inventory_days_change_4q", "receivables_days_change_4q"]
  }
}
```

| field | required | type | rule |
| --- | --- | --- | --- |
| `perspective` | yes | string | 기존 이름과 충돌하지 않는다. snake case. |
| `verdict` | yes | enum string | `BUY`, `SELL`, `HOLD`, `N/A` 중 하나. |
| `confidence` | yes | number | `0.0 <= confidence <= 1.0`. `N/A`이면 `0.0`. |
| `reasoning` | yes | array of string | 최소 1개. 입력값과 가설을 연결한다. |
| `reason` | yes | string | 한 줄 요약. |
| `action.type` | yes | enum string | `buy`, `sell`, `hold`, `none` 중 하나. `verdict="N/A"`이면 `none`. |
| `extra.contract_version` | yes | string | 이 문서의 계약 버전. 첫 값은 `perspective_candidate_contract.1`. |
| `extra.candidate_version` | yes | string | 후보 고유 version. |
| `extra.hypothesis_id` | yes | string | 제출한 독립 가설과 일치. |
| `extra.overlap_score` | yes | number | `0.0 <= overlap_score <= 1.0`. 낮을수록 독립적이다. |
| `extra.novel_evidence` | yes | array of string | 기존 관점과 다른 핵심 관측값. |

## N/A schema

후보가 판단할 수 없을 때는 실패를 숨기지 않고 `N/A`를 반환한다.

```json
{
  "perspective": "working_capital_quality",
  "verdict": "N/A",
  "confidence": 0.0,
  "reasoning": ["working_capital_series 입력이 없어 독립 가설을 검증할 수 없다."],
  "reason": "필수 운전자본 입력 없음",
  "action": {"type": "none"},
  "extra": {
    "contract_version": "perspective_candidate_contract.1",
    "candidate_version": "working_capital_quality.0.1",
    "hypothesis_id": "hyp_v6_working_capital_quality_001",
    "not_applicable_reason": "missing_required_extra_input",
    "missing_inputs": ["working_capital_series"],
    "overlap_score": 0.28,
    "novel_evidence": []
  }
}
```

`N/A`는 낮은 확신의 HOLD가 아니다. 입력 부족, schema 불일치, budget 초과, parser 실패, 독립 가설 미검증은 모두 `N/A`로 남긴다.

## Overlap and forbidden duplication

후보 제안서는 기존 관점별 overlap matrix를 포함해야 한다.

| compared_to | max_overlap_score | forbidden duplication |
| --- | --- | --- |
| `kwangsoo` | 0.40 | 추적 손절매, 주도주, 2 percent 자금관리만으로 verdict를 만들면 거절. |
| `ouroboros` | 0.40 | 희석, 내부자 매도, 기관 수급, 부채 리스크만 나열하면 거절. |
| `quant` | 0.25 | 6 시그널 투표, RSI, MACD, EMA, BB, momentum 조합을 주 판단으로 쓰면 거절. |
| `macro` | 0.40 | 금리, 환율, 섹터 사이클, 기존 인과 체인만 쓰면 거절. |
| `value` | 0.35 | PER, PBR, 배당, PEG threshold만 쓰면 거절. |

Overlap 계산은 최소 두 축을 쓴다.

1. `input_overlap`: 후보 핵심 관측값 중 기존 관점의 핵심 입력과 겹치는 비율.
2. `verdict_correlation_proxy`: fixture에서 기존 관점 verdict와 같은 방향으로 움직인 비율.

최종 `overlap_score`는 `max(input_overlap, verdict_correlation_proxy)`로 시작한다. 후보가 왜 다르게 판단했는지 설명하는 `disagreement_cases`가 있으면 평가 문서에서 낮출 수 있지만, 이 PRD 01에서는 조정식을 정하지 않는다.

## Cost and latency budgets

후보는 제안 시점에 예산을 선언한다.

| budget field | required | default ceiling | rejection rule |
| --- | --- | --- | --- |
| `max_wall_ms_per_ticker` | yes | 6000 | 0 이하, 숫자 아님, 6000 초과면 접수 거절. |
| `max_llm_calls_per_ticker` | yes | 1 | 1 초과면 접수 거절. 코드 전용 후보는 0. |
| `max_prompt_tokens_per_ticker` | yes | 2500 | LLM 후보가 2500 초과면 접수 거절. |
| `max_output_tokens_per_ticker` | yes | 900 | 900 초과면 접수 거절. |
| `max_extra_fetches_per_ticker` | yes | 1 | 1 초과면 접수 거절. |
| `cache_ttl_hours` | yes if extra fetch exists | 168 | 없거나 0 이하이면 접수 거절. |
| `timeout_behavior` | yes | `N/A` | timeout이 BUY, SELL, HOLD로 이어지면 접수 거절. |

Budget 초과는 후보 품질 문제가 아니라 계약 위반이다. 초과 시 `N/A`와 `not_applicable_reason="budget_exceeded"`를 남긴다.

## Owner and version

모든 후보는 소유자와 version을 가진다.

```json
{
  "candidate_identity": {
    "candidate_id": "pcand_v6_working_capital_quality",
    "candidate_name": "working_capital_quality",
    "owner": "research_owner_or_team_handle",
    "candidate_version": "working_capital_quality.0.1",
    "contract_version": "perspective_candidate_contract.1",
    "created_at": "2026-08-06T00:00:00+09:00",
    "change_summary": "initial candidate proposal"
  }
}
```

`owner`는 비어 있으면 안 된다. `candidate_version`은 입력, prompt, parser, budget, 독립 가설 중 하나라도 바뀌면 증가한다.

## Rejection criteria

다음 중 하나라도 참이면 후보를 거절한다.

| rejection_code | condition |
| --- | --- |
| `DUPLICATES_EXISTING_PERSPECTIVE` | overlap score가 해당 관점 ceiling을 넘거나 forbidden duplication에 걸린다. |
| `NO_INDEPENDENT_HYPOTHESIS` | falsifiable claim이 없거나 오류 유형이 모호하다. |
| `UNTYPED_INPUT_OR_OUTPUT` | 입력 또는 출력 schema가 없거나 타입이 모호하다. |
| `MALFORMED_VERDICT` | verdict가 `BUY`, `SELL`, `HOLD`, `N/A` 밖이다. |
| `MALFORMED_CONFIDENCE` | confidence가 숫자가 아니거나 0.0에서 1.0 밖이다. |
| `MALFORMED_NA` | `N/A`인데 confidence가 0.0이 아니거나 action이 `none`이 아니다. |
| `BUDGET_EXCEEDED_BY_DESIGN` | 제안 budget이 ceiling을 넘는다. |
| `MISSING_OWNER_OR_VERSION` | owner, candidate version, contract version 중 하나가 없다. |
| `ADOPTS_CANDIDATE_DIRECTLY` | 평가 없이 정식 관점 추가를 요구한다. |

## Candidate template

새 후보 제안은 아래 template을 채운다.

```json
{
  "candidate_identity": {
    "candidate_id": "pcand_v6_<name>",
    "candidate_name": "<snake_case_name>",
    "owner": "<owner_handle>",
    "candidate_version": "<name>.0.1",
    "contract_version": "perspective_candidate_contract.1",
    "created_at": "<iso8601_with_timezone>",
    "change_summary": "initial candidate proposal"
  },
  "purpose": {
    "one_sentence": "<what error this candidate catches>",
    "decision_impact": "<which verdict can change and how>"
  },
  "independent_hypothesis": {
    "hypothesis_id": "hyp_v6_<name>_001",
    "summary": "<falsifiable claim summary>",
    "error_mode_explained": "<where existing perspectives fail>",
    "novel_signal_family": "<family>",
    "primary_observations": ["<field_a>", "<field_b>"],
    "expected_disagreement": {
      "with_existing": ["<existing_perspective>"],
      "direction": "downgrade_buy_to_hold_or_sell"
    },
    "falsifiable_claim": "<measurable claim>"
  },
  "input_contract": {
    "uses_perspective_input_fields": ["ticker", "name", "signals"],
    "required_extra_inputs": [],
    "missing_behavior": "N/A"
  },
  "output_contract": {
    "verdict_enum": ["BUY", "SELL", "HOLD", "N/A"],
    "confidence_range": [0.0, 1.0],
    "na_requires_confidence_zero": true,
    "na_requires_action_none": true
  },
  "overlap_matrix": [
    {"compared_to": "quant", "input_overlap": 0.10, "verdict_correlation_proxy": 0.20, "overlap_score": 0.20}
  ],
  "budget": {
    "max_wall_ms_per_ticker": 3000,
    "max_llm_calls_per_ticker": 0,
    "max_prompt_tokens_per_ticker": 0,
    "max_output_tokens_per_ticker": 0,
    "max_extra_fetches_per_ticker": 0,
    "timeout_behavior": "N/A"
  }
}
```

## Fixture A: happy independent candidate

```json
{
  "fixture_name": "happy_independent_working_capital_candidate",
  "candidate_identity": {
    "candidate_id": "pcand_v6_working_capital_quality",
    "candidate_name": "working_capital_quality",
    "owner": "research_accounting_quality",
    "candidate_version": "working_capital_quality.0.1",
    "contract_version": "perspective_candidate_contract.1",
    "created_at": "2026-08-06T00:00:00+09:00",
    "change_summary": "initial candidate proposal"
  },
  "purpose": {
    "one_sentence": "운전자본 악화로 모멘텀 BUY가 실적 하향 위험을 숨기는 경우를 잡는다.",
    "decision_impact": "quant BUY와 value BUY를 HOLD 또는 SELL로 낮출 수 있다."
  },
  "independent_hypothesis": {
    "hypothesis_id": "hyp_v6_working_capital_quality_001",
    "summary": "재고 회전일 증가와 매출채권 회수 지연은 가격 모멘텀보다 먼저 이익 품질 악화를 드러낸다.",
    "error_mode_explained": "가격 모멘텀과 낮은 PER은 좋지만 다음 실적에서 마진이 꺾이는 경우",
    "novel_signal_family": "working_capital_quality",
    "primary_observations": ["inventory_days_change_4q", "receivables_days_change_4q", "gross_margin_delta_4q"],
    "expected_disagreement": {
      "with_existing": ["quant", "value"],
      "direction": "downgrade_buy_to_hold_or_sell"
    },
    "falsifiable_claim": "quant BUY fixture 중 inventory_days_change_4q가 20 이상이고 gross_margin_delta_4q가 -3.0 이하인 표본의 20 session benchmark excess return이 quant BUY baseline보다 낮아야 한다."
  },
  "input_contract": {
    "uses_perspective_input_fields": ["ticker", "name", "fundamentals", "signals"],
    "required_extra_inputs": [
      {
        "name": "working_capital_series",
        "type": "object",
        "source_contract": "manual_fixture_or_future_adapter",
        "required_for_verdict": true,
        "missing_behavior": "N/A",
        "freshness_budget_hours": 168
      }
    ],
    "missing_behavior": "N/A"
  },
  "output_contract": {
    "verdict_enum": ["BUY", "SELL", "HOLD", "N/A"],
    "confidence_range": [0.0, 1.0],
    "na_requires_confidence_zero": true,
    "na_requires_action_none": true
  },
  "overlap_matrix": [
    {"compared_to": "kwangsoo", "input_overlap": 0.05, "verdict_correlation_proxy": 0.22, "overlap_score": 0.22},
    {"compared_to": "ouroboros", "input_overlap": 0.18, "verdict_correlation_proxy": 0.25, "overlap_score": 0.25},
    {"compared_to": "quant", "input_overlap": 0.10, "verdict_correlation_proxy": 0.20, "overlap_score": 0.20},
    {"compared_to": "macro", "input_overlap": 0.08, "verdict_correlation_proxy": 0.18, "overlap_score": 0.18},
    {"compared_to": "value", "input_overlap": 0.25, "verdict_correlation_proxy": 0.30, "overlap_score": 0.30}
  ],
  "budget": {
    "max_wall_ms_per_ticker": 3000,
    "max_llm_calls_per_ticker": 0,
    "max_prompt_tokens_per_ticker": 0,
    "max_output_tokens_per_ticker": 0,
    "max_extra_fetches_per_ticker": 0,
    "timeout_behavior": "N/A"
  },
  "expected_decision": {
    "accepted_for_evaluation": true,
    "rejection_code": null
  }
}
```

## Fixture B: rejected quant clone

```json
{
  "fixture_name": "rejected_quant_clone_candidate",
  "candidate_identity": {
    "candidate_id": "pcand_v6_quant_plus",
    "candidate_name": "quant_plus",
    "owner": "research_signals",
    "candidate_version": "quant_plus.0.1",
    "contract_version": "perspective_candidate_contract.1",
    "created_at": "2026-08-06T00:00:00+09:00",
    "change_summary": "initial candidate proposal"
  },
  "purpose": {
    "one_sentence": "기존 6 시그널 투표에 RSI 가중치를 더해 BUY 정확도를 높인다.",
    "decision_impact": "quant HOLD를 BUY로 높인다."
  },
  "independent_hypothesis": {
    "hypothesis_id": "hyp_v6_quant_plus_001",
    "summary": "RSI와 MACD를 더 크게 반영하면 quant보다 낫다.",
    "error_mode_explained": "quant가 약한 모멘텀을 놓치는 경우",
    "novel_signal_family": "technical_signal_reweighting",
    "primary_observations": ["signals.rsi.value", "signals.macd.histogram", "signals.bull_votes"],
    "expected_disagreement": {
      "with_existing": ["quant"],
      "direction": "upgrade_hold_to_buy"
    },
    "falsifiable_claim": "RSI와 MACD 가중치가 높으면 수익이 높다."
  },
  "input_contract": {
    "uses_perspective_input_fields": ["signals"],
    "required_extra_inputs": [],
    "missing_behavior": "N/A"
  },
  "output_contract": {
    "verdict_enum": ["BUY", "SELL", "HOLD", "N/A"],
    "confidence_range": [0.0, 1.0],
    "na_requires_confidence_zero": true,
    "na_requires_action_none": true
  },
  "overlap_matrix": [
    {"compared_to": "quant", "input_overlap": 0.92, "verdict_correlation_proxy": 0.88, "overlap_score": 0.92}
  ],
  "budget": {
    "max_wall_ms_per_ticker": 1000,
    "max_llm_calls_per_ticker": 0,
    "max_prompt_tokens_per_ticker": 0,
    "max_output_tokens_per_ticker": 0,
    "max_extra_fetches_per_ticker": 0,
    "timeout_behavior": "N/A"
  },
  "expected_decision": {
    "accepted_for_evaluation": false,
    "rejection_code": "DUPLICATES_EXISTING_PERSPECTIVE"
  }
}
```

## 검증 기준

PRD 01 parser는 다음을 확인해야 한다.

1. 문서 제목은 `# PRD 01: Perspective Candidate Contract`이다.
2. 바로 다음 줄에 초안 metadata가 정확히 한 번 있다.
3. 정식 채택을 뜻하는 표식은 없다.
4. 후보 template JSON이 parse된다.
5. happy fixture는 `accepted_for_evaluation=true`이고 모든 budget이 ceiling 이하다.
6. rejected quant clone fixture는 `overlap_score=0.92`로 quant ceiling 0.25를 넘고 `DUPLICATES_EXISTING_PERSPECTIVE`로 거절된다.
7. 모든 verdict enum은 `BUY`, `SELL`, `HOLD`, `N/A` 안에 있다.
8. 모든 confidence와 overlap score는 0.0에서 1.0 사이다.
9. `N/A` fixture는 confidence 0.0과 action `none`을 가진다.
10. owner, candidate version, contract version이 비어 있지 않다.
11. malformed probability, malformed budget, dirty duplicate, misleading purpose probe가 실패로 분류된다.

## Failure probes

| probe | mutation | expected result |
| --- | --- | --- |
| `malformed_probability` | confidence를 `1.4` 또는 문자열로 바꾼다. | `MALFORMED_CONFIDENCE` |
| `malformed_budget` | `max_wall_ms_per_ticker`를 `9000`으로 바꾼다. | `BUDGET_EXCEEDED_BY_DESIGN` |
| `malformed_na` | `verdict="N/A"`인데 confidence를 `0.3`으로 바꾼다. | `MALFORMED_NA` |
| `dirty_duplicate` | candidate name은 다르지만 primary observations가 quant와 같다. | `DUPLICATES_EXISTING_PERSPECTIVE` |
| `misleading_purpose` | purpose는 운전자본이라 쓰고 입력은 `signals`만 쓴다. | `NO_INDEPENDENT_HYPOTHESIS` |
| `direct_adoption` | `accepted_for_evaluation` 대신 정식 관점 추가를 요구한다. | `ADOPTS_CANDIDATE_DIRECTLY` |

## 독립성 판정

후보는 다음 조건을 모두 만족할 때 평가 대상으로만 접수된다.

1. 독립 가설이 기존 다섯 관점 중 적어도 하나와 의도적 disagreement를 만든다.
2. 핵심 관측값이 forbidden duplication에 걸리지 않는다.
3. output schema가 `PerspectiveResult`와 호환된다.
4. budget 초과 시 `N/A`로 닫힌다.
5. owner와 version이 명시되어 같은 이름의 후보 변경을 구분할 수 있다.

이 접수는 채택이 아니다. 후속 로컬 PRD에서 offline 평가, paper cohort, 합의 lifecycle을 별도로 검증하기 전까지 production 합의에는 들어가지 않는다.
