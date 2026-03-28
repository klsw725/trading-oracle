#!/usr/bin/env python3
"""추천 성과 추적 — 리포트, 스냅샷 목록, 상세 조회

사용법:
    uv run scripts/performance.py report               # 최근 30일 성과 요약
    uv run scripts/performance.py report --days 60      # 최근 60일
    uv run scripts/performance.py report --json         # JSON 출력
    uv run scripts/performance.py list                  # 스냅샷 목록
    uv run scripts/performance.py detail 2026-03-28     # 특정 날짜 상세
"""

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import json_dump
from src.performance.tracker import (
    list_snapshots,
    load_snapshot,
    evaluate_snapshot,
    generate_report,
)


def cmd_report(args):
    report = generate_report(days_back=args.days)

    if args.json:
        print(json_dump(report))
        return

    from src.output.formatter import console
    from rich.table import Table
    from rich.panel import Panel

    if report["snapshots_count"] == 0:
        console.print("[dim]저장된 스냅샷이 없습니다. 다관점 분석을 먼저 실행하세요.[/dim]")
        return

    console.print(f"\n[bold]📊 추천 성과 리포트[/bold] ({report['period']}, 스냅샷 {report['snapshots_count']}개)\n")

    # 전체 합의 적중률
    consensus = report.get("consensus", {})
    if consensus:
        table = Table(title="전체 합의 적중률", show_header=True)
        table.add_column("평가 기간", style="bold")
        table.add_column("적중", justify="right")
        table.add_column("전체", justify="right")
        table.add_column("적중률", justify="right")
        for window, stats in sorted(consensus.items(), key=lambda x: int(x[0])):
            rate_str = f"{stats['rate']}%" if stats["rate"] is not None else "-"
            color = "green" if stats.get("rate", 0) and stats["rate"] >= 60 else "red" if stats.get("rate") is not None else "dim"
            table.add_row(f"{window}일", str(stats["hits"]), str(stats["total"]), f"[{color}]{rate_str}[/{color}]")
        console.print(table)
        console.print()

    # 관점별 적중률
    by_persp = report.get("by_perspective", {})
    for window in sorted(by_persp.keys(), key=int):
        persp_data = by_persp[window]
        if not persp_data:
            continue
        table = Table(title=f"관점별 적중률 ({window}일)", show_header=True)
        table.add_column("관점", style="bold")
        table.add_column("적중", justify="right")
        table.add_column("전체", justify="right")
        table.add_column("적중률", justify="right")
        for name in ("kwangsoo", "ouroboros", "quant", "macro", "value"):
            stats = persp_data.get(name)
            if not stats:
                continue
            rate_str = f"{stats['rate']}%" if stats["rate"] is not None else "-"
            color = "green" if stats.get("rate", 0) and stats["rate"] >= 60 else "red" if stats.get("rate") is not None else "dim"
            table.add_row(name, str(stats["hits"]), str(stats["total"]), f"[{color}]{rate_str}[/{color}]")
        console.print(table)
        console.print()

    # 합의도별 적중률
    by_conf = report.get("by_confidence", {})
    for window in sorted(by_conf.keys(), key=int):
        conf_data = by_conf[window]
        if not conf_data:
            continue
        table = Table(title=f"합의도별 적중률 ({window}일)", show_header=True)
        table.add_column("합의도", style="bold")
        table.add_column("적중", justify="right")
        table.add_column("전체", justify="right")
        table.add_column("적중률", justify="right")
        order = ["very_high", "high", "moderate", "low", "insufficient"]
        labels = {"very_high": "만장일치", "high": "강한 합의", "moderate": "약한 합의", "low": "분기", "insufficient": "판정 보류"}
        for conf in order:
            stats = conf_data.get(conf)
            if not stats:
                continue
            rate_str = f"{stats['rate']}%" if stats["rate"] is not None else "-"
            color = "green" if stats.get("rate", 0) and stats["rate"] >= 60 else "red" if stats.get("rate") is not None else "dim"
            table.add_row(labels.get(conf, conf), str(stats["hits"]), str(stats["total"]), f"[{color}]{rate_str}[/{color}]")
        console.print(table)
        console.print()


