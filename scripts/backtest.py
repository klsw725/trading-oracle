#!/usr/bin/env python3
"""시그널 백테스트 — 과거 OHLCV 기반 기술 시그널 적중률 검증

사용법:
    uv run scripts/backtest.py 005930                   # 삼성전자 1년 백테스트
    uv run scripts/backtest.py 005930 000660 035420      # 여러 종목
    uv run scripts/backtest.py 005930 --days 500         # 기간 지정 (캘린더일)
    uv run scripts/backtest.py 005930 --windows 5 10 20  # 평가 윈도우 지정
    uv run scripts/backtest.py 005930 --json             # JSON 출력
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import json_dump, load_config
from src.data.market import fetch_ohlcv, get_ticker_name
from src.signals.technical import compute_signals


# 적중 판정 기준 — performance/tracker.py 와 동일
_HIT_CRITERIA = {
    ("BUY", 5): ("positive", 0.0),
    ("BUY", 20): ("positive", 3.0),
    ("SELL", 5): ("negative", 0.0),
    ("SELL", 20): ("negative", 3.0),
    ("HOLD", 5): ("neutral", 3.0),
    ("HOLD", 20): ("neutral", 5.0),
}

_VERDICT_MAP = {"BULLISH": "BUY", "BEARISH": "SELL", "NEUTRAL": "HOLD"}


def _check_hit(verdict: str, return_pct: float, window: int) -> bool | None:
    mapped = _VERDICT_MAP.get(verdict, verdict)
    criteria = _HIT_CRITERIA.get((mapped, window))
    if not criteria:
        return None
    direction, threshold = criteria
    if direction == "positive":
        return bool(return_pct > threshold)
    elif direction == "negative":
        return bool(return_pct < -threshold)
    elif direction == "neutral":
        return bool(abs(return_pct) < threshold)
    return None


def run_backtest(
    ticker: str,
    days_back: int = 450,
    config: dict | None = None,
    eval_windows: list[int] | None = None,
    min_warmup: int = 60,
) -> dict:
    """단일 종목 시그널 백테스트 실행.

    Args:
        ticker: 종목코드
        days_back: OHLCV 로드 기간 (캘린더일)
        config: signals 설정
        eval_windows: 평가 윈도우 (거래일 기준)
        min_warmup: compute_signals에 필요한 최소 데이터 일수

    Returns:
        {"ticker", "name", "period", "total_days", "signals", "stats"}
    """
    if config is None:
        config = load_config()
    if eval_windows is None:
        eval_windows = [5, 20]

    name = get_ticker_name(ticker) or ticker
    ohlcv = fetch_ohlcv(ticker, days_back=days_back)

    if ohlcv.empty or len(ohlcv) < min_warmup + max(eval_windows) + 1:
        return {
            "ticker": ticker,
            "name": name,
            "error": f"데이터 부족: {len(ohlcv)}일 (최소 {min_warmup + max(eval_windows) + 1}일 필요)",
        }

    max_window = max(eval_windows)
    signals = []

    for t in range(min_warmup, len(ohlcv) - max_window):
        slice_df = ohlcv.iloc[: t + 1].copy()
        result = compute_signals(slice_df, config)
        if "error" in result:
            continue

        entry_price = result["current_price"]
        verdict = result["verdict"]
        date = ohlcv.index[t]

        windows = {}
        for w in eval_windows:
            future_price = float(ohlcv.iloc[t + w]["close"])
            ret = (future_price - entry_price) / entry_price * 100
            hit = _check_hit(verdict, ret, w)
            windows[w] = {
                "future_price": future_price,
                "return_pct": round(ret, 2),
                "hit": hit,
            }

        signals.append({
            "date": date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
            "price": entry_price,
            "verdict": verdict,
            "bull_votes": result["bull_votes"],
            "bear_votes": result["bear_votes"],
            "rsi": round(result["signals"]["rsi"]["value"], 1),
            "windows": windows,
        })

    stats = _compute_stats(signals, eval_windows)

    first_date = signals[0]["date"] if signals else ""
    last_date = signals[-1]["date"] if signals else ""

    return {
        "ticker": ticker,
        "name": name,
        "period": f"{first_date} ~ {last_date}",
        "total_days": len(signals),
        "signals": signals,
        "stats": stats,
    }


def _compute_stats(signals: list[dict], eval_windows: list[int]) -> dict:
    """백테스트 결과 통계 산출."""
    if not signals:
        return {}

    # 판정 분포
    verdicts = [s["verdict"] for s in signals]
    distribution = {
        "BULLISH": verdicts.count("BULLISH"),
        "BEARISH": verdicts.count("BEARISH"),
        "NEUTRAL": verdicts.count("NEUTRAL"),
    }

    # 윈도우별 × 판정별 통계
    by_window = {}
    for w in eval_windows:
        window_stats = {}
        for verdict in ("BULLISH", "BEARISH", "NEUTRAL"):
            subset = [s for s in signals if s["verdict"] == verdict]
            if not subset:
                window_stats[verdict] = {
                    "count": 0, "hits": 0, "hit_rate": None,
                    "avg_return": None, "median_return": None,
                    "profit_factor": None, "best": None, "worst": None,
                }
                continue

            returns = [s["windows"][w]["return_pct"] for s in subset]
            hits = [s["windows"][w]["hit"] for s in subset]
            hit_count = sum(1 for h in hits if h is True)
            eval_count = sum(1 for h in hits if h is not None)

            pos_returns = [r for r in returns if r > 0]
            neg_returns = [r for r in returns if r < 0]
            gross_profit = sum(pos_returns) if pos_returns else 0
            gross_loss = abs(sum(neg_returns)) if neg_returns else 0

            window_stats[verdict] = {
                "count": len(subset),
                "hits": hit_count,
                "evaluated": eval_count,
                "hit_rate": round(hit_count / eval_count * 100, 1) if eval_count > 0 else None,
                "avg_return": round(np.mean(returns), 2),
                "median_return": round(np.median(returns), 2),
                "std_return": round(np.std(returns), 2),
                "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
                "win_rate": round(len(pos_returns) / len(returns) * 100, 1) if returns else None,
                "best": round(max(returns), 2),
                "worst": round(min(returns), 2),
            }

        # 전체 (BULLISH 매수 + BEARISH 공매도 시뮬레이션)
        all_returns = []
        for s in signals:
            ret = s["windows"][w]["return_pct"]
            if s["verdict"] == "BULLISH":
                all_returns.append(ret)
            elif s["verdict"] == "BEARISH":
                all_returns.append(-ret)  # 공매도 방향

        if all_returns:
            cumulative = np.cumsum(all_returns)
            peak = np.maximum.accumulate(cumulative)
            drawdown = cumulative - peak
            max_dd = float(np.min(drawdown))

            window_stats["strategy"] = {
                "total_return": round(sum(all_returns), 2),
                "avg_return_per_signal": round(np.mean(all_returns), 2),
                "max_drawdown": round(max_dd, 2),
                "sharpe_approx": round(np.mean(all_returns) / np.std(all_returns), 2) if np.std(all_returns) > 0 else None,
            }

        by_window[str(w)] = window_stats

    return {
        "distribution": distribution,
        "by_window": by_window,
    }


def print_backtest_report(result: dict, eval_windows: list[int]):
    """Rich 테이블로 백테스트 결과 출력."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    if "error" in result:
        console.print(f"[red]❌ {result['name']} ({result['ticker']}): {result['error']}[/red]")
        return

    stats = result["stats"]
    dist = stats["distribution"]

    # 헤더
    console.print(f"\n[bold]📊 {result['name']} ({result['ticker']}) 시그널 백테스트[/bold]")
    console.print(f"  기간: {result['period']}  ({result['total_days']}거래일)")
    console.print(f"  시그널 분포: BULLISH {dist['BULLISH']}일 / BEARISH {dist['BEARISH']}일 / NEUTRAL {dist['NEUTRAL']}일\n")

    for w in eval_windows:
        ws = stats["by_window"][str(w)]

        table = Table(title=f"{w}일 후 성과", show_header=True, padding=(0, 1))
        table.add_column("판정", style="bold", width=10)
        table.add_column("횟수", justify="right", width=6)
        table.add_column("적중률", justify="right", width=8)
        table.add_column("승률", justify="right", width=8)
        table.add_column("평균", justify="right", width=8)
        table.add_column("중앙값", justify="right", width=8)
        table.add_column("표준편차", justify="right", width=8)
        table.add_column("손익비", justify="right", width=8)
        table.add_column("최고", justify="right", width=8)
        table.add_column("최저", justify="right", width=8)

        for verdict, emoji in [("BULLISH", "🟢"), ("BEARISH", "🔴"), ("NEUTRAL", "🟡")]:
            vs = ws.get(verdict, {})
            if vs.get("count", 0) == 0:
                table.add_row(f"{emoji} {verdict}", "0", "-", "-", "-", "-", "-", "-", "-", "-")
                continue

            hr = vs.get("hit_rate")
            hr_str = f"{hr}%" if hr is not None else "-"
            hr_color = "green" if hr and hr >= 55 else "red" if hr is not None else "dim"

            wr = vs.get("win_rate")
            wr_str = f"{wr}%" if wr is not None else "-"

            pf = vs.get("profit_factor")
            pf_str = f"{pf}" if pf is not None else "-"
            pf_color = "green" if pf and pf >= 1.0 else "red" if pf is not None else "dim"

            avg_r = vs.get("avg_return")
            avg_color = "green" if avg_r and avg_r > 0 else "red" if avg_r is not None else "dim"

            table.add_row(
                f"{emoji} {verdict}",
                str(vs["count"]),
                f"[{hr_color}]{hr_str}[/{hr_color}]",
                wr_str,
                f"[{avg_color}]{avg_r:+.2f}%[/{avg_color}]" if avg_r is not None else "-",
                f"{vs['median_return']:+.2f}%" if vs.get("median_return") is not None else "-",
                f"{vs['std_return']:.2f}%" if vs.get("std_return") is not None else "-",
                f"[{pf_color}]{pf_str}[/{pf_color}]",
                f"[green]{vs['best']:+.2f}%[/green]" if vs.get("best") is not None else "-",
                f"[red]{vs['worst']:+.2f}%[/red]" if vs.get("worst") is not None else "-",
            )

        console.print(table)

        # 전략 요약
        strat = ws.get("strategy")
        if strat:
            sr = strat.get("sharpe_approx")
            sr_str = f"{sr:.2f}" if sr is not None else "-"
            sr_color = "green" if sr and sr > 0.5 else "yellow" if sr and sr > 0 else "red"
            console.print(
                f"  [dim]전략 (BULL 매수 + BEAR 공매도):[/dim] "
                f"누적 {strat['total_return']:+.1f}% / "
                f"시그널당 {strat['avg_return_per_signal']:+.2f}% / "
                f"MDD {strat['max_drawdown']:.1f}% / "
                f"샤프 [{sr_color}]{sr_str}[/{sr_color}]"
            )
        console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Trading Oracle — 시그널 백테스트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("tickers", nargs="+", help="종목코드 (예: 005930 000660)")
    parser.add_argument("--days", type=int, default=450, help="OHLCV 로드 기간, 캘린더일 (기본: 450)")
    parser.add_argument("--windows", type=int, nargs="+", default=[5, 20], help="평가 윈도우, 거래일 (기본: 5 20)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()
    config = load_config()

    results = []
    for ticker in args.tickers:
        result = run_backtest(
            ticker,
            days_back=args.days,
            config=config,
            eval_windows=args.windows,
        )
        results.append(result)

    if args.json:
        # signals 리스트는 대용량이므로 stats만 출력
        output = []
        for r in results:
            entry = {k: v for k, v in r.items() if k != "signals"}
            entry["signal_count"] = len(r.get("signals", []))
            output.append(entry)
        print(json_dump(output))
    else:
        for result in results:
            print_backtest_report(result, args.windows)


if __name__ == "__main__":
    main()
