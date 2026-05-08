"""숙의 합의 시스템 — Phase 13 (MAXS-deliberation)

분기/약한 합의 시 소수 측에 다수 측 근거를 제시하고 재판정.
숙의 응답은 변경 제안으로만 취급하고, 수락 기준을 모두 만족할 때만 반영한다.
"""

from typing import Any, TypeAlias

from src.perspectives.base import PerspectiveInput, call_llm, extract_json


DELIBERATION_PROMPT = """\
당신은 이전에 이 종목에 대해 **{original_verdict}** 판정을 내렸습니다.

## 당신의 기존 판단
- verdict: {original_verdict}
- reason: {original_reason}

## 초기 투표 요약
{vote_summary}

## BUY/SELL/HOLD 각 측 근거
{side_reasoning}

## 재검토 규칙
- 이 응답은 판정 변경의 "제안"일 뿐이며, 시스템은 엄격한 조건을 통과한 경우에만 변경을 반영합니다.
- 기존 판정을 유지하는 것은 정상적인 선택지입니다. 합의 수렴을 강요받지 마세요.
- 판정 변경은 기존 판단의 핵심 근거가 명확히 반박되었거나, 새 근거가 기존 판단보다 결정적일 때만 허용됩니다.
- 단순히 다수 의견이므로 따라가거나, 애매한 가능성만으로 변경하지 마세요.
- 유지한다면 왜 다른 측 근거에도 불구하고 기존 판단이 유효한지 설명하세요.

## 출력 규칙
**반드시 아래 JSON 형식으로만 응답하세요.**

```json
{{
  "verdict": "BUY/SELL/HOLD",
  "changed": true 또는 false,
  "change_confidence": "low/medium/high",
  "change_reason": "변경이 필요한 결정적 근거",
  "rebuttal_or_acceptance": "유지 또는 변경 논리"
}}
```
"""


VALID_VERDICTS = ("BUY", "SELL", "HOLD")
DictAny: TypeAlias = dict[str, Any]


def should_deliberate(consensus: DictAny) -> bool:
    """숙의 발동 조건 확인. 분기 또는 약한 합의 시에만."""
    label = consensus.get("consensus_label", "")
    return label in ("분기", "약한 합의")


def identify_minority(consensus: DictAny) -> tuple[list[DictAny], str, list[str]]:
    """소수 측 관점 식별.

    Returns:
        (소수 측 perspectives, 다수 verdict, 다수 측 reasoning)
    """
    verdict = consensus["consensus_verdict"]
    perspectives = consensus.get("perspectives", [])

    if verdict == "DIVIDED":
        votes = consensus.get("vote_summary", {})
        max_v = max(votes.get("BUY", 0), votes.get("SELL", 0), votes.get("HOLD", 0))
        majority_verdict = [v for v in VALID_VERDICTS if votes.get(v, 0) == max_v][0]
    else:
        majority_verdict = verdict

    minority = [
        p for p in perspectives
        if p["verdict"] != majority_verdict and p["verdict"] != "N/A"
    ]
    majority_reasoning = [
        f"[{p['perspective']}] {p.get('reason', '')}"
        for p in perspectives
        if p["verdict"] == majority_verdict
    ]

    return minority, majority_verdict, majority_reasoning


