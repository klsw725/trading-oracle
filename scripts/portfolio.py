#!/usr/bin/env python3
"""포트폴리오 관리 — CRUD + 조회

사용법:
    uv run scripts/portfolio.py add 005930 55000 10 --reason "반도체"
    uv run scripts/portfolio.py add AAPL 200 10 --reason "AI"
    uv run scripts/portfolio.py remove 005930 --price 60000
    uv run scripts/portfolio.py remove 005930 --price 60000 -n 5     # 5주만 분할 매도
    uv run scripts/portfolio.py cash 5000000
    uv run scripts/portfolio.py show --json
    uv run scripts/portfolio.py history --json
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
    build_portfolio_summary_for_display,
    format_portfolio_alert,
    build_cash_summary_for_display,
    format_price_for_display,
    build_trade_record_display,
)
from src.data.market import fetch_ohlcv, get_ticker_name, is_us_ticker
from src.portfolio.tracker import (
    load_portfolio,
    add_position,
    remove_position,
    set_cash,
    get_cash_balance,
    adjust_cash_balance,
    update_positions,
    get_portfolio_summary,
)


def cmd_add(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    currency = "USD" if is_us_ticker(ticker) else "KRW"
    name = get_ticker_name(ticker)
    if not name:
        _error(args, f"종목 {ticker} 을(를) 찾을 수 없음")
        return

    price = args.price
    shares = args.shares
    reason = args.reason or ""
    stop_loss = args.stop_loss or price * 0.9
    invested = price * shares
    include_us = currency == "USD" or get_cash_balance(portfolio, "USD") > 0
    market_data = collect_market_data(include_us=include_us) if include_us else {}

    # 현금 차감
    cash_before = get_cash_balance(portfolio, currency)
    adjust_cash_balance(portfolio, -invested, currency)

    add_position(portfolio, ticker, name, price, shares, reason, stop_loss)
    cash_after = get_cash_balance(portfolio, currency)
    cash_summary = build_cash_summary_for_display(portfolio, market_data)

    if args.json:
        print(
            json_dump(
                {
                    "status": "ok",
                    "action": "add",
                    "ticker": ticker,
                    "name": name,
                    "currency": currency,
                    "price": price,
                    "price_display": format_price_for_display(
                        ticker, price, market_data
                    ),
                    "shares": shares,
                    "invested": invested,
                    "invested_display": format_price_for_display(
                        ticker, invested, market_data
                    ),
                    "stop_loss": stop_loss,
                    "stop_loss_display": format_price_for_display(
                        ticker, stop_loss, market_data
                    ),
                    "cash_krw": cash_summary["cash_krw"],
                    "cash_usd": cash_summary["cash_usd"],
                    "cash_display": cash_summary["cash_display"],
                }
            )
        )
    else:
        print(
            f"{name}({ticker}) 매수 기록: {format_price_for_display(ticker, price, market_data)} × {shares}주 = {format_price_for_display(ticker, invested, market_data)} (손절가: {format_price_for_display(ticker, stop_loss, market_data)})"
        )
        if cash_after < 0:
            print(
                f"  ⚠️ 현금 부족: {format_price_for_display(ticker, cash_before, market_data)} → {format_price_for_display(ticker, cash_after, market_data)}"
            )
        print(f"  보유 현금: {cash_summary['cash_display']}")


def cmd_remove(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    currency = "USD" if is_us_ticker(ticker) else "KRW"
    pos = next((p for p in portfolio["positions"] if p["ticker"] == ticker), None)
    if not pos:
        _error(args, f"{ticker} 은(는) 보유 종목이 아닙니다")
        return

    sell_price = args.price
    reason = args.reason or ""
    sell_shares = args.shares  # None이면 전량

    if not sell_price:
        ohlcv = fetch_ohlcv(ticker, days_back=5)
        if not ohlcv.empty:
            sell_price = float(ohlcv["close"].values[-1])
        else:
            sell_price = pos["entry_price"]

    actual_sell_shares = sell_shares if sell_shares is not None else pos["shares"]

    # 수량 검증
    if actual_sell_shares > pos["shares"]:
        _error(
            args,
            f"매도 수량({actual_sell_shares})이 보유 수량({pos['shares']})을 초과합니다",
        )
        return

    name = pos["name"]
    original_shares = pos["shares"]
    pnl_pct = (sell_price - pos["entry_price"]) / pos["entry_price"] * 100
    pnl_amt = (sell_price - pos["entry_price"]) * actual_sell_shares
    include_us = currency == "USD" or get_cash_balance(portfolio, "USD") > 0
    market_data = collect_market_data(include_us=include_us) if include_us else {}

    # 현금 가산
    proceeds = sell_price * actual_sell_shares

    try:
        remove_position(portfolio, ticker, sell_price, reason, shares=sell_shares)
    except ValueError as e:
        _error(args, str(e))
        return
    adjust_cash_balance(portfolio, proceeds, currency)

    leftover = original_shares - actual_sell_shares
    sell_label = (
        f"{actual_sell_shares}주"
        if sell_shares is not None
        else f"전량 {actual_sell_shares}주"
    )
    cash_summary = build_cash_summary_for_display(portfolio, market_data)

    if args.json:
        print(
            json_dump(
                {
                    "status": "ok",
                    "action": "remove",
                    "ticker": ticker,
                    "name": name,
                    "currency": currency,
                    "sell_price": sell_price,
                    "sell_price_display": format_price_for_display(
                        ticker, sell_price, market_data, include_exchange_rate=True
                    ),
                    "sell_shares": actual_sell_shares,
                    "remaining_shares": leftover,
                    "pnl_pct": pnl_pct,
                    "pnl_amount": pnl_amt,
                    "pnl_amount_display": format_price_for_display(
                        ticker, pnl_amt, market_data, include_exchange_rate=True
                    ),
                    "proceeds": proceeds,
                    "proceeds_display": format_price_for_display(
                        ticker, proceeds, market_data, include_exchange_rate=True
                    ),
                    "cash_krw": cash_summary["cash_krw"],
                    "cash_usd": cash_summary["cash_usd"],
                    "cash_display": cash_summary["cash_display"],
                }
            )
        )
    else:
        print(
            f"{name}({ticker}) 매도: {format_price_for_display(ticker, sell_price, market_data, include_exchange_rate=True)} × {sell_label} {format_price_for_display(ticker, pnl_amt, market_data, include_exchange_rate=True)} ({pnl_pct:+.1f}%%)"
        )
        if leftover > 0:
            print(
                f"  잔여 보유: {leftover}주 (평단가 {format_price_for_display(ticker, pos['entry_price'], market_data)})"
            )
        print(
            f"  보유 현금: {cash_summary['cash_display']} (+{format_price_for_display(ticker, proceeds, market_data, include_exchange_rate=True)})"
        )


def cmd_cash(args):
    portfolio = load_portfolio()
    currency = "USD" if args.usd else "KRW"
    include_us = currency == "USD" or get_cash_balance(portfolio, "USD") > 0
    market_data = collect_market_data(include_us=include_us) if include_us else {}
    set_cash(portfolio, args.amount, currency=currency)
    cash_summary = build_cash_summary_for_display(portfolio, market_data)
    if args.json:
        print(
            json_dump(
                {
                    "status": "ok",
                    "action": "cash",
                    "currency": currency,
                    "amount": args.amount,
                    "cash_krw": cash_summary["cash_krw"],
                    "cash_usd": cash_summary["cash_usd"],
                    "cash_display": cash_summary["cash_display"],
                }
            )
        )
    else:
        label = f"${args.amount:,.2f}" if currency == "USD" else f"{args.amount:,.0f}원"
        print(f"보유 현금({currency}): {label}")
        print(f"  전체 현금: {cash_summary['cash_display']}")


def cmd_show(args):
    portfolio = load_portfolio()
    positions = portfolio.get("positions", [])

    if positions:
        current_prices = {}
        for pos in positions:
            ohlcv = fetch_ohlcv(pos["ticker"], days_back=5)
            if not ohlcv.empty:
                current_prices[pos["ticker"]] = float(ohlcv["close"].values[-1])
        config = load_config()
        alerts = update_positions(
            portfolio, current_prices, config.get("trailing_stop_pct", 10)
        )
    else:
        alerts = []

    if args.json:
        include_us = (
            any(pos["ticker"].isalpha() for pos in positions)
            or get_cash_balance(portfolio, "USD") > 0
        )
        market_data = collect_market_data(include_us=include_us)
        summary_native = get_portfolio_summary(portfolio)
        summary_display = build_portfolio_summary_for_display(portfolio, market_data)
        print(
            json_dump(
                {
                    "summary": summary_display,
                    "summary_native": summary_native,
                    "positions": portfolio.get("positions", []),
                    "alerts": [format_portfolio_alert(a, market_data) for a in alerts],
                }
            )
        )
    else:
        from src.output.formatter import (
            console,
            print_header,
            print_portfolio_summary,
            print_alert,
        )

        include_us = (
            any(pos["ticker"].isalpha() for pos in positions)
            or get_cash_balance(portfolio, "USD") > 0
        )
        market_data = collect_market_data(include_us=include_us)
        print_header()
        print_portfolio_summary(portfolio, market_data)
        for alert in alerts:
            print_alert(format_portfolio_alert(alert, market_data))
        if not positions:
            console.print(
                "\n[dim]종목 추가: uv run scripts/portfolio.py add <종목코드> <매수가> <수량>[/dim]"
            )


def cmd_history(args):
    portfolio = load_portfolio()
    history = portfolio.get("history", [])
    include_us = any(is_us_ticker(trade["ticker"]) for trade in history)
    market_data = collect_market_data(include_us=include_us) if include_us else {}
    if args.json:
        print(
            json_dump(
                {
                    "history": history,
                    "history_display": [
                        build_trade_record_display(trade, market_data)
                        for trade in history
                    ],
                }
            )
        )
    else:
        from src.output.formatter import print_header, print_phase, print_trade_history

        print_header()
        print_phase("거래 내역")
        print_trade_history(portfolio, market_data)


def _error(args, message: str):
    if getattr(args, "json", False):
        print(json_dump({"status": "error", "message": message}))
    else:
        print(f"오류: {message}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 포트폴리오 관리")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add
    add_p = subparsers.add_parser("add", help="매수 기록")
    add_p.add_argument("ticker", help="종목코드")
    add_p.add_argument("price", type=float, help="매수가")
    add_p.add_argument("shares", type=int, help="수량")
    add_p.add_argument("--reason", "-r", help="매수 이유")
    add_p.add_argument(
        "--stop-loss", "-s", type=float, help="손절가, 기본 매수가의 90%%"
    )
    add_p.add_argument("--json", action="store_true", help="JSON 출력")

    # remove
    rm_p = subparsers.add_parser("remove", help="매도 기록")
    rm_p.add_argument("ticker", help="종목코드")
    rm_p.add_argument("--price", "-p", type=float, help="매도가")
    rm_p.add_argument("--shares", "-n", type=int, help="매도 수량 (미지정 시 전량)")
    rm_p.add_argument("--reason", "-r", help="매도 이유")
    rm_p.add_argument("--json", action="store_true", help="JSON 출력")

    # cash
    cash_p = subparsers.add_parser("cash", help="현금 설정")
    cash_p.add_argument("amount", type=float, help="금액")
    cash_p.add_argument("--usd", action="store_true", help="USD 현금 설정")
    cash_p.add_argument("--json", action="store_true", help="JSON 출력")

    # show
    show_p = subparsers.add_parser("show", help="포트폴리오 조회")
    show_p.add_argument("--json", action="store_true", help="JSON 출력")

    # history
    hist_p = subparsers.add_parser("history", help="거래 내역")
    hist_p.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()

    {
        "add": cmd_add,
        "remove": cmd_remove,
        "cash": cmd_cash,
        "show": cmd_show,
        "history": cmd_history,
    }[args.command](args)


if __name__ == "__main__":
    main()
