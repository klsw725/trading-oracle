"""숙의 합의 시스템 — Phase 13 (MAXS-deliberation)

분기/약한 합의 시 소수 측에 다수 측 근거를 제시하고 재판정.
수렴하면 합의로 승격, 미수렴 시 기존 결과 유지.
"""

from src.perspectives.base import PerspectiveInput, PerspectiveResult, call_llm, extract_json, make_na_result


DELIBERATION_PROMPT = """\
당신은 이전에 이 종목에 대해 {verdict} 판정을 내렸습니다.

그런데 다른 관점들의 다수 의견은 **{majority_verdict}**입니다.

다수 측의 근거는 다음과 같습니다:
{majority_reasoning}

위 근거를 고려한 후, 당신의 기존 판정을 **유지할지 변경할지** 재판정해주세요.

## 규칙
- 기존 판정을 유지한다면, 왜 다수 측 근거에도 불구하고 유지하는지 **반론**을 제시하세요.
- 판정을 변경한다면, 어떤 근거가 결정적이었는지 설명하세요.
- 무비판적 동조는 금지합니다. 반드시 논리적 근거를 제시하세요.

## 출력 규칙
**반드시 아래 JSON 형식으로만 응답하세요.**

```json
{{
  "verdict": "BUY 또는 SELL 또는 HOLD",
  "changed": true 또는 false,
  "reason": "변경/유지 사유 한 줄",
  "reasoning": ["근거 1", "근거 2"]
}}
```
"""


def should_deliberate(consensus: dict) -> bool:
    """숙의 발동 조건 확인. 분기 또는 약한 합의 시에만."""
    label = consensus.get("consensus_label", "")
    return label in ("분기", "약한 합의")


def identify_minority(consensus: dict) -> tuple[list[dict], str, list[str]]:
    """소수 측 관점 식별.

    Returns:
        (소수 측 perspectives, 다수 verdict, 다수 측 reasoning)
    """
    verdict = consensus["consensus_verdict"]
    perspectives = consensus.get("perspectives", [])

    if verdict == "DIVIDED":
        # 분기: 투표 수가 가장 많은 쪽이 다수
        votes = consensus.get("vote_summary", {})
        max_v = max(votes.get("BUY", 0), votes.get("SELL", 0), votes.get("HOLD", 0))
        majority_verdict = [v for v in ("BUY", "SELL", "HOLD") if votes.get(v, 0) == max_v][0]
    else:
        majority_verdict = verdict

    minority = [p for p in perspectives if p["verdict"] != majority_verdict and p["verdict"] != "N/A"]
    majority_reasoning = [f"[{p['perspective']}] {p.get('reason', '')}" for p in perspectives if p["verdict"] == majority_verdict]

    return minority, majority_verdict, majority_reasoning