def cmd_list(args):
    dates = list_snapshots()

    if args.json:
        print(json_dump({"snapshots": dates, "count": len(dates)}))
        return

    from src.output.formatter import console

    if not dates:
        console.print("[dim]저장된 스냅샷이 없습니다.[/dim]")
        return

    console.print(f"\n[bold]📋 스냅샷 목록[/bold] ({len(dates)}개)\n")
    for d in dates:
        snap = load_snapshot(d)
        tickers = list(snap["recommendations"].keys()) if snap else []
        console.print(f"  {d}  —  {len(tickers)}개 종목")


def cmd_detail(args):
    snapshot = load_snapshot(args.date)
    if not snapshot:
        msg = f"스냅샷 없음: {args.date}"
        if args.json:
            print(json_dump({"status": "error", "message": msg}))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    evaluation = evaluate_snapshot(snapshot)

    if args.json:
        print(json_dump(evaluation))
        return

    from src.output.formatter import console
    from rich.table import Table

    console.print(f"\n[bold]📊 {args.date} 추천 상세[/bold]\n")

    for ticker, ev in evaluation["evaluations"].items():
        verdict_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(ev["consensus_verdict"], "⚪")
        console.print(f"  {verdict_emoji} [bold]{ev['name']}[/bold] ({ticker}) — {ev['consensus_verdict']} ({ev['consensus_confidence']})")
        console.print(f"    추천가: {ev['recommendation_price']:,.0f}원")

        for window, w_data in ev["windows"].items():
            if w_data["current_price"] is None:
                console.print(f"    {window}일: [dim]데이터 부족[/dim]")
            else:
                hit_str = "[green]✅ 적중[/green]" if w_data["hit"] else "[red]❌ 미적중[/red]" if w_data["hit"] is False else "[dim]미평가[/dim]"
                ret_color = "green" if w_data["return_pct"] >= 0 else "red"
                console.print(f"    {window}일: {w_data['current_price']:,.0f}원 [{ret_color}]{w_data['return_pct']:+.1f}%[/{ret_color}] {hit_str}")

        # 관점별
        table = Table(show_header=True, padding=(0, 1))
        table.add_column("관점", style="bold", width=12)
        table.add_column("판정", width=6)
        for days in ("5", "20"):
            table.add_column(f"{days}일", justify="center", width=8)

        for p_name in ("kwangsoo", "ouroboros", "quant", "macro", "value"):
            p_data = ev["perspective_hits"].get(p_name)
            if not p_data:
                continue
            cols = [p_name, p_data["verdict"]]
            for days in ("5", "20"):
                hit = p_data.get(days)
                if hit is True:
                    cols.append("[green]✅[/green]")
                elif hit is False:
                    cols.append("[red]❌[/red]")
                else:
                    cols.append("[dim]-[/dim]")
            table.add_row(*cols)

        console.print(table)
        console.print()


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 추천 성과 추적")
    subparsers = parser.add_subparsers(dest="command")

    # report
    report_parser = subparsers.add_parser("report", help="성과 리포트")
    report_parser.add_argument("--days", type=int, default=30, help="최근 N일 (기본: 30)")
    report_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # list
    list_parser = subparsers.add_parser("list", help="스냅샷 목록")
    list_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # detail
    detail_parser = subparsers.add_parser("detail", help="특정 날짜 상세")
    detail_parser.add_argument("date", help="날짜 (YYYY-MM-DD)")
    detail_parser.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {"report": cmd_report, "list": cmd_list, "detail": cmd_detail}
    cmds[args.command](args)


if __name__ == "__main__":
    main()
