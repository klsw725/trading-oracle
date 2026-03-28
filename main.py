"""Trading Oracle — 다관점 투자 판정 에이전트

사용법:
    uv run main.py                                    # 다관점 분석 (5개 관점 + 합의도)
    uv run main.py --tickers 005930 000660             # 추가 종목도 함께 분석
    uv run main.py --screen                            # 주도주 스크리닝 포함
    uv run main.py --no-llm                            # 시그널만 (LLM 없이)
    uv run main.py --legacy                            # 기존 단일 관점 분석
    uv run main.py --json                              # JSON 출력 (shacs-bot 연동용)
    uv run main.py codex-login                         # Codex OAuth 로그인

    uv run main.py add 005930 55000 10                 # 매수 기록: 종목 매수가 수량
    uv run main.py add 005930 55000 10 --reason "반도체 수출 증가"
    uv run main.py remove 005930                       # 매도 기록
    uv run main.py remove 005930 --price 60000         # 매도가 기록
    uv run main.py cash 5000000                        # 현금 설정
    uv run main.py portfolio                           # 포트폴리오 조회
    uv run main.py portfolio --json                    # 포트폴리오 JSON
    uv run main.py history                             # 거래 내역

scripts/ 진입점:
    uv run scripts/daily.py --json                     # 일일 분석
    uv run scripts/portfolio.py show --json            # 포트폴리오
    uv run scripts/screen.py --json                    # 스크리닝
    uv run scripts/perspective.py --kwangsoo -t 005930  # 단일 관점
"""

import argparse
import sys

from src.common import (
    ensure_project_root,
    load_config,
    json_dump,
    collect_market_data,
    collect_tickers,
    analyze_tickers,
    run_multi_perspective,
    build_signals_json,
)
from src.data.market import fetch_ohlcv, get_ticker_name
from src.portfolio.tracker import (
    load_portfolio,
    add_position,
    remove_position,
    set_cash,
    update_positions,
    get_portfolio_summary,
)
from src.output.formatter import (
    console,
    print_header,
    print_phase,
    print_loading,
    print_error,
    print_success,
    print_signal_card,
    print_analysis,
    print_portfolio_summary,
    print_alert,
    print_trade_history,
)


def _print_consensus_card(name: str, ticker: str, consensus: dict):
    """다관점 합의 결과를 터미널에 출력"""
    from rich.panel import Panel

    verdict_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "N/A": "⚪", "DIVIDED": "🔶", "INSUFFICIENT": "⚫"}
    confidence_colors = {"very_high": "bold green", "high": "green", "moderate": "yellow", "low": "red", "insufficient": "dim"}

    lines = []
    votes = consensus["vote_summary"]
    cc = confidence_colors.get(consensus["confidence"], "white")
    weighted_tag = " [dim](가중)[/dim]" if consensus.get("weighted") else ""
    lines.append(f"[bold]합의도:[/bold] [{cc}]{consensus['consensus_label']}[/{cc}]{weighted_tag}")
    lines.append(f"[bold]투표:[/bold] 매수 {votes.get('BUY', 0)} / 매도 {votes.get('SELL', 0)} / 관망 {votes.get('HOLD', 0)} / N/A {votes.get('N/A', 0)}")
    lines.append("")

    for p in consensus.get("perspectives", []):
        emoji = verdict_emoji.get(p["verdict"], "⚪")
        lines.append(f"  {emoji} [bold]{p['perspective']}[/bold]: {p['verdict']} — {p.get('reason', '')[:60]}")

    if consensus.get("majority_reasoning"):
        lines.append("")
        for r in consensus["majority_reasoning"][:3]:
            lines.append(f"  [dim]{r[:80]}[/dim]")

    vs = {"BUY": "green", "SELL": "red", "HOLD": "yellow", "DIVIDED": "magenta", "INSUFFICIENT": "dim"}.get(consensus["consensus_verdict"], "white")
    console.print(Panel("\n".join(lines), title=f"📊 {name} ({ticker}) — [{vs}]{consensus['consensus_verdict']}[/{vs}]", style=vs))


# --- Subcommands (thin wrappers) ---