def deliberate(consensus: DictAny, data: PerspectiveInput, max_rounds: int = 2) -> DictAny:
    """숙의 실행. 소수 측 변경 제안 검토 후 합의도 재계산."""
    if not should_deliberate(consensus):
        return consensus

    minority, majority_verdict, majority_reasoning = identify_minority(consensus)
    if not minority:
        return consensus

    current_perspectives = [dict(p) for p in consensus.get("perspectives", [])]
    before_vote_summary = dict(consensus.get("vote_summary", {}))
    accepted_changes = []
    rejected_changes = []
    excluded_perspectives = []
    errors = []
    rounds = []

    for round_num in range(2, max_rounds + 2):
        round_changes = []

        for p in minority:
            p_name = p["perspective"]
            p_verdict = p["verdict"]

            if p_name == "quant":
                excluded = {"perspective": p_name, "reason": "code_based_verdict"}
                if excluded not in excluded_perspectives:
                    excluded_perspectives.append(excluded)
                round_changes.append({
                    "perspective": p_name,
                    "previous": p_verdict,
                    "current": p_verdict,
                    "changed": False,
                    "reason": "code_based_verdict",
                })
                continue

            prompt = DELIBERATION_PROMPT.format(
                original_verdict=p_verdict,
                original_reason=p.get("reason", ""),
                vote_summary=_format_vote_summary(before_vote_summary),
                side_reasoning=_format_side_reasoning(current_perspectives),
                majority_verdict=majority_verdict,
                majority_reasoning="\n".join(majority_reasoning[:5]),
            )

            try:
                response = call_llm(
                    f"당신은 {p_name} 관점의 투자 분석가입니다. 이전 판정을 재검토합니다.",
                    prompt,
                    data.config,
                    max_tokens=700,
                )
                parsed_obj: object = extract_json(response)
            except Exception as exc:
                change = _build_change(p_name, round_num, p_verdict, p_verdict, False, "LLM/parsing exception")
                rejected_changes.append(change)
                errors.append({
                    "perspective": p_name,
                    "round": round_num,
                    "error": str(exc),
                })
                round_changes.append({
                    "perspective": p_name,
                    "previous": p_verdict,
                    "current": p_verdict,
                    "changed": False,
                    "reason": "LLM/parsing exception",
                })
                continue

            accepted, new_verdict, reject_reason = _evaluate_change_proposal(parsed_obj, p_verdict)
            if not accepted:
                change = _build_change(p_name, round_num, p_verdict, new_verdict or p_verdict, False, reject_reason)
                rejected_changes.append(change)
                round_changes.append({
                    "perspective": p_name,
                    "previous": p_verdict,
                    "current": p_verdict,
                    "changed": False,
                    "reason": reject_reason,
                })
                continue

            if not isinstance(parsed_obj, dict):
                continue
            parsed: DictAny = parsed_obj

            proposal_reason = _proposal_reason(parsed)
            change = _build_change(p_name, round_num, p_verdict, new_verdict, True, proposal_reason)
            accepted_changes.append(change)
            round_changes.append({
                "perspective": p_name,
                "previous": p_verdict,
                "current": new_verdict,
                "changed": True,
                "reason": proposal_reason,
            })

            for cp in current_perspectives:
                if cp["perspective"] == p_name:
                    cp["verdict"] = new_verdict
                    cp["reason"] = proposal_reason
                    cp["reasoning"] = _proposal_reasoning(parsed, proposal_reason)
                    break

        rounds.append({"round": round_num, "changes": round_changes})

        num_changed = sum(1 for c in round_changes if c["changed"])
        delta = num_changed / max(len([p for p in minority if p.get("perspective") != "quant"]), 1)
        if delta <= 0.1:
            break

        minority, majority_verdict, majority_reasoning = _reidentify_minority(current_perspectives)
        if not minority:
            break

    final = _classify_final(current_perspectives, consensus)

    result = {**consensus}
    result["perspectives"] = current_perspectives
    result["vote_summary"] = final["vote_summary"]
    result["consensus_verdict"] = final["consensus_verdict"]
    result["consensus_label"] = final["consensus_label"]
    result["confidence"] = final["confidence"]
    result["majority_reasoning"] = final["majority_reasoning"]
    result["minority_reasoning"] = final["minority_reasoning"]
    if final.get("sides"):
        result["sides"] = final["sides"]
    elif "sides" in result:
        result.pop("sides", None)
    result["deliberation"] = {
        "triggered": True,
        "trigger_reason": "분기 또는 약한 합의",
        "before_vote_summary": before_vote_summary,
        "after_vote_summary": final["vote_summary"],
        "excluded_perspectives": excluded_perspectives,
        "accepted_changes": accepted_changes,
        "rejected_changes": rejected_changes,
        "errors": errors,
        "rounds": rounds,
        "total_rounds": len(rounds),
        "original_verdict": consensus["consensus_verdict"],
        "original_label": consensus["consensus_label"],
        "final_verdict": final["consensus_verdict"],
        "final_label": final["consensus_label"],
        "verdict_changed": final["consensus_verdict"] != consensus["consensus_verdict"],
    }

    return result


