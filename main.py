"""Trading Oracle — 다관점 투자 판정 에이전트

사용법:
    uv run main.py                                    # 다관점 분석 (5개 관점 + 합의도)
    uv run main.py --tickers 005930 000660             # 추가 종목도 함께 분석
    uv run main.py --screen                            # 주도주 스크리닝 포함
    uv run main.py --no-llm                            # 시그널만 (LLM 없이)
    uv run main.py --legacy                            # 기존 단일 관점 분석
    uv run main.py --json                              # JSON 출력 (shacs-bot 연동용)

    uv run main.py add 005930 55000 10                 # 매수 기록: 종목 매수가 수량
    uv run main.py add 005930 55000 10 --reason "반도체 수출 증가"
    uv run main.py remove 005930                       # 매도 기록
    uv run main.py remove 005930 --price 60000         # 매도가 기록
    uv run main.py cash 5000000                        # 현금 설정
    uv run main.py portfolio                           # 포트폴리오 조회
    uv run main.py portfolio --json                    # 포트폴리오 JSON
    uv run main.py history                             # 거래 내역
"""

import argparse
import json as json_mod
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from src.data.market import (
    fetch_index_ohlcv,
    fetch_market_cap,
    fetch_ohlcv,
    get_ticker_name,
)
from src.data.fundamentals import fetch_naver_fundamentals, fetch_fundamentals_cached
from src.signals.technical import compute_signals
from src.screener.leading import screen_leading_stocks
from src.portfolio.tracker import (
    load_portfolio,
    save_portfolio,
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


class _Encoder(json_mod.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _json_dump(data: dict) -> str:
    return json_mod.dumps(data, ensure_ascii=False, indent=2, cls=_Encoder)


def load_config() -> dict:
    config_path = Path("config.yaml")
    if config_path.exists():
        return yaml.safe_load(config_path.read_text())
    return {}


def get_index_summary(index_code: str, name: str) -> dict:
    df = fetch_index_ohlcv(index_code, days_back=60)
    if df.empty or len(df) < 20:
        return {}
    closes = df["close"].values
    return {
        "name": name,
        "close": float(closes[-1]),
        "change_5d": float((closes[-1] - closes[-5]) / closes[-5] * 100),
        "change_20d": float((closes[-1] - closes[-20]) / closes[-20] * 100),
    }


def analyze_ticker(ticker: str, config: dict, quiet: bool = False) -> dict | None:
    name = get_ticker_name(ticker)
    if not name:
        if not quiet:
            print_error(f"종목 {ticker} 을(를) 찾을 수 없음")
        return None

    ohlcv = fetch_ohlcv(ticker, days_back=120)
    if ohlcv.empty or len(ohlcv) < 60:
        if not quiet:
            print_error(f"{name}({ticker}) 데이터 부족")
        return None

    signals = compute_signals(ohlcv, config)
    if "error" in signals:
        if not quiet:
            print_error(f"{name}({ticker}): {signals['error']}")
        return None

    fund = fetch_naver_fundamentals(ticker)
    cap_data = fetch_market_cap(ticker)
    market_cap = cap_data.get("market_cap", 0)

    return {
        "ticker": ticker,
        "name": name,
        "signals": signals,
        "fundamentals": fund,
        "market_cap": market_cap,
    }


def _print_consensus_card(name: str, ticker: str, consensus: dict):
    """다관점 합의 결과를 터미널에 출력"""
    from rich.panel import Panel

    verdict_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "N/A": "⚪", "DIVIDED": "🔶", "INSUFFICIENT": "⚫"}
    confidence_colors = {"very_high": "bold green", "high": "green", "moderate": "yellow", "low": "red", "insufficient": "dim"}

    lines = []
    votes = consensus["vote_summary"]
    lines.append(f"[bold]합의도:[/bold] [{confidence_colors.get(consensus['confidence'], 'white')}]{consensus['consensus_label']}[/{confidence_colors.get(consensus['confidence'], 'white')}]")
    lines.append(f"[bold]투표:[/bold] 매수 {votes.get('BUY', 0)} / 매도 {votes.get('SELL', 0)} / 관망 {votes.get('HOLD', 0)} / N/A {votes.get('N/A', 0)}")
    lines.append("")

    for p in consensus.get("perspectives", []):
        emoji = verdict_emoji.get(p["verdict"], "⚪")
        lines.append(f"  {emoji} [bold]{p['perspective']}[/bold]: {p['verdict']} — {p.get('reason', '')[:60]}")

    if consensus.get("majority_reasoning"):
        lines.append("")
        for r in consensus["majority_reasoning"][:3]:
            lines.append(f"  [dim]{r[:80]}[/dim]")

    verdict_style = {"BUY": "green", "SELL": "red", "HOLD": "yellow", "DIVIDED": "magenta", "INSUFFICIENT": "dim"}.get(consensus["consensus_verdict"], "white")
    console.print(Panel(
        "\n".join(lines),
        title=f"📊 {name} ({ticker}) — [{verdict_style}]{consensus['consensus_verdict']}[/{verdict_style}]",
        style=verdict_style,
    ))


def run_screening(config: dict, quiet: bool = False) -> list[str]:
    if not quiet:
        print_phase("주도주 스크리닝", "시총 상위 종목에서 모멘텀 + 밸류에이션 필터링")
        print_loading("코스피/코스닥 상위 종목 분석 중")

    candidates = screen_leading_stocks(market="ALL", top_n=30)
    if not candidates:
        if not quiet:
            print_error("스크리닝 결과 없음")
        return []

    max_positions = config.get("max_positions", 3)
    top = candidates[:max_positions * 2]

    if not quiet:
        console.print(f"\n[bold]스크리닝 결과 상위 {len(top)}개:[/bold]")
        for i, c in enumerate(top, 1):
            score_bar = "█" * int(c["score"]) + "░" * (15 - int(c["score"]))
            console.print(
                f"  {i:2d}. {c['name']:12s} ({c['ticker']}) "
                f"점수:{c['score']:5.1f} [{score_bar}] "
                f"PER:{c['per']:6.1f} PBR:{c['pbr']:5.2f} "
                f"5일:{c['ret_5d']:+6.1f}% 20일:{c['ret_20d']:+6.1f}%"
            )

    return [c["ticker"] for c in top[:max_positions * 2]]


# --- Subcommands ---

def cmd_add(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    name = get_ticker_name(ticker)
    if not name:
        print_error(f"종목 {ticker} 을(를) 찾을 수 없음")
        return

    price = args.price
    shares = args.shares
    reason = args.reason or ""
    stop_loss = args.stop_loss or price * 0.9

    add_position(portfolio, ticker, name, price, shares, reason, stop_loss)
    invested = price * shares

    if getattr(args, "json", False):
        print(_json_dump({"status": "ok", "action": "add", "ticker": ticker, "name": name,
                          "price": price, "shares": shares, "invested": invested, "stop_loss": stop_loss}))
    else:
        print_success(
            f"{name}({ticker}) 매수 기록 완료: "
            f"{price:,.0f}원 × {shares}주 = {invested:,.0f}원 "
            f"(손절가: {stop_loss:,.0f}원)"
        )


def cmd_remove(args):
    portfolio = load_portfolio()
    ticker = args.ticker
    pos = next((p for p in portfolio["positions"] if p["ticker"] == ticker), None)
    if not pos:
        if getattr(args, "json", False):
            print(_json_dump({"status": "error", "message": f"{ticker} 은(는) 보유 종목이 아닙니다"}))
        else:
            print_error(f"{ticker} 은(는) 보유 종목이 아닙니다")
        return

    sell_price = args.price
    reason = args.reason or ""

    if not sell_price:
        ohlcv = fetch_ohlcv(ticker, days_back=5)
        if not ohlcv.empty:
            sell_price = float(ohlcv["close"].values[-1])
        else:
            sell_price = pos["entry_price"]

    name = pos["name"]
    pnl_pct = (sell_price - pos["entry_price"]) / pos["entry_price"] * 100
    pnl_amt = (sell_price - pos["entry_price"]) * pos["shares"]

    remove_position(portfolio, ticker, sell_price, reason)

    if getattr(args, "json", False):
        print(_json_dump({"status": "ok", "action": "remove", "ticker": ticker, "name": name,
                          "sell_price": sell_price, "pnl_pct": pnl_pct, "pnl_amount": pnl_amt}))
    else:
        pnl_color = "green" if pnl_pct >= 0 else "red"
        console.print(
            f"[bold]{name}({ticker}) 매도 완료[/bold]: "
            f"{sell_price:,.0f}원 × {pos['shares']}주 "
            f"[{pnl_color}]{pnl_amt:+,.0f}원 ({pnl_pct:+.1f}%)[/{pnl_color}]"
        )


def cmd_cash(args):
    portfolio = load_portfolio()
    set_cash(portfolio, args.amount)
    if getattr(args, "json", False):
        print(_json_dump({"status": "ok", "action": "cash", "amount": args.amount}))
    else:
        print_success(f"보유 현금: {args.amount:,.0f}원으로 설정 완료")


def cmd_portfolio(args):
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

    if getattr(args, "json", False):
        summary = get_portfolio_summary(portfolio)
        print(_json_dump({
            "summary": summary,
            "positions": portfolio.get("positions", []),
            "alerts": [a["message"] for a in alerts],
        }))
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
        print(_json_dump({"history": portfolio.get("history", [])}))
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
    positions = portfolio.get("positions", [])

    # 시장 현황
    if not quiet:
        print_phase("시장 환경", datetime.now().strftime("%Y-%m-%d %H:%M"))
        print_loading("코스피/코스닥 지수 수집")

    market_data = {"date": datetime.now().strftime("%Y-%m-%d")}
    kospi = get_index_summary("KS11", "코스피")
    kosdaq = get_index_summary("KQ11", "코스닥")

    if kospi:
        market_data["kospi"] = kospi
        if not quiet:
            console.print(f"  코스피: {kospi['close']:,.2f} (5일 {kospi['change_5d']:+.1f}%, 20일 {kospi['change_20d']:+.1f}%)")
    if kosdaq:
        market_data["kosdaq"] = kosdaq
        if not quiet:
            console.print(f"  코스닥: {kosdaq['close']:,.2f} (5일 {kosdaq['change_5d']:+.1f}%, 20일 {kosdaq['change_20d']:+.1f}%)")

    # 분석할 종목
    tickers_to_analyze = set()
    for pos in positions:
        tickers_to_analyze.add(pos["ticker"])
    if args.tickers:
        for t in args.tickers:
            tickers_to_analyze.add(t)
    if config.get("watchlist"):
        for t in config["watchlist"]:
            tickers_to_analyze.add(t)

    screened_tickers = []
    if getattr(args, "screen", False):
        screened_tickers = run_screening(config, quiet=quiet)
        for t in screened_tickers:
            tickers_to_analyze.add(t)

    if not tickers_to_analyze:
        if not quiet:
            console.print("\n[dim]보유 종목과 관심 종목이 없어 주도주 스크리닝을 실행합니다[/dim]")
        screened_tickers = run_screening(config, quiet=quiet)
        for t in screened_tickers:
            tickers_to_analyze.add(t)

    if not tickers_to_analyze:
        if is_json:
            print(_json_dump({"status": "error", "message": "분석할 종목이 없습니다"}))
        else:
            print_error("분석할 종목이 없습니다")
        return

    # 종목별 기술적 분석
    if not quiet:
        print_phase("기술적 분석", f"{len(tickers_to_analyze)}개 종목 앙상블 보팅")

    signals_data = []
    for ticker in tickers_to_analyze:
        if not quiet:
            print_loading(f"{ticker} 분석")
        result = analyze_ticker(ticker, config, quiet=quiet)
        if result:
            signals_data.append(result)
            if not quiet:
                print_signal_card(result)

    if not signals_data:
        if is_json:
            print(_json_dump({"status": "error", "message": "분석 가능한 종목이 없습니다"}))
        else:
            print_error("분석 가능한 종목이 없습니다")
        return

    # 포트폴리오 업데이트
    alerts = []
    if positions:
        if not quiet:
            print_phase("포트폴리오 업데이트")
        current_prices = {}
        for item in signals_data:
            current_prices[item["ticker"]] = item["signals"]["current_price"]
        alerts = update_positions(portfolio, current_prices, config.get("trailing_stop_pct", 10))
        if not quiet:
            print_portfolio_summary(portfolio)
            for alert in alerts:
                print_alert(alert["message"])

    # LLM 분석
    no_llm = getattr(args, "no_llm", False)
    use_legacy = getattr(args, "legacy", False)
    analysis_text = None
    multi_results = {}  # ticker → consensus dict

    if not no_llm:
        if use_legacy:
            # 기존 단일 관점 분석
            if not quiet:
                print_phase("투자 오라클 분석", "이광수 철학 기반 포트폴리오 종합 전략")
                print_loading("Claude API 호출")
            try:
                from src.agent.oracle import analyze
                analysis_text = analyze(market_data, signals_data, portfolio, config)
                if not quiet:
                    print_analysis(analysis_text)
            except RuntimeError as e:
                if is_json:
                    analysis_text = f"LLM 오류: {e}"
                else:
                    print_error(str(e))
                    console.print("[dim]--no-llm 옵션으로 시그널만 확인할 수 있습니다[/dim]")
            except Exception as e:
                if is_json:
                    analysis_text = f"LLM 오류: {e}"
                else:
                    print_error(f"LLM 분석 실패: {e}")
        else:
            # 다관점 분석 (기본)
            if not quiet:
                print_phase("다관점 투자 판정", f"{len(signals_data)}개 종목 × 5개 관점 병렬 분석")
            try:
                from src.perspectives.base import PerspectiveInput
                from src.consensus.voter import run_all_perspectives
                from src.consensus.scorer import compute_consensus

                market_context = {}
                if "kospi" in market_data:
                    market_context["kospi"] = market_data["kospi"]
                if "kosdaq" in market_data:
                    market_context["kosdaq"] = market_data["kosdaq"]

                for item in signals_data:
                    ticker = item["ticker"]
                    if not quiet:
                        print_loading(f"{item['name']}({ticker}) 5개 관점 분석")

                    pos = next((p for p in positions if p["ticker"] == ticker), None)
                    fund = fetch_fundamentals_cached(ticker) if not item.get("fundamentals") else item["fundamentals"]

                    pi = PerspectiveInput(
                        ticker=ticker,
                        name=item["name"],
                        ohlcv=fetch_ohlcv(ticker, days_back=120),
                        signals=item["signals"],
                        fundamentals=fund,
                        position=pos,
                        market_context=market_context,
                        config=config,
                    )

                    results = run_all_perspectives(pi)
                    consensus = compute_consensus(results)
                    multi_results[ticker] = consensus

                    if not quiet:
                        _print_consensus_card(item["name"], ticker, consensus)

            except RuntimeError as e:
                if is_json:
                    analysis_text = f"LLM 오류: {e}"
                else:
                    print_error(str(e))
                    console.print("[dim]--no-llm 또는 --legacy 옵션을 사용할 수 있습니다[/dim]")
            except Exception as e:
                if is_json:
                    analysis_text = f"LLM 오류: {e}"
                else:
                    print_error(f"다관점 분석 실패: {e}")

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
            "signals": [
                {
                    "ticker": s["ticker"],
                    "name": s["name"],
                    "price": s["signals"]["current_price"],
                    "verdict": s["signals"]["verdict"],
                    "bull_votes": s["signals"]["bull_votes"],
                    "bear_votes": s["signals"]["bear_votes"],
                    "rsi": s["signals"]["signals"]["rsi"]["value"],
                    "trailing_stop": s["signals"]["trailing_stop_10pct"],
                    "change_5d": s["signals"]["change_5d"],
                    "change_20d": s["signals"]["change_20d"],
                    "per": s.get("fundamentals", {}).get("per"),
                    "pbr": s.get("fundamentals", {}).get("pbr"),
                }
                for s in signals_data
            ],
        }
        if multi_results:
            output["multi_perspective"] = multi_results
        if analysis_text:
            output["analysis"] = analysis_text
        print(_json_dump(output))
        return

    if not no_llm and not analysis_text and not multi_results:
        return

    print_success("분석 완료")
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Trading Oracle — 이광수 투자 철학 기반 일일 투자 조언",
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
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()

    if args.command == "add":
        cmd_add(args)
    elif args.command == "remove":
        cmd_remove(args)
    elif args.command == "cash":
        cmd_cash(args)
    elif args.command == "portfolio":
        cmd_portfolio(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "codex-login":
        cmd_codex_login(args)
    else:
        cmd_analyze(args)


if __name__ == "__main__":
    main()
