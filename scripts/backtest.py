"""시그널 백테스트 CLI — Phase 18 M3

Usage:
    uv run scripts/backtest.py --period 6m
    uv run scripts/backtest.py --period 1y --tickers 005930,000660,005380
    uv run scripts/backtest.py --period 6m --no-forex
    uv run scripts/backtest.py --period 6m --compare  # forex ON vs OFF 비교
    uv run scripts/backtest.py --period 6m --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common import ensure_project_root, load_config, NumEncoder

ensure_project_root()


def parse_period(s: str) -> int:
    """기간 문자열을 거래일 수로 변환."""
    s = s.lower().strip()
    if s.endswith("m"):
        months = int(s[:-1])
        return months * 21  # 월 ~21 거래일
    elif s.endswith("y"):
        years = int(s[:-1])
        return years * 252
    elif s.endswith("d"):
        return int(s[:-1])
    return int(s)


# 시총 상위 대표 종목 (기본값)
DEFAULT_TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005380": "현대차",
    "006400": "삼성SDI",
    "051910": "LG화학",
    "035420": "NAVER",
    "035720": "카카오",
    "105560": "KB금융",
    "012450": "한화에어로스페이스",
    "003670": "포스코퓨처엠",
}


def main():
    parser = argparse.ArgumentParser(description="시그널 백테스트")
    parser.add_argument("--period", default="6m", help="백테스트 기간 (6m, 1y, 2y, 120d)")
    parser.add_argument("--tickers", help="종목코드 (쉼표 구분)")
    parser.add_argument("--no-forex", action="store_true", help="환율 팩터 비활성화")
    parser.add_argument("--compare", action="store_true", help="forex ON/OFF 비교")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument("--capital", type=float, default=10_000_000, help="초기 자본금")
    args = parser.parse_args()

    config = load_config()
    period_days = parse_period(args.period)

    if args.tickers:
        ticker_list = [t.strip() for t in args.tickers.split(",")]
        from src.data.market import get_ticker_name
        ticker_names = {}
        for t in ticker_list:
            name = get_ticker_name(t)
            ticker_names[t] = name if name else t
    else:
        ticker_names = dict(DEFAULT_TICKERS)
        ticker_list = list(ticker_names.keys())

    from src.backtest.engine import run_backtest, BacktestConfig
    from src.backtest.metrics import compute_metrics

    signal_config = config.get("signals", {})
    forex_config = config.get("forex", {})

    def run_one(use_forex: bool, label: str) -> dict:
        bt_config = BacktestConfig(
            initial_capital=args.capital,
            max_positions=config.get("max_positions", 3),
            min_votes=signal_config.get("min_votes", 4),
            use_forex=use_forex,
        )

        if not args.json:
            print(f"\n{'='*50}")
            print(f"  백테스트: {label}")
            print(f"  기간: {args.period} ({period_days}거래일)")
            print(f"  종목: {len(ticker_list)}개")
            print(f"  자본: {args.capital:,.0f}원")
            print(f"  환율팩터: {'ON' if use_forex else 'OFF'}")
            print(f"{'='*50}")

        def progress(cur, total):
            if not args.json and total > 0:
                pct = cur / total * 100
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                print(f"\r  [{bar}] {pct:.0f}%% ({cur}/{total}일)", end="", flush=True)

        result = run_backtest(
            tickers=ticker_list,
            ticker_names=ticker_names,
            period_days=period_days,
            config=bt_config,
            signal_config=signal_config,
            forex_config=forex_config if use_forex else None,
            on_progress=progress if not args.json else None,
        )

        if not args.json:
            print()  # 진행바 다음 줄

        if "error" in result:
            if not args.json:
                print(f"  ❌ {result['error']}")
            return {"error": result["error"]}

        metrics = compute_metrics(result["equity_curve"], result["trades"])
        result["metrics"] = metrics
        return result

    if args.compare:
        result_on = run_one(True, "환율 팩터 ON")
        result_off = run_one(False, "환율 팩터 OFF")

        if args.json:
            output = {"forex_on": result_on, "forex_off": result_off}
            print(json.dumps(output, ensure_ascii=False, indent=2, cls=NumEncoder))
        else:
            _print_comparison(result_on, result_off)
    else:
        use_forex = not args.no_forex
        label = "환율 팩터 ON" if use_forex else "환율 팩터 OFF"
        result = run_one(use_forex, label)

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, cls=NumEncoder))
        elif "error" not in result:
            _print_result(result)


def _print_result(result: dict):
    """Rich 없이 단순 텍스트 출력."""
    m = result.get("metrics", {})
    print(f"\n📊 백테스트 결과")
    print(f"  초기 자본:    {m.get('initial_capital', 0):>14,}원")
    print(f"  최종 가치:    {m.get('final_value', 0):>14,}원")
    print(f"  누적 수익률:  {m.get('total_return_pct', 0):>13.2f}%%")
    print(f"  CAGR:         {m.get('cagr_pct', 0):>13.2f}%%")
    print(f"  샤프 비율:    {m.get('sharpe_ratio', 0):>13.2f}")
    print(f"  MDD:          {m.get('mdd_pct', 0):>13.2f}%%")
    print(f"  총 거래:      {m.get('total_trades', 0):>13}건")
    print(f"  승률:         {m.get('win_rate_pct', 0):>13.1f}%%")
    print(f"  평균 수익:    {m.get('avg_win_pct', 0):>13.2f}%%")
    print(f"  평균 손실:    {m.get('avg_loss_pct', 0):>13.2f}%%")
    print(f"  손익비:       {m.get('profit_factor', 0):>13}")
    print(f"  평균 보유:    {m.get('avg_hold_days', 0):>12.1f}일")

    trades = result.get("trades", [])
    if trades:
        print(f"\n📋 거래 내역 (최근 10건)")
        for t in trades[-10:]:
            emoji = "🟢" if t["pnl_pct"] > 0 else "🔴"
            print(f"  {emoji} {t['name']} {t['entry_date']}→{t['exit_date']} "
                  f"{t['pnl_pct']:+.1f}%% ({t['exit_reason']})")

    final = result.get("final_positions", [])
    if final:
        print(f"\n📦 미청산 포지션")
        for p in final:
            print(f"  {p['name']}: {p['entry_price']:,.0f}→{p['current_price']:,.0f} ({p['pnl_pct']:+.1f}%%)")


def _print_comparison(on: dict, off: dict):
    """환율 ON/OFF 비교 출력."""
    if "error" in on or "error" in off:
        print("비교 불가")
        return

    m_on = on.get("metrics", {})
    m_off = off.get("metrics", {})

    print(f"\n📊 환율 팩터 A/B 비교")
    print(f"{'지표':<16} {'ON':>12} {'OFF':>12} {'차이':>12}")
    print(f"{'-'*52}")

    for key, label, fmt in [
        ("total_return_pct", "누적 수익률", ".2f"),
        ("cagr_pct", "CAGR", ".2f"),
        ("sharpe_ratio", "샤프 비율", ".2f"),
        ("mdd_pct", "MDD", ".2f"),
        ("win_rate_pct", "승률", ".1f"),
        ("total_trades", "거래 수", "d"),
    ]:
        v_on = m_on.get(key, 0)
        v_off = m_off.get(key, 0)
        diff = v_on - v_off if isinstance(v_on, (int, float)) and isinstance(v_off, (int, float)) else 0

        if fmt == "d":
            print(f"{label:<16} {v_on:>12} {v_off:>12} {diff:>+12}")
        else:
            print(f"{label:<16} {v_on:>12{fmt}}%% {v_off:>12{fmt}}%% {diff:>+12{fmt}}%%")


if __name__ == "__main__":
    main()