def _evaluate_change_proposal(parsed: object, original_verdict: str) -> tuple[bool, str | None, str]:
    if not parsed or not isinstance(parsed, dict):
        return False, None, "JSON parsing failed"

    proposed = str(parsed.get("verdict", "")).upper()
    if parsed.get("changed") is not True:
        return False, proposed if proposed in VALID_VERDICTS else None, "changed is not true"
    if proposed not in VALID_VERDICTS:
        return False, proposed or None, "verdict is not BUY/SELL/HOLD"
    if proposed == original_verdict:
        return False, proposed, "verdict does not differ from original"
    if str(parsed.get("change_confidence", "")).lower() != "high":
        return False, proposed, f"change_confidence is {parsed.get('change_confidence', 'missing')}"

    reason = _proposal_reason(parsed)
    if not reason.strip():
        return False, proposed, "change_reason or rebuttal_or_acceptance is empty"
    if not _has_concrete_change_reason(reason):
        return False, proposed, "change reason does not explain concrete rebuttal/new evidence"

    return True, proposed, "accepted"


def _proposal_reason(parsed: DictAny) -> str:
    return str(parsed.get("change_reason") or parsed.get("rebuttal_or_acceptance") or "").strip()


def _proposal_reasoning(parsed: DictAny, fallback: str) -> list[str]:
    reasoning = parsed.get("reasoning")
    if isinstance(reasoning, list) and reasoning:
        return [str(r) for r in reasoning]
    rebuttal = str(parsed.get("rebuttal_or_acceptance") or "").strip()
    if rebuttal and rebuttal != fallback:
        return [fallback, rebuttal]
    return [fallback]


def _has_concrete_change_reason(reason: str) -> bool:
    compact = "".join(reason.split())
    return len(compact) >= 12


def _build_change(
    perspective: str,
    round_num: int,
    from_verdict: str,
    to_verdict: str | None,
    accepted: bool,
    reason: str,
) -> DictAny:
    return {
        "perspective": perspective,
        "round": round_num,
        "from": from_verdict,
        "to": to_verdict or from_verdict,
        "accepted": accepted,
        "reason": reason,
    }


def _format_vote_summary(votes: DictAny) -> str:
    return " / ".join(f"{v}: {votes.get(v, 0)}" for v in ("BUY", "SELL", "HOLD", "N/A"))


def _format_side_reasoning(perspectives: list[DictAny]) -> str:
    lines = []
    for verdict in VALID_VERDICTS:
        reasons = [
            f"- [{p['perspective']}] {p.get('reason', '')}"
            for p in perspectives
            if p.get("verdict") == verdict
        ]
        if reasons:
            lines.append(f"### {verdict}\n" + "\n".join(reasons))
        else:
            lines.append(f"### {verdict}\n- 해당 없음")
    return "\n\n".join(lines)