def deliberate(consensus: dict, data: PerspectiveInput, max_rounds: int = 2) -> dict:
    """숙의 실행. 소수 측 재판정 후 합의도 재계산.

    Args:
        consensus: 1차 compute_consensus() 결과
        data: PerspectiveInput (config 등 LLM 호출에 필요)
        max_rounds: 최대 숙의 라운드 수

    Returns:
        consensus dict에 deliberation 필드 추가.
        변경 사항이 있으면 vote_summary, consensus_verdict 등도 갱신.
    """
    if not should_deliberate(consensus):
        return consensus

    minority, majority_verdict, majority_reasoning = identify_minority(consensus)
    if not minority:
        return consensus

    rounds = []
    current_perspectives = list(consensus.get("perspectives", []))

    for round_num in range(1, max_rounds + 1):
        round_changes = []

        for p in minority:
            p_name = p["perspective"]
            p_verdict = p["verdict"]

            # 숙의 프롬프트 구성
            prompt = DELIBERATION_PROMPT.format(
                verdict=p_verdict,
                majority_verdict=majority_verdict,
                majority_reasoning="\n".join(majority_reasoning[:5]),
            )

            try:
                response = call_llm(
                    f"당신은 {p_name} 관점의 투자 분석가입니다. 이전 판정을 재검토합니다.",
                    prompt,
                    data.config,
                    max_tokens=512,
                )
                parsed = extract_json(response)

                if parsed and "verdict" in parsed:
                    new_verdict = parsed["verdict"].upper()
                    if new_verdict in ("BUY", "SELL", "HOLD"):
                        changed = new_verdict != p_verdict
                        round_changes.append({
                            "perspective": p_name,
                            "previous": p_verdict,
                            "current": new_verdict,
                            "changed": changed,
                            "reason": parsed.get("reason", ""),
                        })

                        if changed:
                            # current_perspectives에서 해당 관점 verdict 업데이트
                            for cp in current_perspectives:
                                if cp["perspective"] == p_name:
                                    cp["verdict"] = new_verdict
                                    cp["reason"] = parsed.get("reason", cp.get("reason", ""))
                                    break
            except Exception:
                round_changes.append({
                    "perspective": p_name,
                    "previous": p_verdict,
                    "current": p_verdict,
                    "changed": False,
                    "reason": "LLM 호출 실패 — 기존 판정 유지",
                })

        rounds.append({"round": round_num, "changes": round_changes})

        # 수렴 판정: δ = |변경 수| / |소수 측 수|
        num_changed = sum(1 for c in round_changes if c["changed"])
        delta = num_changed / max(len(minority), 1)

        if delta <= 0.1:
            break  # 수렴 → 조기 종료

        # 다음 라운드를 위해 소수 측 재식별
        minority, majority_verdict, majority_reasoning = _reidentify_minority(current_perspectives)
        if not minority:
            break

    # 합의도 재계산
    new_votes = {"BUY": 0, "SELL": 0, "HOLD": 0, "N/A": 0}
    for p in current_perspectives:
        v = p["verdict"]
        new_votes[v] = new_votes.get(v, 0) + 1

    valid = sum(new_votes[v] for v in ("BUY", "SELL", "HOLD"))
    max_count = max(new_votes["BUY"], new_votes["SELL"], new_votes["HOLD"])
    winners = [v for v in ("BUY", "SELL", "HOLD") if new_votes[v] == max_count]

    if max_count == valid and valid >= 3:
        new_verdict = winners[0]
        new_label = "숙의 만장일치"
        new_confidence = "very_high"
    elif max_count >= 4 or (max_count >= 3 and valid == 3):
        new_verdict = winners[0]
        new_label = "숙의 합의"
        new_confidence = "high"
    elif max_count >= 3 and len(winners) == 1:
        new_verdict = winners[0]
        new_label = "숙의 약한 합의"
        new_confidence = "moderate"
    else:
        new_verdict = consensus["consensus_verdict"]
        new_label = consensus["consensus_label"]
        new_confidence = consensus["confidence"]

    result = {**consensus}
    result["perspectives"] = current_perspectives
    result["vote_summary"] = new_votes
    result["consensus_verdict"] = new_verdict
    result["consensus_label"] = new_label
    result["confidence"] = new_confidence
    result["deliberation"] = {
        "rounds": rounds,
        "total_rounds": len(rounds),
        "original_verdict": consensus["consensus_verdict"],
        "original_label": consensus["consensus_label"],
        "final_verdict": new_verdict,
        "final_label": new_label,
        "verdict_changed": new_verdict != consensus["consensus_verdict"],
    }

    return result


def _reidentify_minority(perspectives: list[dict]) -> tuple[list[dict], str, list[str]]:
    """현재 perspectives에서 소수 측 재식별."""
    votes = {"BUY": 0, "SELL": 0, "HOLD": 0}
    for p in perspectives:
        v = p["verdict"]
        if v in votes:
            votes[v] += 1

    max_count = max(votes.values())
    majority_verdict = [v for v, c in votes.items() if c == max_count][0]

    minority = [p for p in perspectives if p["verdict"] != majority_verdict and p["verdict"] != "N/A"]
    majority_reasoning = [f"[{p['perspective']}] {p.get('reason', '')}" for p in perspectives if p["verdict"] == majority_verdict]

    return minority, majority_verdict, majority_reasoning
