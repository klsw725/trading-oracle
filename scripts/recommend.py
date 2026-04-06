#!/usr/bin/env python3
"""종목 추천 — 스크리닝 → 시그널 필터 → 다관점 분석 → BUY 합의

사용법:
    uv run scripts/recommend.py                    # 한국 주도주 BUY 추천
    uv run scripts/recommend.py --market US        # 미국 시장
    uv run scripts/recommend.py --top 10           # 후보 수 조정
    uv run scripts/recommend.py --no-filter        # 시그널 필터 없이 전체 분석
    uv run scripts/recommend.py --no-llm           # 시그널만 (LLM 없이)
    uv run scripts/recommend.py --json             # JSON 출력
"""

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import load_config, json_dump, run_recommend


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 종목 추천")
    parser.add_argument(
        "--market", default="ALL", help="시장 (ALL, KOSPI, KOSDAQ, US, NASDAQ, NYSE)"
    )
    parser.add_argument("--top", type=int, default=6, help="스크리닝 후보 수 (기본: 6)")
    parser.add_argument(
        "--no-filter", action="store_true", help="시그널 필터 없이 전체 분석"
    )
    parser.add_argument("--no-llm", action="store_true", help="시그널만 (LLM 없이)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    config = load_config()
    result = run_recommend(
        config,
        market=args.market,
        top_n=args.top,
        signal_filter=not args.no_filter,
        use_llm=not args.no_llm,
    )

    if args.json:
        print(json_dump(result))
        return

    # 터미널 Rich 출력
    from src.output.formatter import console
    from rich.panel import Panel

    regime = result.get("regime", {})
    regime_label = regime.get("label", "")
    console.print(f"\n[bold]🎯 종목 추천[/bold] ({result['date']}, {regime_label})")
    console.print(
        f"  스크리닝: {result['screened']}개 후보 → 시그널 필터: {result['signal_filtered']}개 통과 → 분석: {result['analyzed']}개"
    )
    console.print()

    recs = result["recommendations"]
    if not recs:
        reason = result.get("no_recommendation_reason", "추천 종목 없음")
        console.print(f"  [yellow]⚠️  {reason}[/yellow]")
        if regime.get("regime") == "bear":
            console.print(
                "  [dim]시장 레짐이 하락 추세입니다. 현금 비중 유지를 권장합니다.[/dim]"
            )
        console.print()
        return

    verdict_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "N/A": "⚪"}

    for rec in recs:
        consensus = rec.get("consensus")
        sig = rec["signals"]

        lines = []
        lines.append(
            f"[bold]시그널:[/bold] {sig['verdict']} (Bull {sig['bull_votes']}/6)"
        )

        if consensus:
            lines.append(
                f"[bold]합의도:[/bold] {consensus['consensus_label']} ({consensus['consensus_verdict']})"
            )
            lines.append("")
            for p in consensus.get("perspectives", []):
                emoji = verdict_emoji.get(p["verdict"], "⚪")
                lines.append(
                    f"  {emoji} [bold]{p['perspective']}[/bold]: {p['verdict']} — {p.get('reason', '')}"
                )

        # 매수 전략
        plan = rec.get("action_plan")
        if plan and plan.get("type") == "buy":
            lines.append("")
            lines.append(
                f"  [bold green]💰 매수 전략 (분할 매수 1차 / {plan['first_tranche_pct']}%%)[/bold green]"
            )
            lines.append(
                f"    1차 수량: {plan['first_tranche_shares']}주 (목표 {plan['target_shares']}주)"
            )
            lines.append(f"    투자금: {plan['investment']:,.0f}원")
            lines.append(f"    손절가: {plan['stop_loss']:,.0f}원")
            lines.append(
                f"    최대 손실: {plan['risk_amount']:,.0f}원 (자산의 {plan['risk_pct']}%%)"
            )
            if plan.get("note"):
                lines.append(f"    [dim]ℹ️  {plan['note']}[/dim]")
        elif plan and plan.get("type") == "buy_blocked":
            lines.append("")
            lines.append(f"  [dim]💤 매수 차단: {plan['reason']}[/dim]")

        console.print(
            Panel(
                "\n".join(lines),
                title=f"🟢 {rec['name']} ({rec['ticker']}) — {rec['price']:,.0f}원",
                style="green",
            )
        )

    console.print()


if __name__ == "__main__":
    main()
