#!/usr/bin/env python3
"""다관점 일일 분석 — 5개 관점 + 합의도

사용법:
    uv run scripts/daily.py                          # 포트폴리오 기반 다관점 분석
    uv run scripts/daily.py -t 005930 000660         # 특정 종목 분석
    uv run scripts/daily.py --screen                 # 주도주 스크리닝 포함
    uv run scripts/daily.py --legacy                 # 기존 단일 관점 분석
    uv run scripts/daily.py --no-llm                 # 시그널만
    uv run scripts/daily.py --json                   # JSON 출력
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (scripts/ 에서 실행 시)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import (
    load_config,
    json_dump,
    collect_market_data,
    collect_tickers,
    analyze_tickers,
    run_multi_perspective,
    build_signals_json,
    build_skill_ticker_payloads,
    has_us_tickers,
)
from src.portfolio.tracker import (
    load_portfolio,
    update_positions,
    get_portfolio_summary,
)


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 다관점 일일 분석")
    parser.add_argument("--tickers", "-t", nargs="+", help="분석 종목")
    parser.add_argument("--screen", action="store_true", help="주도주 스크리닝 포함")
    parser.add_argument("--no-llm", action="store_true", help="LLM 분석 생략")
    parser.add_argument(
        "--llm-mode",
        choices=["payload", "prompt-ready"],
        help="스킬 경로용 LLM 위임 모드",
    )
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

    config = load_config()
    if args.no_search:
        config.setdefault("web_search", {})["enabled"] = False
    if args.no_deliberation:
        config.setdefault("deliberation", {})["enabled"] = False
    portfolio = load_portfolio()

    # 분석 종목 수집 (시장 데이터 전에 US 여부 판단)
    tickers, _ = collect_tickers(args.tickers, config, portfolio, args.screen)
    include_us = has_us_tickers(tickers, portfolio)

    # 시장 데이터
    market_data = collect_market_data(include_us=include_us)
    if not tickers:
        if args.json:
            print(json_dump({"status": "error", "message": "분석할 종목이 없습니다"}))
        else:
            print("분석할 종목이 없습니다", file=sys.stderr)
        sys.exit(1)

    # 기술적 분석
    regime = market_data.get("regime", {}).get("regime")
    signals_data = analyze_tickers(tickers, config, regime=regime)
    if not signals_data:
        if args.json:
            print(
                json_dump({"status": "error", "message": "분석 가능한 종목이 없습니다"})
            )
        else:
            print("분석 가능한 종목이 없습니다", file=sys.stderr)
        sys.exit(1)

    # 포트폴리오 업데이트
    positions = portfolio.get("positions", [])
    alerts = []
    if positions:
        current_prices = {
            item["ticker"]: item["signals"]["current_price"] for item in signals_data
        }
        alerts = update_positions(
            portfolio, current_prices, config.get("trailing_stop_pct", 10)
        )

    # LLM 분석
    multi_results = {}
    analysis_text = None
    delta = None

    if args.llm_mode:
        summary = get_portfolio_summary(portfolio)
        output = {
            "schema_version": "v1",
            "llm_mode": args.llm_mode,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "command": "daily",
            "user_intent": "portfolio_daily_analysis",
            "market": market_data,
            "portfolio": {
                "summary": summary,
                "positions": portfolio.get("positions", []),
                "alerts": [a["message"] for a in alerts],
            },
            "signals": build_signals_json(signals_data),
            "analysis": {
                "tickers": build_skill_ticker_payloads(
                    signals_data,
                    portfolio,
                    market_data,
                    config,
                    include_prompts=args.llm_mode == "prompt-ready",
                )
            },
            "render_hints": {
                "primary_order": ["portfolio_alerts", "positions", "watchlist"],
                "max_reasons_per_perspective": 2,
            },
        }
        print(json_dump(output))
        return

    if not args.no_llm:
        if args.legacy:
            from src.agent.oracle import analyze

            analysis_text = analyze(market_data, signals_data, portfolio, config)
        else:
            use_weights = not args.no_weights
            multi_results = run_multi_perspective(
                signals_data, portfolio, market_data, config, use_weights=use_weights
            )

            # 일간 변동 계산
            if multi_results:
                try:
                    from src.performance.tracker import compute_delta

                    delta = compute_delta(multi_results)
                except Exception:
                    pass

    # 출력
    if args.json:
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
        # Phase 17: 환율 레짐
        if market_data.get("fx_regime"):
            output["fx_regime"] = market_data["fx_regime"]
        if market_data.get("fx_regimes"):
            output["fx_regimes"] = market_data["fx_regimes"]
        # Phase 19: 상관 리스크
        if len(positions) >= 2:
            try:
                from src.portfolio.sizer import check_portfolio_health

                regime_str = market_data.get("regime", {}).get("regime", "sideways")
                pf_check = check_portfolio_health(portfolio, regime_str, config)
                output["portfolio"]["correlation_risk"] = pf_check.get(
                    "correlation_risk", {}
                )
                output["portfolio"]["sector_concentration"] = pf_check.get(
                    "sector_concentration", {}
                )
                output["portfolio"]["diversification_score"] = pf_check.get(
                    "diversification_score", 0
                )
            except Exception:
                pass
        print(json_dump(output))
    else:
        # 터미널 Rich 출력
        from src.output.formatter import (
            console,
            print_header,
            print_phase,
            print_loading,
            print_signal_card,
            print_analysis,
            print_portfolio_summary,
            print_alert,
            print_success,
            print_error,
        )

        print_header()

        # 시장 현황
        print_phase("시장 환경", market_data["date"])
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

        # 환율 레짐 (Phase 17)
        fx_regime = market_data.get("fx_regime")
        if fx_regime and fx_regime.get("fx_regime") != "unknown":
            fx_colors = {
                "krw_weak": "red",
                "krw_extreme_weak": "bold red",
                "krw_strong": "green",
                "krw_extreme_strong": "bold green",
                "krw_stable": "yellow",
            }
            fc = fx_colors.get(fx_regime["fx_regime"], "white")
            console.print(
                f"  [{fc}]💱 환율 레짐: {fx_regime['fx_regime_description']}[/{fc}]"
            )
            if fx_regime.get("usd_krw_ma20"):
                console.print(
                    f"     USD/KRW MA20={fx_regime['usd_krw_ma20']:,.0f} / MA60={fx_regime.get('usd_krw_ma60', 0):,.0f}"
                )
            if fx_regime.get("is_extreme"):
                console.print(
                    f"  [bold red]⚠️  환율 극단 변동 — 포지션 사이징 축소 적용[/bold red]"
                )

        # 시그널
        print_phase("기술적 분석", f"{len(signals_data)}개 종목")
        for item in signals_data:
            print_signal_card(item)

        # 포트폴리오
        if positions:
            print_phase("포트폴리오")
            print_portfolio_summary(portfolio)
            for alert in alerts:
                print_alert(alert["message"])

            # 상관 리스크 (Phase 19)
            if len(positions) >= 2:
                try:
                    from src.portfolio.sizer import check_portfolio_health

                    regime_str = market_data.get("regime", {}).get("regime", "sideways")
                    pf_check = check_portfolio_health(portfolio, regime_str, config)

                    corr_risk = pf_check.get("correlation_risk", {})
                    sector_conc = pf_check.get("sector_concentration", {})
                    div_score = pf_check.get("diversification_score", 0)

                    if corr_risk or sector_conc.get("is_concentrated"):
                        console.print(f"\n  [bold]🔗 포트폴리오 리스크[/bold]")
                        if corr_risk.get("high_corr_pairs"):
                            for pair in corr_risk["high_corr_pairs"]:
                                t1, t2, c, n1, n2 = pair
                                console.print(
                                    f"    [yellow]⚠️  {n1} ↔ {n2}: ρ={c:.3f} (고상관)[/yellow]"
                                )
                        if sector_conc.get("is_concentrated"):
                            s = sector_conc["most_concentrated"]
                            p = sector_conc["concentration_pct"]
                            console.print(
                                f"    [yellow]⚠️  {s} 섹터 집중: {p:.0f}%% (분산 필요)[/yellow]"
                            )
                        console.print(f"    분산도: {div_score:.2f}/1.00")
                except Exception:
                    pass

        # 다관점 / 레거시
        if multi_results:
            print_phase("다관점 투자 판정")
            for ticker, consensus in multi_results.items():
                name = next(
                    (s["name"] for s in signals_data if s["ticker"] == ticker), ticker
                )
                _print_consensus_card(name, ticker, consensus)

            # 일간 변동
            if delta and (
                delta["changes"] or delta["new_tickers"] or delta["removed_tickers"]
            ):
                _print_delta(delta)
            elif delta:
                console.print(
                    f"\n  [dim]📋 전일({delta['previous_date']}) 대비 변동 없음[/dim]"
                )
        elif analysis_text:
            print_analysis(analysis_text)

        print_success("분석 완료")


def _print_delta(delta: dict):
    """일간 변동 사항 터미널 출력"""
    from src.output.formatter import console

    verdict_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "DIVIDED": "🔶"}
    console.print(f"\n  [bold]📋 전일({delta['previous_date']}) 대비 변동[/bold]")

    for ch in delta["changes"]:
        prev_e = verdict_emoji.get(ch["previous_verdict"], "⚪")
        curr_e = verdict_emoji.get(ch["current_verdict"], "⚪")
        console.print(
            f"    {prev_e} → {curr_e} [bold]{ch['name']}[/bold]: {ch['previous_verdict']} → {ch['current_verdict']}"
        )
        for pc in ch.get("perspective_changes", []):
            console.print(
                f"      [dim]└ {pc['perspective']}: {pc['previous']} → {pc['current']}[/dim]"
            )

    for nt in delta.get("new_tickers", []):
        console.print(f"    [green]+ {nt['ticker']} — {nt['verdict']}[/green]")

    for rt in delta.get("removed_tickers", []):
        console.print(f"    [red]- {rt['name']} ({rt['ticker']})[/red]")

    console.print()


def _print_consensus_card(name: str, ticker: str, consensus: dict):
    """다관점 합의 결과 터미널 출력"""
    from rich.panel import Panel
    from src.output.formatter import console

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

    # 환율 시그널 (Phase 17)
    fx = consensus.get("fx_signal")
    if not fx:
        # multi_results에 fx_signal이 없을 수 있으므로 perspectives에서 찾기
        pass
    if fx and fx.get("fx_verdict") != "NEUTRAL":
        fx_emoji = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(fx["fx_verdict"], "⚪")
        fx_class_label = {
            "export": "수출주",
            "import": "내수주",
            "neutral": "중립",
        }.get(fx.get("fx_class", ""), "")
        lines.append(
            f"  {fx_emoji} [bold]환율[/bold]: {fx['fx_verdict']} ({fx_class_label}, β={fx.get('fx_beta', 'N/A')})"
        )

    if consensus.get("majority_reasoning"):
        lines.append("")
        for r in consensus["majority_reasoning"][:3]:
            lines.append(f"  [dim]{r}[/dim]")

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


if __name__ == "__main__":
    main()
