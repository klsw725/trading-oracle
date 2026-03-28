"""합의도 계산 — MAXS-lite

SPEC §4-3:
  유효 5/5 동일 → "만장일치" (very high)
  유효 4/5 또는 4/4 동일 → "강한 합의" (high)
  유효 3/5 또는 3/4 동일 → "약한 합의" (moderate, 소수 의견 명시)
  유효 2개 이하 → "판정 보류"
  기타 → "분기" (low, 양측 근거 제시)
"""

from src.perspectives.base import PerspectiveResult


def compute_consensus(results: list[PerspectiveResult]) -> dict:
    """5개 관점 결과에서 합의도를 계산한다.

    Returns dict with:
      consensus_verdict: BUY/SELL/HOLD/DIVIDED/INSUFFICIENT
      consensus_label: 만장일치/강한 합의/약한 합의/분기/판정 보류
      confidence: very_high/high/moderate/low/insufficient
      vote_summary: {"BUY": n, "SELL": n, "HOLD": n, "N/A": n}
      majority_reasoning: list[str] — 다수 측 주요 근거
      minority_reasoning: list[str] — 소수 측 주요 근거 (분기 시)
      perspectives: list[dict] — 각 관점 결과
    """
    valid = [r for r in results if r.verdict != "N/A"]
    na_count = len(results) - len(valid)

    votes = {"BUY": 0, "SELL": 0, "HOLD": 0, "N/A": na_count}
    by_verdict: dict[str, list[PerspectiveResult]] = {"BUY": [], "SELL": [], "HOLD": []}

    for r in valid:
        v = r.verdict
        votes[v] = votes.get(v, 0) + 1
        by_verdict.setdefault(v, []).append(r)

    num_valid = len(valid)

    # 판정 보류: 유효 2개 이하
    if num_valid <= 2:
        return _build_result(
            "INSUFFICIENT", "판정 보류", "insufficient",
            votes, results,
            majority_reasoning=["유효 관점 수 부족으로 판정 보류"],
        )

    # 다수 verdict 찾기
    max_count = max(votes["BUY"], votes["SELL"], votes["HOLD"])
    majority_verdict = [v for v in ("BUY", "SELL", "HOLD") if votes[v] == max_count]

    # 동률이면 분기
    if len(majority_verdict) > 1:
        return _build_divergence(votes, by_verdict, results)

    winner = majority_verdict[0]
    winner_count = max_count

    # 만장일치: 유효 전원 동일
    if winner_count == num_valid and num_valid >= 3:
        label = "만장일치"
        confidence = "very_high"
    # 강한 합의: 4/5 또는 4/4
    elif winner_count >= 4 or (winner_count >= 3 and num_valid == 3):
        label = "강한 합의"
        confidence = "high"
    # 약한 합의: 3/5 또는 3/4
    elif winner_count >= 3:
        label = "약한 합의"
        confidence = "moderate"
    else:
        return _build_divergence(votes, by_verdict, results)

    majority_reasoning = []
    for r in by_verdict[winner]:
        majority_reasoning.append(f"[{r.perspective}] {r.reason}")

    minority_reasoning = []
    for v in ("BUY", "SELL", "HOLD"):
        if v != winner:
            for r in by_verdict.get(v, []):
                minority_reasoning.append(f"[{r.perspective}] {r.reason}")

    return _build_result(
        winner, label, confidence,
        votes, results,
        majority_reasoning=majority_reasoning,
        minority_reasoning=minority_reasoning,
    )


def _build_divergence(
    votes: dict,
    by_verdict: dict[str, list[PerspectiveResult]],
    results: list[PerspectiveResult],
) -> dict:
    """분기 결과 구성 — 양측 근거 포함"""
    sides = []
    for v in ("BUY", "SELL", "HOLD"):
        if by_verdict.get(v):
            names = [r.perspective for r in by_verdict[v]]
            reasons = [f"[{r.perspective}] {r.reason}" for r in by_verdict[v]]
            sides.append({"verdict": v, "perspectives": names, "reasoning": reasons})

    return _build_result(
        "DIVIDED", "분기", "low",
        votes, results,
        majority_reasoning=[f"{s['verdict']} 측 ({', '.join(s['perspectives'])}): " + "; ".join(s['reasoning']) for s in sides],
        sides=sides,
    )


def _build_result(
    consensus_verdict: str,
    label: str,
    confidence: str,
    votes: dict,
    results: list[PerspectiveResult],
    majority_reasoning: list[str] | None = None,
    minority_reasoning: list[str] | None = None,
    sides: list[dict] | None = None,
) -> dict:
    output = {
        "consensus_verdict": consensus_verdict,
        "consensus_label": label,
        "confidence": confidence,
        "vote_summary": votes,
        "majority_reasoning": majority_reasoning or [],
        "minority_reasoning": minority_reasoning or [],
        "perspectives": [r.to_dict() for r in results],
    }
    if sides:
        output["sides"] = sides
    return output