def _classify_final(perspectives: list[DictAny], initial_consensus: DictAny) -> DictAny:
    votes = _count_votes(perspectives)
    valid = sum(votes[v] for v in VALID_VERDICTS)
    by_verdict = {
        v: [p for p in perspectives if p.get("verdict") == v]
        for v in VALID_VERDICTS
    }

    if valid <= 2:
        return _final_result(
            "INSUFFICIENT", "판정 보류", "insufficient", votes, by_verdict,
            majority_reasoning=["유효 관점 수 부족으로 판정 보류"],
        )

    max_count = max(votes[v] for v in VALID_VERDICTS)
    winners = [v for v in VALID_VERDICTS if votes[v] == max_count]
    initial_unanimous = _is_unanimous(initial_consensus.get("vote_summary", {}))

    if len(winners) > 1:
        return _build_final_divergence(votes, by_verdict)

    winner = winners[0]
    if max_count == valid:
        label = "만장일치" if initial_unanimous else f"숙의 후 {winner} 수렴"
        return _final_result(winner, label, "very_high", votes, by_verdict)
    if max_count >= 4:
        return _final_result(winner, "숙의 합의", "high", votes, by_verdict)
    if max_count >= 3:
        return _final_result(winner, "숙의 약한 합의", "moderate", votes, by_verdict)
    return _build_final_divergence(votes, by_verdict)


def _count_votes(perspectives: list[DictAny]) -> DictAny:
    votes = {"BUY": 0, "SELL": 0, "HOLD": 0, "N/A": 0}
    for p in perspectives:
        v = p.get("verdict", "N/A")
        votes[v] = votes.get(v, 0) + 1
    return votes


def _is_unanimous(votes: DictAny) -> bool:
    valid = sum(votes.get(v, 0) for v in VALID_VERDICTS)
    if valid < 3:
        return False
    return max(votes.get(v, 0) for v in VALID_VERDICTS) == valid


def _final_result(
    verdict: str,
    label: str,
    confidence: str,
    votes: DictAny,
    by_verdict: dict[str, list[DictAny]],
    majority_reasoning: list[str] | None = None,
) -> DictAny:
    majority_reasoning = majority_reasoning or [
        f"[{p['perspective']}] {p.get('reason', '')}"
        for p in by_verdict.get(verdict, [])
    ]
    minority_reasoning = []
    for v in VALID_VERDICTS:
        if v != verdict:
            for p in by_verdict.get(v, []):
                minority_reasoning.append(f"[{p['perspective']}] {p.get('reason', '')}")
    return {
        "consensus_verdict": verdict,
        "consensus_label": label,
        "confidence": confidence,
        "vote_summary": votes,
        "majority_reasoning": majority_reasoning,
        "minority_reasoning": minority_reasoning,
    }


def _build_final_divergence(votes: DictAny, by_verdict: dict[str, list[DictAny]]) -> DictAny:
    sides = []
    for v in VALID_VERDICTS:
        if by_verdict.get(v):
            names = [p["perspective"] for p in by_verdict[v]]
            reasons = [f"[{p['perspective']}] {p.get('reason', '')}" for p in by_verdict[v]]
            sides.append({"verdict": v, "perspectives": names, "reasoning": reasons})
    return {
        "consensus_verdict": "DIVIDED",
        "consensus_label": "분기",
        "confidence": "low",
        "vote_summary": votes,
        "majority_reasoning": [
            f"{s['verdict']} 측 ({', '.join(s['perspectives'])}): " + "; ".join(s["reasoning"])
            for s in sides
        ],
        "minority_reasoning": [],
        "sides": sides,
    }


def _reidentify_minority(perspectives: list[DictAny]) -> tuple[list[DictAny], str, list[str]]:
    """현재 perspectives에서 소수 측 재식별."""
    votes = {v: 0 for v in VALID_VERDICTS}
    for p in perspectives:
        v = p["verdict"]
        if v in votes:
            votes[v] += 1

    max_count = max(votes.values())
    majority_verdict = [v for v, c in votes.items() if c == max_count][0]

    minority = [
        p for p in perspectives
        if p["verdict"] != majority_verdict and p["verdict"] != "N/A"
    ]
    majority_reasoning = [
        f"[{p['perspective']}] {p.get('reason', '')}"
        for p in perspectives
        if p["verdict"] == majority_verdict
    ]

    return minority, majority_verdict, majority_reasoning
