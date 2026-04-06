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
    uv run main.py remove 005930                       # 전량 매도 기록
    uv run main.py remove 005930 --price 60000         # 매도가 지정
    uv run main.py remove 005930 --price 60000 -n 5    # 5주만 분할 매도
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
    has_us_tickers,
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
    from src.data.market import is_us_ticker

    is_us = is_us_ticker(ticker)
    c = "$" if is_us else ""
    u = "" if is_us else "원"
    fmt = ",.2f" if is_us else ",.0f"

    verdict_emoji = {
        "BUY": "🟢",
        "SELL": "🔴",
        "HOLD": "🟡",
        "N/A": "⚪",
        "DIVIDED": "🔶",
        "INSUFFICIENT": "⚫",
    }
    confidence_colors = {
        "very_high": "bold green",
        "high": "green",
        "moderate": "yellow",
        "low": "red",
        "insufficient": "dim",
    }

    lines = []
    votes = consensus["vote_summary"]
    cc = confidence_colors.get(consensus["confidence"], "white")
    weighted_tag = " [dim](가중)[/dim]" if consensus.get("weighted") else ""
    lines.append(
        f"[bold]합의도:[/bold] [{cc}]{consensus['consensus_label']}[/{cc}]{weighted_tag}"
    )
    lines.append(
        f"[bold]투표:[/bold] 매수 {votes.get('BUY', 0)} / 매도 {votes.get('SELL', 0)} / 관망 {votes.get('HOLD', 0)} / N/A {votes.get('N/A', 0)}"
    )
    lines.append("")

    for p in consensus.get("perspectives", []):
        emoji = verdict_emoji.get(p["verdict"], "⚪")
        lines.append(
            f"  {emoji} [bold]{p['perspective']}[/bold]: {p['verdict']} — {p.get('reason', '')}"
        )

    if consensus.get("majority_reasoning"):
        lines.append("")
        for r in consensus["majority_reasoning"][:3]:
            lines.append(f"  [dim]{r}[/dim]")

    # 매매 전략 (action_plan)
    plan = consensus.get("action_plan")
    if plan:
        lines.append("")
        if plan["type"] == "buy":
            tranche_label = f"분할 매수 1차 / {plan['first_tranche_pct']}%"
            lines.append(f"  [bold green]💰 매수 전략 ({tranche_label})[/bold green]")
            lines.append(f"    매수가: {c}{plan['entry_price']:{fmt}}{u}")
            lines.append(
                f"    1차 수량: {plan['first_tranche_shares']}주 (목표 {plan['target_shares']}주)"
            )
            lines.append(f"    투자금: {c}{plan['investment']:{fmt}}{u}")
            lines.append(f"    손절가: {c}{plan['stop_loss']:{fmt}}{u}")
            lines.append(
                f"    최대 손실: {c}{plan['risk_amount']:{fmt}}{u} (자산의 {plan['risk_pct']}%%)"
            )
            lines.append(
                f"    매수 후 현금: {c}{plan['portfolio_cash_after']:{fmt}}{u} ({plan['portfolio_cash_ratio_after']}%%)"
            )
            if plan.get("note"):
                lines.append(f"    [dim]ℹ️  {plan['note']}[/dim]")
        elif plan["type"] == "sell":
            ratio_label = (
                f"{plan['sell_ratio']}%% 매도"
                if plan["sell_ratio"] < 100
                else "전량 매도"
            )
            lines.append(f"  [bold red]🔴 매도 전략 ({ratio_label})[/bold red]")
            lines.append(f"    매도가: {c}{plan['sell_price']:{fmt}}{u} (현재가)")
            lines.append(
                f"    매도 수량: {plan['sell_shares']}주 (보유 {plan['total_shares']}주)"
            )
            pnl_color = "green" if plan["expected_pnl"] >= 0 else "red"
            lines.append(
                f"    예상 손익: [{pnl_color}]{c}{plan['expected_pnl']:+{fmt}}{u} ({plan['expected_pnl_pct']:+.1f}%%)[/{pnl_color}]"
            )
            if plan["remaining_shares"] > 0:
                lines.append(f"    매도 후 잔여: {plan['remaining_shares']}주")
            lines.append(
                f"    매도 후 현금: {c}{plan['portfolio_cash_after']:{fmt}}{u} ({plan['portfolio_cash_ratio_after']}%%)"
            )
            lines.append(f"    [dim]{plan['sell_reason']}[/dim]")
            if plan["urgency"] == "immediate":
                lines.append(f"    [bold red]⚡ 즉시 실행 권고[/bold red]")
        elif plan["type"] == "buy_blocked":
            lines.append(f"  [dim]💤 매수 차단: {plan['reason']}[/dim]")
        elif plan["type"] == "sell_blocked":
            lines.append(f"  [dim]💤 {plan['reason']}[/dim]")

    vs = {
        "BUY": "green",
        "SELL": "red",
        "HOLD": "yellow",
        "DIVIDED": "magenta",
        "INSUFFICIENT": "dim",
    }.get(consensus["consensus_verdict"], "white")
    console.print(
        Panel(
            "\n".join(lines),
            title=f"📊 {name} ({ticker}) — [{vs}]{consensus['consensus_verdict']}[/{vs}]",
            style=vs,
        )
    )


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
    invested = price * shares

    # 현금 차감
    cash_before = portfolio.get("cash", 0)
    portfolio["cash"] = cash_before - invested
    if portfolio["cash"] < 0:
        console.print(
            f"[yellow]⚠️ 현금 부족: {cash_before:,.0f}원 → {portfolio['cash']:,.0f}원 (매수 대금 {invested:,.0f}원)[/yellow]"
        )

    add_position(portfolio, ticker, name, price, shares, reason, stop_loss)

    if getattr(args, "json", False):
        print(
            json_dump(
                {
                    "status": "ok",
                    "action": "add",
                    "ticker": ticker,
                    "name": name,
                    "price": price,
                    "shares": shares,
                    "invested": invested,
                    "stop_loss": stop_loss,
                    "cash": portfolio["cash"],
                }
            )
        )
    else:
        print_success(
            f"{name}({ticker}) 매수 기록 완료: {price:,.0f}원 × {shares}주 = {invested:,.0f}원 (손절가: {stop_loss:,.0f}원)"
        )
        console.print(f"  [dim]보유 현금: {portfolio['cash']:,.0f}원[/dim]")