def cmd_add(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    name = get_ticker_name(ticker)
    if not name:
        print_error(f"종목 {ticker} 을(를) 찾을 수 없음")
        return

    price, shares = args.price, args.shares
    reason = args.reason or ""
    stop_loss = args.stop_loss or price * 0.9

    add_position(portfolio, ticker, name, price, shares, reason, stop_loss)
    invested = price * shares

    if getattr(args, "json", False):
        print(json_dump({"status": "ok", "action": "add", "ticker": ticker, "name": name,
                          "price": price, "shares": shares, "invested": invested, "stop_loss": stop_loss}))
    else:
        print_success(f"{name}({ticker}) 매수 기록 완료: {price:,.0f}원 × {shares}주 = {invested:,.0f}원 (손절가: {stop_loss:,.0f}원)")


def cmd_remove(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    pos = next((p for p in portfolio["positions"] if p["ticker"] == ticker), None)
    if not pos:
        if getattr(args, "json", False):
            print(json_dump({"status": "error", "message": f"{ticker} 은(는) 보유 종목이 아닙니다"}))
        else:
            print_error(f"{ticker} 은(는) 보유 종목이 아닙니다")
        return

    sell_price = args.price
    reason = args.reason or ""
    if not sell_price:
        ohlcv = fetch_ohlcv(ticker, days_back=5)
        sell_price = float(ohlcv["close"].values[-1]) if not ohlcv.empty else pos["entry_price"]

    name = pos["name"]
    pnl_pct = (sell_price - pos["entry_price"]) / pos["entry_price"] * 100
    pnl_amt = (sell_price - pos["entry_price"]) * pos["shares"]
    remove_position(portfolio, ticker, sell_price, reason)

    if getattr(args, "json", False):
        print(json_dump({"status": "ok", "action": "remove", "ticker": ticker, "name": name,
                          "sell_price": sell_price, "pnl_pct": pnl_pct, "pnl_amount": pnl_amt}))
    else:
        pnl_color = "green" if pnl_pct >= 0 else "red"
        console.print(f"[bold]{name}({ticker}) 매도 완료[/bold]: {sell_price:,.0f}원 × {pos['shares']}주 [{pnl_color}]{pnl_amt:+,.0f}원 ({pnl_pct:+.1f}%)[/{pnl_color}]")


def cmd_cash(args):
    portfolio = load_portfolio()
    set_cash(portfolio, args.amount)
    if getattr(args, "json", False):
        print(json_dump({"status": "ok", "action": "cash", "amount": args.amount}))
    else:
        print_success(f"보유 현금: {args.amount:,.0f}원으로 설정 완료")


def cmd_portfolio(args):
    portfolio = load_portfolio()
    positions = portfolio.get("positions", [])

    alerts = []
    if positions:
        current_prices = {}
        for pos in positions:
            ohlcv = fetch_ohlcv(pos["ticker"], days_back=5)
            if not ohlcv.empty:
                current_prices[pos["ticker"]] = float(ohlcv["close"].values[-1])
        config = load_config()
        alerts = update_positions(portfolio, current_prices, config.get("trailing_stop_pct", 10))

    if getattr(args, "json", False):
        summary = get_portfolio_summary(portfolio)
        print(json_dump({"summary": summary, "positions": portfolio.get("positions", []),
                          "alerts": [a["message"] for a in alerts]}))
    else:
        print_header()
        print_portfolio_summary(portfolio)
        for alert in alerts:
            print_alert(alert["message"])
        if not positions:
            console.print("\n[dim]종목 추가: uv run main.py add <종목코드> <매수가> <수량>[/dim]")


def cmd_codex_login(args):
    from src.agent.codex import codex_login
    codex_login()


def cmd_history(args):
    portfolio = load_portfolio()
    if getattr(args, "json", False):
        print(json_dump({"history": portfolio.get("history", [])}))
    else:
        print_header()
        print_phase("거래 내역")
        print_trade_history(portfolio)


def cmd_analyze(args):
    is_json = getattr(args, "json", False)
    quiet = is_json

    if not quiet:
        print_header()

    config = load_config()
    portfolio = load_portfolio()

    # 시장 현황
    if not quiet:
        print_phase("시장 환경")
        print_loading("코스피/코스닥 지수 수집")

    market_data = collect_market_data()

    if not quiet:
        regime = market_data.get("regime", {})
        if regime.get("regime"):
            regime_colors = {"bull": "green", "bear": "red", "sideways": "yellow"}
            rc = regime_colors.get(regime["regime"], "white")
            console.print(f"  [{rc}]📈 시장 레짐: {regime['label']}[/{rc}] — {regime['description']}")
        for idx_name in ("kospi", "kosdaq"):
            idx = market_data.get(idx_name)
            if idx:
                console.print(f"  {idx['name']}: {idx['close']:,.2f} (5일 {idx['change_5d']:+.1f}%, 20일 {idx['change_20d']:+.1f}%)")

    # 분석할 종목
    tickers, _ = collect_tickers(args.tickers, config, portfolio, getattr(args, "screen", False))

    if not tickers:
        if is_json:
            print(json_dump({"status": "error", "message": "분석할 종목이 없습니다"}))
        else:
            print_error("분석할 종목이 없습니다")
        return

    # 기술적 분석
    if not quiet:
        print_phase("기술적 분석", f"{len(tickers)}개 종목 앙상블 보팅")

    signals_data = analyze_tickers(tickers, config)
    if not quiet:
        for item in signals_data:
            print_signal_card(item)

    if not signals_data:
        if is_json:
            print(json_dump({"status": "error", "message": "분석 가능한 종목이 없습니다"}))
        else:
            print_error("분석 가능한 종목이 없습니다")
        return

    # 포트폴리오 업데이트
    positions = portfolio.get("positions", [])
    alerts = []
    if positions:
        if not quiet:
            print_phase("포트폴리오 업데이트")
        current_prices = {item["ticker"]: item["signals"]["current_price"] for item in signals_data}
        alerts = update_positions(portfolio, current_prices, config.get("trailing_stop_pct", 10))
        if not quiet:
            print_portfolio_summary(portfolio)
            for alert in alerts:
                print_alert(alert["message"])

    # LLM 분석
    no_llm = getattr(args, "no_llm", False)
    use_legacy = getattr(args, "legacy", False)
    analysis_text = None
    multi_results = {}

    if not no_llm:
        if use_legacy:
            if not quiet:
                print_phase("투자 오라클 분석", "이광수 철학 기반 종합 전략")
                print_loading("LLM API 호출")
            try:
                from src.agent.oracle import analyze
                analysis_text = analyze(market_data, signals_data, portfolio, config)
                if not quiet:
                    print_analysis(analysis_text)
            except Exception as e:
                if is_json:
                    analysis_text = f"LLM 오류: {e}"
                else:
                    print_error(f"LLM 분석 실패: {e}")
                    console.print("[dim]--no-llm 옵션으로 시그널만 확인할 수 있습니다[/dim]")
        else:
            if not quiet:
                print_phase("다관점 투자 판정", f"{len(signals_data)}개 종목 × 5개 관점 병렬 분석")
            try:
                use_weights = not getattr(args, "no_weights", False)
                multi_results = run_multi_perspective(signals_data, portfolio, market_data, config, use_weights=use_weights)
                if not quiet:
                    for ticker, consensus in multi_results.items():
                        name = next((s["name"] for s in signals_data if s["ticker"] == ticker), ticker)
                        _print_consensus_card(name, ticker, consensus)
            except Exception as e:
                if is_json:
                    analysis_text = f"LLM 오류: {e}"
                else:
                    print_error(f"다관점 분석 실패: {e}")
                    console.print("[dim]--no-llm 또는 --legacy 옵션을 사용할 수 있습니다[/dim]")

    # JSON 출력
    if is_json:
        summary = get_portfolio_summary(portfolio)
        output = {
            "date": market_data["date"],
            "market": market_data,
            "portfolio": {"summary": summary, "positions": portfolio.get("positions", []),
                          "alerts": [a["message"] for a in alerts]},
            "signals": build_signals_json(signals_data),
        }
        if multi_results:
            output["multi_perspective"] = multi_results
        if analysis_text:
            output["analysis"] = analysis_text
        print(json_dump(output))
        return

    if not no_llm and not analysis_text and not multi_results:
        return

    print_success("분석 완료")
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Trading Oracle — 다관점 투자 판정 에이전트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # add
    add_parser = subparsers.add_parser("add", help="매수 기록 추가")
    add_parser.add_argument("ticker", help="종목코드")
    add_parser.add_argument("price", type=float, help="매수가")
    add_parser.add_argument("shares", type=int, help="수량")
    add_parser.add_argument("--reason", "-r", help="매수 이유")
    add_parser.add_argument("--stop-loss", "-s", type=float, help="손절가, 기본 매수가의 90%%")
    add_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # remove
    rm_parser = subparsers.add_parser("remove", help="매도 기록")
    rm_parser.add_argument("ticker", help="종목코드")
    rm_parser.add_argument("--price", "-p", type=float, help="매도가")
    rm_parser.add_argument("--reason", "-r", help="매도 이유")
    rm_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # cash
    cash_parser = subparsers.add_parser("cash", help="보유 현금 설정")
    cash_parser.add_argument("amount", type=float, help="금액")
    cash_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # portfolio
    port_parser = subparsers.add_parser("portfolio", help="포트폴리오 조회")
    port_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # history
    hist_parser = subparsers.add_parser("history", help="거래 내역")
    hist_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # codex-login
    subparsers.add_parser("codex-login", help="OpenAI Codex OAuth 로그인")

    # 기본 분석 옵션
    parser.add_argument("--tickers", "-t", nargs="+", help="추가 분석 종목")
    parser.add_argument("--screen", action="store_true", help="주도주 스크리닝 포함")
    parser.add_argument("--no-llm", action="store_true", help="LLM 분석 생략")
    parser.add_argument("--legacy", action="store_true", help="기존 단일 관점 분석")
    parser.add_argument("--no-weights", action="store_true", help="적응형 가중치 비활성화 (동등 가중치)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()

    cmds = {
        "add": cmd_add, "remove": cmd_remove, "cash": cmd_cash,
        "portfolio": cmd_portfolio, "history": cmd_history, "codex-login": cmd_codex_login,
    }
    handler = cmds.get(args.command)
    if handler:
        handler(args)
    else:
        cmd_analyze(args)


if __name__ == "__main__":
    main()
