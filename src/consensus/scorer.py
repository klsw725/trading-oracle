"""합의도 계산 — MAXS-lite

SPEC §4-3:
  유효 5/5 동일 → "만장일치" (very high)
  유효 4/5 또는 4/4 동일 → "강한 합의" (high)
  유효 3/5 또는 3/4 동일 → "약한 합의" (moderate, 소수 의견 명시)
  유효 2개 이하 → "판정 보류"
  기타 → "분기" (low, 양측 근거 제시)
"""

from src.perspectives.base import PerspectiveResult


def compute_consensus(results: list[PerspectiveResult], weights: dict | None = None) -> dict:
    """5개 관점 결과에서 합의도를 계산한다.

    Args:
        results: 5개 관점 분석 결과
        weights: 관점별 가중치 dict (예: {"kwangsoo": 0.7, ...}).
                 None이면 동등 가중치 (기존 동작).

    Returns dict with:
      consensus_verdict: BUY/SELL/HOLD/DIVIDED/INSUFFICIENT
      consensus_label: 만장일치/강한 합의/약한 합의/분기/판정 보류
      confidence: very_high/high/moderate/low/insufficient
      vote_summary: {"BUY": n, "SELL": n, "HOLD": n, "N/A": n}
      majority_reasoning: list[str] — 다수 측 주요 근거
      minority_reasoning: list[str] — 소수 측 주요 근거 (분기 시)
      perspectives: list[dict] — 각 관점 결과
      weighted: bool — 가중치 적용 여부
      weights_used: dict | None — 사용된 가중치
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
    is_weighted = weights is not None and num_valid > 0

    # 판정 보류: 유효 2개 이하
    if num_valid <= 2:
        return _build_result(
            "INSUFFICIENT", "판정 보류", "insufficient",
            votes, results,
            majority_reasoning=["유효 관점 수 부족으로 판정 보류"],
            weighted=is_weighted,
            weights_used=weights,
        )

    # 만장일치 체크 (가중치 무관)
    max_count = max(votes["BUY"], votes["SELL"], votes["HOLD"])
    majority_verdict = [v for v in ("BUY", "SELL", "HOLD") if votes[v] == max_count]

    if max_count == num_valid and num_valid >= 3:
        # 만장일치 — 가중치 무관
        winner = majority_verdict[0]
        majority_reasoning = [f"[{r.perspective}] {r.reason}" for r in by_verdict[winner]]
        return _build_result(
            winner, "만장일치", "very_high",
            votes, results,
            majority_reasoning=majority_reasoning,
            weighted=is_weighted,
            weights_used=weights,
        )

    # 가중 투표 또는 단순 투표
    if is_weighted:
        winner, label, confidence = _weighted_classify(by_verdict, valid, weights)
    else:
        winner, label, confidence = _unweighted_classify(votes, by_verdict, num_valid)

    if winner is None:
        return _build_divergence(votes, by_verdict, results, weighted=is_weighted, weights_used=weights)

    majority_reasoning = [f"[{r.perspective}] {r.reason}" for r in by_verdict[winner]]
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
        weighted=is_weighted,
        weights_used=weights,
    )


def _unweighted_classify(
    votes: dict,
    by_verdict: dict[str, list[PerspectiveResult]],
    num_valid: int,
) -> tuple[str | None, str, str]:
    """기존 단순 카운트 기반 분류. (winner, label, confidence) 또는 (None, ...) 분기."""
    max_count = max(votes["BUY"], votes["SELL"], votes["HOLD"])
    majority = [v for v in ("BUY", "SELL", "HOLD") if votes[v] == max_count]

    if len(majority) > 1:
        return None, "분기", "low"

    winner = majority[0]
    winner_count = max_count

    if winner_count >= 4 or (winner_count >= 3 and num_valid == 3):
        return winner, "강한 합의", "high"
    elif winner_count >= 3:
        return winner, "약한 합의", "moderate"
    return None, "분기", "low"


def _weighted_classify(
    by_verdict: dict[str, list[PerspectiveResult]],
    valid: list[PerspectiveResult],
    weights: dict,
) -> tuple[str | None, str, str]:
    """가중 투표 기반 분류. (winner, label, confidence) 또는 (None, ...) 분기."""
    weighted_votes = {}
    for v in ("BUY", "SELL", "HOLD"):
        weighted_votes[v] = sum(weights.get(r.perspective, 1.0) for r in by_verdict.get(v, []))

    total_weight = sum(weights.get(r.perspective, 1.0) for r in valid)
    if total_weight <= 0:
        return None, "분기", "low"

    max_wv = max(weighted_votes.values())
    winners = [v for v, wv in weighted_votes.items() if wv == max_wv]

    if len(winners) > 1:
        return None, "분기", "low"

    winner = winners[0]
    ratio = max_wv / total_weight

    if ratio >= 0.8:
        return winner, "강한 합의", "high"
    elif ratio >= 0.6:
        return winner, "약한 합의", "moderate"
    return None, "분기", "low"


def _build_divergence(
    votes: dict,
    by_verdict: dict[str, list[PerspectiveResult]],
    results: list[PerspectiveResult],
    weighted: bool = False,
    weights_used: dict | None = None,
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
        weighted=weighted,
        weights_used=weights_used,
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
    weighted: bool = False,
    weights_used: dict | None = None,
) -> dict:
    output = {
        "consensus_verdict": consensus_verdict,
        "consensus_label": label,
        "confidence": confidence,
        "vote_summary": votes,
        "majority_reasoning": majority_reasoning or [],
        "minority_reasoning": minority_reasoning or [],
        "perspectives": [r.to_dict() for r in results],
        "weighted": weighted,
    }
    if weights_used:
        output["weights_used"] = weights_used
    if sides:
        output["sides"] = sides
    return output