def cmd_remove(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    pos = next((p for p in portfolio["positions"] if p["ticker"] == ticker), None)
    if not pos:
        if getattr(args, "json", False):
            print(
                json_dump(
                    {
                        "status": "error",
                        "message": f"{ticker} 은(는) 보유 종목이 아닙니다",
                    }
                )
            )
        else:
            print_error(f"{ticker} 은(는) 보유 종목이 아닙니다")
        return

    sell_price = args.price
    reason = args.reason or ""
    sell_shares = args.shares  # None이면 전량
    if not sell_price:
        ohlcv = fetch_ohlcv(ticker, days_back=5)
        sell_price = (
            float(ohlcv["close"].values[-1]) if not ohlcv.empty else pos["entry_price"]
        )

    actual_sell_shares = sell_shares if sell_shares is not None else pos["shares"]

    # 수량 검증
    if actual_sell_shares > pos["shares"]:
        msg = (
            f"매도 수량({actual_sell_shares})이 보유 수량({pos['shares']})을 초과합니다"
        )
        if getattr(args, "json", False):
            print(json_dump({"status": "error", "message": msg}))
        else:
            print_error(msg)
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
        if getattr(args, "json", False):
            print(json_dump({"status": "error", "message": str(e)}))
        else:
            print_error(str(e))
        return

    leftover = pos["shares"] - actual_sell_shares
    sell_label = (
        f"{actual_sell_shares}주"
        if sell_shares is not None
        else f"전량 {actual_sell_shares}주"
    )

    if getattr(args, "json", False):
        print(
            json_dump(
                {
                    "status": "ok",
                    "action": "remove",
                    "ticker": ticker,
                    "name": name,
                    "sell_price": sell_price,
                    "sell_shares": actual_sell_shares,
                    "remaining_shares": leftover,
                    "pnl_pct": pnl_pct,
                    "pnl_amount": pnl_amt,
                    "proceeds": proceeds,
                    "cash": portfolio["cash"],
                }
            )
        )
    else:
        pnl_color = "green" if pnl_pct >= 0 else "red"
        console.print(
            f"[bold]{name}({ticker}) 매도 완료[/bold]: {sell_price:,.0f}원 × {sell_label} [{pnl_color}]{pnl_amt:+,.0f}원 ({pnl_pct:+.1f}%)[/{pnl_color}]"
        )
        if leftover > 0:
            console.print(
                f"  [dim]잔여 보유: {leftover}주 (평단가 {pos['entry_price']:,.0f}원)[/dim]"
            )
        console.print(
            f"  [dim]보유 현금: {portfolio['cash']:,.0f}원 (+{proceeds:,.0f}원)[/dim]"
        )


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
        alerts = update_positions(
            portfolio, current_prices, config.get("trailing_stop_pct", 10)
        )

    if getattr(args, "json", False):
        summary = get_portfolio_summary(portfolio)
        print(
            json_dump(
                {
                    "summary": summary,
                    "positions": portfolio.get("positions", []),
                    "alerts": [a["message"] for a in alerts],
                }
            )
        )
    else:
        print_header()
        print_portfolio_summary(portfolio)
        for alert in alerts:
            print_alert(alert["message"])
        if not positions:
            console.print(
                "\n[dim]종목 추가: uv run main.py add <종목코드> <매수가> <수량>[/dim]"
            )


def cmd_codex_login(args):
    from src.agent.codex import codex_login

    codex_login()


def cmd_reset(args):
    """데이터 초기화"""
    import shutil
    from pathlib import Path

    targets = []
    if args.snapshots or args.all:
        targets.append(("스냅샷", "data/snapshots"))
    if args.causal or args.all:
        targets.append(("인과 그래프", "data/causal_graph.json"))
        targets.append(("인과 체크포인트", "data/causal_checkpoint.json"))
    if args.cache or args.all:
        targets.append(("펀더멘털 캐시", "data/fundamentals_cache.json"))
    if args.portfolio:
        targets.append(("포트폴리오", "data/portfolio.json"))

    if not targets:
        if getattr(args, "json", False):
            print(
                json_dump(
                    {
                        "status": "error",
                        "message": "초기화 대상을 지정하세요 (--snapshots, --causal, --cache, --all, --portfolio)",
                    }
                )
            )
        else:
            print_error(
                "초기화 대상을 지정하세요: --snapshots, --causal, --cache, --all, --portfolio"
            )
        return

    deleted = []
    for name, path_str in targets:
        p = Path(path_str)
        if p.is_dir():
            count = len(list(p.glob("*.json")))
            if count > 0:
                shutil.rmtree(p)
                p.mkdir(parents=True, exist_ok=True)
                deleted.append(f"{name} ({count}개 파일)")
        elif p.is_file():
            p.unlink()
            deleted.append(name)

    if getattr(args, "json", False):
        print(json_dump({"status": "ok", "deleted": deleted}))
    else:
        if deleted:
            for d in deleted:
                print_success(f"초기화 완료: {d}")
        else:
            console.print("[dim]삭제할 데이터가 없습니다.[/dim]")


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
    if getattr(args, "no_search", False):
        config.setdefault("web_search", {})["enabled"] = False
    if getattr(args, "no_deliberation", False):
        config.setdefault("deliberation", {})["enabled"] = False
    portfolio = load_portfolio()

    # 분석할 종목 (시장 데이터 수집 전에 먼저 수집하여 US 여부 판단)
    tickers, _ = collect_tickers(
        args.tickers, config, portfolio, getattr(args, "screen", False)
    )
    include_us = has_us_tickers(tickers, portfolio)

    # 시장 현황
    if not quiet:
        print_phase("시장 환경")
        print_loading("코스피/코스닥 + 나스닥/S&P500 지수 수집")

    market_data = collect_market_data(include_us=include_us)

    if not quiet:
        regime = market_data.get("regime", {})
        if regime.get("regime"):
            regime_colors = {"bull": "green", "bear": "red", "sideways": "yellow"}
            rc = regime_colors.get(regime["regime"], "white")
            console.print(
                f"  [{rc}]📈 시장 레짐: {regime['label']}[/{rc}] — {regime['description']}"
            )
        for idx_name in ("kospi", "kosdaq", "nasdaq", "sp500"):
            idx = market_data.get(idx_name)
            if idx:
                console.print(
                    f"  {idx['name']}: {idx['close']:,.2f} (5일 {idx['change_5d']:+.1f}%, 20일 {idx['change_20d']:+.1f}%)"
                )
        if market_data.get("causal_warning"):
            console.print(
                f"  [bold yellow]⚠️  {market_data['causal_warning']}[/bold yellow]"
            )

    if not tickers:
        if is_json:
            print(json_dump({"status": "error", "message": "분석할 종목이 없습니다"}))
        else:
            print_error("분석할 종목이 없습니다")
        return

    # 기술적 분석
    if not quiet:
        print_phase("기술적 분석", f"{len(tickers)}개 종목 앙상블 보팅")

    regime = market_data.get("regime", {}).get("regime")
    signals_data = analyze_tickers(tickers, config, regime=regime)
    if not quiet:
        for item in signals_data:
            print_signal_card(item)

    if not signals_data:
        if is_json:
            print(
                json_dump({"status": "error", "message": "분석 가능한 종목이 없습니다"})
            )
        else:
            print_error("분석 가능한 종목이 없습니다")
        return

    # 포트폴리오 업데이트
    positions = portfolio.get("positions", [])
    alerts = []
    if positions:
        if not quiet:
            print_phase("포트폴리오 업데이트")
        current_prices = {
            item["ticker"]: item["signals"]["current_price"] for item in signals_data
        }
        alerts = update_positions(
            portfolio, current_prices, config.get("trailing_stop_pct", 10)
        )
        if not quiet:
            print_portfolio_summary(portfolio)
            for alert in alerts:
                print_alert(alert["message"])

    # LLM 분석
    no_llm = getattr(args, "no_llm", False)
    use_legacy = getattr(args, "legacy", False)
    analysis_text = None
    multi_results = {}
    delta = None

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
                    console.print(
                        "[dim]--no-llm 옵션으로 시그널만 확인할 수 있습니다[/dim]"
                    )
        else:
            if not quiet:
                print_phase(
                    "다관점 투자 판정",
                    f"{len(signals_data)}개 종목 × 5개 관점 병렬 분석",
                )
            try:
                use_weights = not getattr(args, "no_weights", False)
                multi_results = run_multi_perspective(
                    signals_data,
                    portfolio,
                    market_data,
                    config,
                    use_weights=use_weights,
                )
                if multi_results:
                    try:
                        from src.performance.tracker import compute_delta

                        delta = compute_delta(multi_results)
                    except Exception:
                        pass

                    # 포지션 사이징: action_plan 부착
                    from src.portfolio.sizer import (
                        check_portfolio_health,
                        compute_action_plan,
                    )

                    regime_str = market_data.get("regime", {}).get("regime", "sideways")
                    pf_check = check_portfolio_health(portfolio, regime_str, config)

                    if not quiet and pf_check["portfolio_health"] == "danger":
                        for fs in pf_check.get("forced_sell_tickers", []):
                            print_alert(
                                f"포트폴리오 손실 {pf_check['total_pnl_pct']:.1f}%% — {fs['name']}({fs['ticker']}) 감축 권고 (손익 {fs['pnl_pct']:+.1f}%%)"
                            )
                    if (
                        not quiet
                        and not pf_check["can_buy"]
                        and pf_check["buy_block_reason"]
                    ):
                        if pf_check["portfolio_health"] != "danger":
                            console.print(
                                f"  [yellow]⚠️  매수 제한: {pf_check['buy_block_reason']}[/yellow]"
                            )

                    for ticker, consensus in multi_results.items():
                        sig_item = next(
                            (s for s in signals_data if s["ticker"] == ticker), None
                        )
                        if sig_item:
                            stop_price = sig_item["signals"]["trailing_stop_10pct"]
                            current_price = sig_item["signals"]["current_price"]
                            plan = compute_action_plan(
                                ticker,
                                current_price,
                                stop_price,
                                consensus["consensus_verdict"],
                                consensus["confidence"],
                                portfolio,
                                pf_check,
                                config,
                            )
                            if plan:
                                consensus["action_plan"] = plan
                            consensus["portfolio_check"] = pf_check

                if not quiet:
                    for ticker, consensus in multi_results.items():
                        name = next(
                            (s["name"] for s in signals_data if s["ticker"] == ticker),
                            ticker,
                        )
                        _print_consensus_card(name, ticker, consensus)
            except Exception as e:
                if is_json:
                    analysis_text = f"LLM 오류: {e}"
                else:
                    print_error(f"다관점 분석 실패: {e}")
                    console.print(
                        "[dim]--no-llm 또는 --legacy 옵션을 사용할 수 있습니다[/dim]"
                    )

    # JSON 출력
    if is_json:
        summary = get_portfolio_summary(portfolio)
        output = {
            "date": market_data["date"],
            "market": market_data,
            "portfolio": {
                "summary": summary,
                "positions": portfolio.get("positions", []),
                "alerts": [a["message"] for a in alerts],
            },
            "signals": build_signals_json(signals_data),
        }
        if multi_results:
            output["multi_perspective"] = multi_results
        if delta:
            output["delta"] = delta
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
    add_parser.add_argument(
        "--stop-loss", "-s", type=float, help="손절가, 기본 매수가의 90%%"
    )
    add_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # remove
    rm_parser = subparsers.add_parser("remove", help="매도 기록")
    rm_parser.add_argument("ticker", help="종목코드")
    rm_parser.add_argument("--price", "-p", type=float, help="매도가")
    rm_parser.add_argument(
        "--shares", "-n", type=int, help="매도 수량 (미지정 시 전량)"
    )
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

    # reset
    reset_parser = subparsers.add_parser("reset", help="데이터 초기화")
    reset_parser.add_argument(
        "--snapshots", action="store_true", help="추천 스냅샷 초기화"
    )
    reset_parser.add_argument(
        "--causal", action="store_true", help="인과 그래프 초기화"
    )
    reset_parser.add_argument(
        "--cache", action="store_true", help="펀더멘털 캐시 초기화"
    )
    reset_parser.add_argument(
        "--portfolio",
        action="store_true",
        help="포트폴리오 초기화 (주의: 실제 투자 기록 삭제)",
    )
    reset_parser.add_argument(
        "--all", action="store_true", help="전체 초기화 (포트폴리오 제외)"
    )
    reset_parser.add_argument("--json", action="store_true", help="JSON 출력")

    # codex-login
    subparsers.add_parser("codex-login", help="OpenAI Codex OAuth 로그인")

    # help (전체 명령 가이드)
    subparsers.add_parser("guide", help="전체 명령 가이드")

    # 기본 분석 옵션
    parser.add_argument("--tickers", "-t", nargs="+", help="추가 분석 종목")
    parser.add_argument("--screen", action="store_true", help="주도주 스크리닝 포함")
    parser.add_argument("--no-llm", action="store_true", help="LLM 분석 생략")
    parser.add_argument("--legacy", action="store_true", help="기존 단일 관점 분석")
    parser.add_argument(
        "--no-weights", action="store_true", help="적응형 가중치 비활성화 (동등 가중치)"
    )
    parser.add_argument("--no-search", action="store_true", help="웹 검색 비활성화")
    parser.add_argument(
        "--no-deliberation", action="store_true", help="숙의 합의 비활성화"
    )
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()

    def cmd_guide(_args):
        guide = """\
🔮 Trading Oracle — 전체 명령 가이드

━━━ 분석 ━━━
  uv run main.py                              다관점 분석 (포트폴리오 종목)
  uv run main.py -t 005930 AAPL               특정 종목 분석
  uv run main.py --screen                     주도주 스크리닝 포함
  uv run main.py --no-llm                     시그널만 (LLM 없이)
  uv run main.py --no-search                  웹 검색 비활성화
  uv run main.py --legacy                     기존 단일 관점 분석

━━━ 종목 추천 ━━━
  uv run scripts/recommend.py                 BUY 합의 종목 추천
  uv run scripts/recommend.py --market US     미국 시장 추천
  uv run scripts/recommend.py --no-llm        시그널만 (빠른 스캔)

━━━ 포트폴리오 ━━━
  uv run main.py add 005930 55000 10          매수 기록
  uv run main.py remove 005930                전량 매도
  uv run main.py remove 005930 -n 5           5주 분할 매도
  uv run main.py cash 10000000                현금 설정
  uv run main.py portfolio                    포트폴리오 조회
  uv run main.py history                      거래 내역

━━━ 스크리닝 ━━━
  uv run scripts/screen.py                    주도주 스크리닝
  uv run scripts/screen.py --top 10           상위 10개

━━━ 단일 관점 ━━━
  uv run scripts/perspective.py --kwangsoo -t 005930
  uv run scripts/perspective.py --quant -t AAPL
  (사용 가능: --kwangsoo, --ouroboros, --quant, --macro, --value)

━━━ 성과 추적 ━━━
  uv run scripts/performance.py report        성과 리포트
  uv run scripts/performance.py list          스냅샷 목록
  uv run scripts/performance.py detail 2026-03-28

━━━ 백테스트 ━━━
  uv run scripts/backtest.py 005930 AAPL      시그널 백테스트
  uv run scripts/backtest.py --days 450       기간 지정

━━━ 인과 그래프 ━━━
  uv run scripts/build_causal.py build        전체 구축 (~$10, 한국+글로벌)
  uv run scripts/build_causal.py update 2차전지 AI
  uv run scripts/build_causal.py info         현재 그래프 정보
  uv run scripts/verify_causal.py             Granger 인과 검증
  uv run scripts/verify_causal.py --detail    검증된 트리플 상세

━━━ 자가 학습 (v3) ━━━
  uv run scripts/performance.py patterns      적중 패턴 분석 (레짐별 성적표)

━━━ 관리 ━━━
  uv run main.py reset --all                  전체 초기화 (포트폴리오 제외)
  uv run main.py reset --snapshots            스냅샷만 초기화
  uv run main.py reset --causal               인과 그래프 초기화
  uv run main.py codex-login                  Codex OAuth 로그인

━━━ 공통 옵션 ━━━
  --json          JSON 출력 (shacs-bot 연동)
  --no-weights    적응형 가중치 비활성화
  --no-search     웹 검색 비활성화
  --no-deliberation  숙의 합의 비활성화
"""
        print(guide)

    cmds = {
        "add": cmd_add,
        "remove": cmd_remove,
        "cash": cmd_cash,
        "portfolio": cmd_portfolio,
        "history": cmd_history,
        "reset": cmd_reset,
        "codex-login": cmd_codex_login,
        "guide": cmd_guide,
    }
    handler = cmds.get(args.command)
    if handler:
        handler(args)
    else:
        cmd_analyze(args)


if __name__ == "__main__":
    main()
