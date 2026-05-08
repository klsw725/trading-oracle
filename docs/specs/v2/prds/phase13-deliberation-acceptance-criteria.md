# PRD: Phase 13 Amendment — 숙의 변경 수용 기준 강화

> **SPEC 참조**: [SPEC.md §5-5](../SPEC.md#5-5-숙의-프롬프트-설계), [§5-6](../SPEC.md#5-6-숙의-결과-출력-형식)
> **상태**: 📝 초안
> **우선순위**: P1 — 숙의 합의 품질 보정
> **선행 조건**: Phase 13 숙의 합의 시스템 구현 완료

---

## 문제

Phase 13 숙의 합의는 분기/약한 합의 시 소수 측 관점에 다수 측 근거를 제시하고 재판정한다. 이 구조는 비용을 낮추고 합의 수렴을 유도하지만, 실제 운용에서는 소수 의견이 다수 의견으로 쉽게 흡수되어 `숙의 만장일치`, 특히 `숙의 만장일치 HOLD`가 과도하게 발생한다.

이 문제는 환경변수나 플래그로 숙의를 끄는 방식으로 해결하지 않는다. 숙의 기능은 유지하되, **관점의 verdict를 변경해도 되는 조건 자체를 강화**해야 한다.

---

## 목표

1. 숙의가 원래 독립 판정을 무분별하게 덮어쓰지 않도록 한다.
2. `quant`처럼 코드 기반으로 산출된 관점은 LLM 숙의가 verdict를 변경하지 못하게 한다.
3. 초기 투표와 숙의 후 투표를 모두 추적 가능하게 저장한다.
4. 초기부터 만장일치였던 경우와 숙의 후 수렴한 경우를 라벨에서 구분한다.
5. 기존 CLI/JSON 소비자는 top-level 최종 consensus 필드를 계속 사용할 수 있게 한다.

## 비목표

- 숙의 기능을 환경변수로 조절하거나 기본 비활성화하지 않는다.
- 단순히 UI 문구만 바꿔 문제를 숨기지 않는다.
- 전체 합의 시스템을 새 알고리즘으로 재작성하지 않는다.
- LLM 호출 수를 크게 늘리는 전원 재토론 구조는 이번 범위에 포함하지 않는다.

---

## 사용자 영향

### 현재

```
초기: BUY 1 / SELL 1 / HOLD 3
숙의 후: HOLD 5
출력: 숙의 만장일치 HOLD
```

사용자는 실제로는 초기 분기가 있었는데도 최종 화면만 보면 모든 관점이 독립적으로 HOLD에 동의한 것처럼 오해한다.

### 변경 후

```
초기: BUY 1 / SELL 1 / HOLD 3
숙의 후: HOLD 4 / BUY 1
출력: 숙의 후 HOLD 수렴
```

사용자는 다음을 구분할 수 있다.

- 처음부터 만장일치였는지
- 숙의 후 일부 관점이 변경됐는지
- 어떤 변경이 수락/거절됐는지
- 정량 관점이 독립 신호로 유지됐는지

---

## 요구사항

### 전역 데이터 계약

이 PRD에서 consensus dict의 의미는 다음과 같이 고정한다.

- top-level `consensus_verdict`, `consensus_label`, `confidence`, `vote_summary`, `perspectives`는 항상 **숙의 후 최종 결과**다.
- 숙의 전 Round 1 결과는 top-level 필드에 섞지 않고 `initial_consensus`에만 저장한다.
- 숙의 판단 내역은 `deliberation` metadata에만 저장한다.
- 기존 CLI/JSON 소비자는 top-level 최종 필드만 읽어도 계속 동작해야 한다.
- 신규 필드(`initial_consensus`, `deliberation`)는 과거 snapshot에는 없을 수 있으므로 모든 reader는 missing field를 정상 상태로 처리한다.

### R1. 초기 합의 보존

`compute_consensus()` 직후의 결과를 `initial_consensus`로 보존한다.

필수 포함 필드:

- `consensus_verdict`
- `consensus_label`
- `confidence`
- `vote_summary`
- `majority_reasoning`
- `minority_reasoning`
- `perspectives`

구현 시 `deepcopy`를 사용해 숙의 후 mutation이 초기 결과를 오염시키지 않도록 한다. `initial_consensus` 안에는 다시 `initial_consensus`를 넣지 않는다. 즉, self-nesting 없이 Round 1 consensus snapshot만 보존한다.

### R2. 코드 기반 관점 변경 금지

`quant` 관점은 숙의 LLM 재판정 및 verdict 변경 대상에서 제외한다. 단, `quant`를 합의 시스템에서 제거하지는 않는다.

- `quant` verdict는 Round 1의 코드 기반 결과를 유지한다.
- 최종 `vote_summary`, `perspectives`, `consensus_verdict` 계산에는 원래 `quant` vote를 그대로 포함한다.
- `quant`가 소수 측이어도 LLM 재판정 호출을 하지 않는다.
- `quant`가 다수 측이면 reasoning은 다른 관점의 판단 근거로 제공할 수 있으나, `quant` 자신의 verdict는 변경하지 않는다.
- 숙의 metadata에는 다음 형식으로 제외 사유를 기록한다.

```json
"excluded_perspectives": [
  {"perspective": "quant", "reason": "code_based_verdict"}
]
```

### R3. 변경 수락 조건 강화

숙의 응답은 기본적으로 “변경 제안”이다. 기본 동작은 reject이며, 아래 조건을 **모두** 만족할 때만 실제 verdict 변경으로 반영한다.

1. JSON 파싱 성공
2. `changed == true`
3. `verdict`가 `BUY`, `SELL`, `HOLD` 중 하나
4. `verdict`가 기존 verdict와 다름
5. `change_confidence == "high"`
6. `change_reason` 또는 `rebuttal_or_acceptance`가 공백 제거 후 비어 있지 않음
7. 변경 사유가 원 판단의 어떤 근거가 반박됐는지, 또는 어떤 새 근거 때문에 verdict가 바뀌는지 설명함

하나라도 실패하면 기존 verdict를 유지하고 `rejected_changes`에 사유를 기록한다. `changed=false`, `change_confidence` 누락, `medium` 이하 confidence, JSON 파싱 실패, 기존 verdict와 같은 verdict 제안은 모두 reject다.

수락/거절 metadata는 최소 다음 필드를 포함한다.

```json
{
  "perspective": "value",
  "round": 2,
  "from": "SELL",
  "to": "HOLD",
  "accepted": false,
  "reason": "change_confidence is medium"
}
```

### R4. 숙의 프롬프트 균형화

숙의 프롬프트는 다수 의견만 제시하지 않고 다음 정보를 함께 제공한다.

- 자기 원래 verdict와 reason
- 초기 `vote_summary`
- BUY/SELL/HOLD 각 측 reasoning 요약
- 변경은 원 판단이 명확히 반박될 때만 허용된다는 지시
- 변경하지 않는 것이 정상 선택지이며, 합의 수렴을 강요하지 않는다는 지시

응답 JSON에는 다음 필드를 요구한다.

```json
{
  "verdict": "BUY/SELL/HOLD",
  "changed": true,
  "change_confidence": "low/medium/high",
  "change_reason": "변경이 필요한 결정적 근거",
  "rebuttal_or_acceptance": "유지 또는 변경 논리"
}
```

### R5. 라벨 의미 보정

초기부터 유효 관점 전원이 같은 verdict인 경우에만 `만장일치` 라벨을 사용한다.

숙의 후 전원이 같은 verdict가 되었더라도 초기 결과가 만장일치가 아니었다면 `숙의 만장일치`를 사용하지 않는다. 이 경우 라벨은 반드시 다음 중 하나를 사용한다.

- `숙의 후 수렴`
- verdict 포함 시: `숙의 후 HOLD 수렴`

기존 `confidence`는 최종 표 분포 기준으로 유지할 수 있으나, `consensus_label`은 초기 상태를 고려한다.

판정표:

| 초기 상태 | 최종 상태 | 허용 라벨 |
|---|---|---|
| 초기부터 유효 관점 전원 동일 | 전원 동일 유지 | `만장일치` |
| 초기 비만장일치 | 숙의 후 전원 동일 | `숙의 후 수렴` 또는 `숙의 후 {VERDICT} 수렴` |
| 초기 비만장일치 | 숙의 후 4표 이상 동일 | `숙의 합의` |
| 초기 비만장일치 | 숙의 후 3표 동일 | `숙의 약한 합의` |
| 초기 비만장일치 | 숙의 후 동률/불충분 | 기존 `분기` 또는 `판정 보류` 의미 유지 |

### R6. before/after 추적성 저장

최종 consensus dict와 snapshot에 다음 정보를 포함한다.

```json
{
  "initial_consensus": { ... },
  "deliberation": {
    "triggered": true,
    "trigger_reason": "분기 또는 약한 합의",
    "before_vote_summary": {"BUY": 1, "SELL": 1, "HOLD": 3, "N/A": 0},
    "after_vote_summary": {"BUY": 1, "SELL": 0, "HOLD": 4, "N/A": 0},
    "excluded_perspectives": [
      {"perspective": "quant", "reason": "code_based_verdict"}
    ],
    "accepted_changes": [],
    "rejected_changes": []
  }
}
```

snapshot에는 기존 필드(`consensus_verdict`, `consensus_confidence`, `consensus_label`, `vote_summary`, `perspectives`)를 그대로 유지하고, 신규 필드는 optional로 추가한다. 과거 snapshot에는 해당 필드가 없을 수 있으므로, 읽기 로직은 missing field를 허용해야 한다.

LLM 호출 실패, JSON 파싱 실패, 수락 조건 미충족은 파이프라인 실패가 아니다. 이 경우 원 verdict를 유지하고 `deliberation.rejected_changes` 또는 `deliberation.errors`에 사유를 남긴다.

---

## 마일스톤

### M1: 초기/최종 합의 상태 분리

- [ ] `run_multi_perspective()`에서 숙의 전 `initial_consensus` 저장
- [ ] 숙의 결과에 `before_vote_summary` / `after_vote_summary` 포함
- [ ] 기존 top-level consensus 필드는 최종 결과로 유지

**검증**: 분기 시나리오에서 최종 `vote_summary`와 `initial_consensus.vote_summary`가 서로 독립적으로 유지된다.

### M2: 변경 수락 게이트 구현

- [ ] 숙의 응답을 변경 제안으로 파싱
- [ ] 수락 조건을 모두 만족할 때만 verdict 변경
- [ ] 거절된 변경은 `rejected_changes`에 사유와 함께 기록

**검증**: `changed=false`, confidence 누락, 애매한 reason 응답은 모두 기존 verdict를 유지한다.

### M3: quant 보호 및 숙의 대상 제한

- [ ] `quant`를 숙의 재판정 대상에서 제외
- [ ] `excluded_perspectives`에 제외 사유 기록
- [ ] 최종 집계에 quant 원 vote 반영

**검증**: 초기 quant BUY가 숙의 후에도 BUY로 유지되고, 다른 관점 변경만 최종 vote에 반영된다.

### M4: 균형 프롬프트 및 라벨 보정

- [ ] 숙의 프롬프트에 자기 판단 + 전체 side reasoning + 초기 vote summary 포함
- [ ] 초기 비만장일치 → 최종 전원동일 케이스를 `숙의 후 수렴`으로 라벨링
- [ ] `majority_reasoning`은 최종 perspectives 기준으로 재계산하거나 초기 논거임을 명시

**검증**: 초기 BUY/SELL/HOLD 분기 후 최종 HOLD 5표가 되어도 `숙의 만장일치`가 아니라 `숙의 후 수렴`으로 표시된다.

### M5: snapshot 및 회귀 검증

- [ ] snapshot 저장 필드에 `initial_consensus`와 숙의 metadata 포함
- [ ] 과거 snapshot 호환성 유지
- [ ] LLM 호출 없는 fixture/stub 기반 회귀 검증 추가

**검증**: 저장된 snapshot에서 초기 투표, 최종 투표, 수락/거절된 변경 내역을 모두 확인할 수 있다.

---

## 성공 기준

- top-level consensus 필드는 숙의 후 최종 결과로 유지되어 기존 CLI/JSON 소비자가 깨지지 않는다.
- `--no-deliberation` 없이도 초기 분기 정보가 보존된다.
- 숙의 후 최종 만장일치처럼 보이는 출력이 초기 만장일치와 구분된다.
- `quant` verdict가 LLM 숙의로 변경되지 않는다.
- 애매한 숙의 응답은 verdict를 변경하지 않는다.
- 신규 snapshot 필드는 optional이며 과거 snapshot 로드가 깨지지 않는다.
- 최근 snapshot을 기준으로 `숙의 만장일치 HOLD` 남발이 `숙의 후 수렴` 또는 비수렴 결과로 분리된다.

---

## 리스크 및 완화

| 리스크 | 설명 | 완화 |
|---|---|---|
| 합의 수렴률 하락 | 변경 조건 강화로 숙의 후에도 분기가 유지될 수 있음 | 분기는 정보 가치가 있으므로 숨기지 않는다 |
| JSON 스키마 증가 | snapshot과 출력 필드가 늘어남 | top-level 최종 필드는 유지하고 신규 필드는 optional 처리 |
| LLM 응답 불안정 | 새 필드를 누락할 수 있음 | 누락 시 변경 거절이 기본값 |
| 기존 성과 비교 단절 | 과거 snapshot에는 initial 정보가 없음 | missing field 허용, 새 snapshot부터 비교 |

---

## 구현 대상

- `src/common.py`
- `src/consensus/deliberator.py`
- `src/consensus/scorer.py`
- `src/performance/tracker.py`
- `main.py`
- `scripts/daily.py`

---

## 검증 전략

실제 LLM 호출 없이 stubbed 숙의 응답으로 검증한다.

1. 초기 `BUY 1 / SELL 1 / HOLD 3`, quant=BUY → 숙의 후 quant BUY 유지
2. `changed=true`지만 confidence가 `medium` → 변경 거절
3. `changed=true`, confidence=`high`, 구체적 reason 있음 → 변경 수락
4. 초기 비만장일치 → 최종 5/5 동일 → 라벨 `숙의 후 수렴`
5. 과거 snapshot 로드 시 `initial_consensus` 누락이어도 오류 없음
