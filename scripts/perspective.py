#!/usr/bin/env python3
"""단일 관점 분석 — 특정 관점으로만 종목 분석

사용법:
    uv run scripts/perspective.py --kwangsoo -t 005930 --json
    uv run scripts/perspective.py --quant -t 005930 000660
    uv run scripts/perspective.py --macro -t 005930
    uv run scripts/perspective.py --ouroboros -t 005930
    uv run scripts/perspective.py --value -t 005930
"""

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import (
    load_config,
    json_dump,
    collect_market_data,
    analyze_tickers,
    run_single_perspective,
)
from src.portfolio.tracker import load_portfolio

PERSPECTIVES = ["kwangsoo", "ouroboros", "quant", "macro", "value"]


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 단일 관점 분석")
    parser.add_argument("--tickers", "-t", nargs="+", required=True, help="분석 종목")
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    group = parser.add_mutually_exclusive_group(required=True)
    for p in PERSPECTIVES:
        group.add_argument(f"--{p}", action="store_true", help=f"{p} 관점")

    args = parser.parse_args()
    perspective_name = next(p for p in PERSPECTIVES if getattr(args, p, False))

    config = load_config()
    portfolio = load_portfolio()
    market_data = collect_market_data()

    signals_data = analyze_tickers(set(args.tickers), config)
    if not signals_data:
        if args.json:
            print(json_dump({"status": "error", "message": "분석 가능한 종목이 없습니다"}))
        else:
            print("분석 가능한 종목이 없습니다", file=sys.stderr)
        sys.exit(1)

    results = run_single_perspective(perspective_name, signals_data, portfolio, market_data, config)

    if "error" in results:
        if args.json:
            print(json_dump({"status": "error", "message": results["error"]}))
        else:
            print(f"오류: {results['error']}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json_dump({"perspective": perspective_name, "results": results}))
    else:
        from src.output.formatter import console
        from rich.panel import Panel

        verdict_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "N/A": "⚪"}

        for ticker, result in results.items():
            emoji = verdict_emoji.get(result["verdict"], "⚪")
            lines = [
                f"[bold]판정:[/bold] {emoji} {result['verdict']} (확신도: {result['confidence']:.1%})",
                f"[bold]요약:[/bold] {result['reason']}",
                "",
            ]
            for r in result.get("reasoning", []):
                lines.append(f"  • {r[:80]}")

            vs = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(result["verdict"], "white")
            name = next((s["name"] for s in signals_data if s["ticker"] == ticker), ticker)
            console.print(Panel("\n".join(lines), title=f"[{vs}]{perspective_name}[/{vs}] — {name} ({ticker})", style=vs))


if __name__ == "__main__":
    main()
