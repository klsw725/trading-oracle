"""프롬프트 자가 튜닝 — Phase 16

적중률 저조 관점의 오답 분석 → LLM 기반 프롬프트 개선 제안.
사용자 수동 승인 후 적용.
"""

from src.performance.pattern_analyzer import analyze_hit_patterns, PERSPECTIVES
from src.performance.tracker import list_snapshots, load_snapshot, evaluate_snapshot
from src.perspectives.base import call_llm


TUNING_ANALYSIS_PROMPT = """\
당신은 투자 분석 시스템의 메타 분석가입니다.

아래는 "{perspective}" 관점의 최근 오답 사례입니다. 이 관점의 적중률은 {hit_rate}%%입니다.

## 오답 사례 (추천 vs 실제)
{wrong_cases}

## 현재 시스템 프롬프트 (요약)
이 관점은 {perspective_desc} 기반으로 판정합니다.

## 분석 요청
1. 이 관점이 반복적으로 틀리는 **패턴**이 있는가?
2. 프롬프트에 어떤 **구체적 지시**를 추가/수정하면 개선될 수 있는가?
3. 예상 개선 효과는?

## 출력 규칙
**반드시 아래 JSON 형식으로만 응답하세요.**

```json
{{
  "pattern": "반복 오답 패턴 설명",
  "suggestion": "프롬프트 개선 제안 (구체적 문구)",
  "estimated_improvement": "예상 개선 효과 (+N%%p)",
  "confidence": 0.0~1.0
}}
```
"""

PERSPECTIVE_DESCS = {
    "kwangsoo": "이광수 투자 철학 (추적 손절매, 주도주, 모멘텀)",
    "ouroboros": "포렌식 감사관 (희석 리스크, 내부자, 기관 수급)",
    "quant": "퀀트 시그널 (6-시그널 앙상블 보팅)",
    "macro": "매크로 인과 체인 (금리, 환율, 섹터 사이클)",
    "value": "가치 투자 (PER, PBR, 배당수익률)",
}


def identify_underperformers(threshold: float = 40.0, min_snapshots: int = 5) -> list[dict]:
    """적중률 저조 관점 식별.

    Returns:
        [{"perspective": "quant", "rate": 35.0, "trend_slope": -0.02}, ...]
    """
    patterns = analyze_hit_patterns(min_snapshots=min_snapshots)
    if not patterns:
        return []

    underperformers = []
    overall = patterns.get("overall", {})
    trend = patterns.get("trend", {})

    for p in PERSPECTIVES:
        stats = overall.get(p)
        if not stats or stats["rate"] is None:
            continue
        if stats["rate"] < threshold:
            t = trend.get(p, {})
            underperformers.append({
                "perspective": p,
                "rate": stats["rate"],
                "total": stats["total"],
                "trend_slope": t.get("slope", 0),
                "improving": t.get("improving", False),
            })

    return underperformers


def collect_wrong_cases(perspective: str, max_cases: int = 10, eval_window: int = 5) -> list[dict]:
    """특정 관점의 최근 오답 사례 수집."""
    snapshots = list_snapshots()
    wrong = []

    for date_str in reversed(snapshots):
        if len(wrong) >= max_cases:
            break
        snap = load_snapshot(date_str)
        if not snap:
            continue
        ev = evaluate_snapshot(snap, eval_days=[eval_window])

        for ticker, ticker_ev in ev.get("evaluations", {}).items():
            p_data = ticker_ev.get("perspective_hits", {}).get(perspective)
            if not p_data:
                continue
            hit = p_data.get(str(eval_window))
            if hit is False:
                rec = snap.get("recommendations", {}).get(ticker, {})
                wrong.append({
                    "date": date_str,
                    "ticker": ticker,
                    "name": rec.get("name", ticker),
                    "verdict": p_data.get("verdict", "N/A"),
                    "price": rec.get("price", 0),
                    "return_pct": ticker_ev.get("windows", {}).get(str(eval_window), {}).get("return_pct"),
                })
                if len(wrong) >= max_cases:
                    break

    return wrong


def generate_tuning_suggestion(perspective: str, config: dict) -> dict | None:
    """프롬프트 튜닝 제안 생성.

    Returns:
        {
            "perspective": "quant",
            "current_hit_rate": 35.0,
            "wrong_cases_count": 8,
            "analysis": {...},  # LLM 분석 결과
        }
    """
    # 적중률 확인
    patterns = analyze_hit_patterns(min_snapshots=2)
    if not patterns:
        return None

    overall = patterns.get("overall", {}).get(perspective)
    if not overall or overall["rate"] is None:
        return None

    # 오답 수집
    wrong = collect_wrong_cases(perspective)
    if not wrong:
        return None

    # 오답 텍스트 포맷
    wrong_text = ""
    for w in wrong:
        ret = f"{w['return_pct']:+.1f}%" if w.get("return_pct") is not None else "N/A"
        wrong_text += f"- [{w['date']}] {w['name']}: {w['verdict']} 판정 → 실제 {ret}\n"

    # LLM 분석 요청
    try:
        from src.perspectives.base import extract_json
        prompt = TUNING_ANALYSIS_PROMPT.format(
            perspective=perspective,
            hit_rate=overall["rate"],
            wrong_cases=wrong_text,
            perspective_desc=PERSPECTIVE_DESCS.get(perspective, perspective),
        )
        response = call_llm(
            "당신은 투자 분석 시스템의 메타 분석가입니다.",
            prompt,
            config,
            max_tokens=1024,
        )
        analysis = extract_json(response)
    except Exception:
        analysis = None

    return {
        "perspective": perspective,
        "current_hit_rate": overall["rate"],
        "wrong_cases_count": len(wrong),
        "analysis": analysis,
    }
