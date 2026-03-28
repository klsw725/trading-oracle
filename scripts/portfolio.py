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

from src.common import load_config, json_dump
from src.data.market import fetch_ohlcv, get_ticker_name
from src.portfolio.tracker import (
    load_portfolio,
    add_position,
    remove_position,
    set_cash,
    update_positions,
    get_portfolio_summary,
)


def cmd_add(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    name = get_ticker_name(ticker)
    if not name:
        _error(args, f"종목 {ticker} 을(를) 찾을 수 없음")
        return

    price = args.price
    shares = args.shares
    reason = args.reason or ""
    stop_loss = args.stop_loss or price * 0.9
    invested = price * shares

    # 현금 차감
    cash_before = portfolio.get("cash", 0)
    portfolio["cash"] = cash_before - invested

    add_position(portfolio, ticker, name, price, shares, reason, stop_loss)

    if args.json:
        print(json_dump({"status": "ok", "action": "add", "ticker": ticker, "name": name,
                          "price": price, "shares": shares, "invested": invested, "stop_loss": stop_loss,
                          "cash": portfolio["cash"]}))
    else:
        print(f"{name}({ticker}) 매수 기록: {price:,.0f}원 × {shares}주 = {invested:,.0f}원 (손절가: {stop_loss:,.0f}원)")
        if portfolio["cash"] < 0:
            print(f"  ⚠️ 현금 부족: {cash_before:,.0f}원 → {portfolio['cash']:,.0f}원")


def cmd_remove(args):
    portfolio = load_portfolio()
    ticker = args.ticker
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
        _error(args, f"매도 수량({actual_sell_shares})이 보유 수량({pos['shares']})을 초과합니다")
        return

    name = pos["name"]
    pnl_pct = (sell_price - pos["entry_price"]) / pos["entry_price"] * 100
    pnl_amt = (sell_price - pos["entry_price"]) * actual_sell_shares

    # 현금 가산
    proceeds = sell_price * actual_sell_shares
    portfolio["cash"] = portfolio.get("cash", 0) + proceeds

    try:
        remove_position(portfolio, ticker, sell_price, reason, shares=sell_shares)
    except ValueError as e:
        _error(args, str(e))
        return

    leftover = pos["shares"] - actual_sell_shares
    sell_label = f"{actual_sell_shares}주" if sell_shares is not None else f"전량 {actual_sell_shares}주"

    if args.json:
        print(json_dump({"status": "ok", "action": "remove", "ticker": ticker, "name": name,
                          "sell_price": sell_price, "sell_shares": actual_sell_shares,
                          "remaining_shares": leftover, "pnl_pct": pnl_pct, "pnl_amount": pnl_amt,
                          "proceeds": proceeds, "cash": portfolio["cash"]}))
    else:
        sign = "+" if pnl_pct >= 0 else ""
        print(f"{name}({ticker}) 매도: {sell_price:,.0f}원 × {sell_label} {sign}{pnl_amt:,.0f}원 ({sign}{pnl_pct:.1f}%%)")
        if leftover > 0:
            print(f"  잔여 보유: {leftover}주")
        print(f"  보유 현금: {portfolio['cash']:,.0f}원 (+{proceeds:,.0f}원)")


def cmd_cash(args):
    portfolio = load_portfolio()
    set_cash(portfolio, args.amount)
    if args.json:
        print(json_dump({"status": "ok", "action": "cash", "amount": args.amount}))
    else:
        print(f"보유 현금: {args.amount:,.0f}원")


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
        alerts = update_positions(portfolio, current_prices, config.get("trailing_stop_pct", 10))
    else:
        alerts = []

    if args.json:
        summary = get_portfolio_summary(portfolio)
        print(json_dump({
            "summary": summary,
            "positions": portfolio.get("positions", []),
            "alerts": [a["message"] for a in alerts],
        }))
    else:
        from src.output.formatter import console, print_header, print_portfolio_summary, print_alert
        print_header()
        print_portfolio_summary(portfolio)
        for alert in alerts:
            print_alert(alert["message"])
        if not positions:
            console.print("\n[dim]종목 추가: uv run scripts/portfolio.py add <종목코드> <매수가> <수량>[/dim]")


def cmd_history(args):
    portfolio = load_portfolio()
    if args.json:
        print(json_dump({"history": portfolio.get("history", [])}))
    else:
        from src.output.formatter import print_header, print_phase, print_trade_history
        print_header()
        print_phase("거래 내역")
        print_trade_history(portfolio)


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
    add_p.add_argument("--stop-loss", "-s", type=float, help="손절가, 기본 매수가의 90%%")
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
    cash_p.add_argument("--json", action="store_true", help="JSON 출력")

    # show
    show_p = subparsers.add_parser("show", help="포트폴리오 조회")
    show_p.add_argument("--json", action="store_true", help="JSON 출력")

    # history
    hist_p = subparsers.add_parser("history", help="거래 내역")
    hist_p.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()

    {"add": cmd_add, "remove": cmd_remove, "cash": cmd_cash,
     "show": cmd_show, "history": cmd_history}[args.command](args)


if __name__ == "__main__":
    main()
