"""터미널 출력 포맷터 — Rich 기반 카드형 출력"""

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text


console = Console()


def print_header():
    console.print()
    console.print(Panel(
        Text("🔮 Trading Oracle — 오늘의 투자 조언", justify="center", style="bold white"),
        style="bold blue",
        padding=(1, 2),
    ))
    console.print()


def print_phase(title: str, description: str = ""):
    console.print(f"\n[bold cyan]━━━ {title} ━━━[/bold cyan]")
    if description:
        console.print(f"[dim]{description}[/dim]")


def print_loading(message: str):
    console.print(f"[dim]⏳ {message}...[/dim]")


def print_error(message: str):
    console.print(f"[bold red]❌ {message}[/bold red]")


def print_success(message: str):
    console.print(f"[bold green]✅ {message}[/bold green]")


def print_alert(message: str):
    console.print(Panel(message, style="bold yellow", title="⚠️ 경고"))


def print_signal_card(item: dict):
    sig = item["signals"]
    verdict_color = {"BULLISH": "green", "BEARISH": "red", "NEUTRAL": "yellow"}.get(sig["verdict"], "white")

    lines = []
    lines.append(f"[bold]현재가:[/bold] {sig['current_price']:,.0f}원")
    lines.append(f"[bold]판정:[/bold] [{verdict_color}]{sig['verdict']}[/{verdict_color}] (Bull {sig['bull_votes']}/6, Bear {sig['bear_votes']}/6)")
    lines.append(f"[bold]52주:[/bold] 고가 {sig['high_52w']:,.0f} / 저가 {sig['low_52w']:,.0f}")
    lines.append(f"[bold]수익률:[/bold] 5일 {sig['change_5d']:+.1f}% / 20일 {sig['change_20d']:+.1f}%")
    lines.append(f"[bold]RSI:[/bold] {sig['signals']['rsi']['value']:.1f}")
    lines.append(f"[bold]손절매:[/bold] {sig['trailing_stop_10pct']:,.0f}원 (고점-10%)")

    if "fundamentals" in item:
        f = item["fundamentals"]
        lines.append(f"[bold]PER:[/bold] {f.get('per', 'N/A')} / [bold]PBR:[/bold] {f.get('pbr', 'N/A')}")

    console.print(Panel(
        "\n".join(lines),
        title=f"📊 {item['name']} ({item['ticker']})",
        style="cyan",
    ))


def print_analysis(analysis_text: str):
    console.print()
    console.print(Panel(
        Markdown(analysis_text),
        title="🔮 투자 오라클 분석",
        style="bold blue",
        padding=(1, 2),
    ))


def print_portfolio_summary(portfolio: dict):
    from src.portfolio.tracker import get_portfolio_summary
    summary = get_portfolio_summary(portfolio)
    positions = portfolio.get("positions", [])

    # 총 요약
    pnl_color = "green" if summary["total_pnl"] >= 0 else "red"
    overview = (
        f"[bold]총 자산:[/bold] {summary['total_assets']:,.0f}원\n"
        f"[bold]투자금:[/bold] {summary['total_market_value']:,.0f}원 | "
        f"[bold]현금:[/bold] {summary['cash']:,.0f}원 ({summary['cash_pct']:.0f}%)\n"
        f"[bold]총 손익:[/bold] [{pnl_color}]{summary['total_pnl']:+,.0f}원 ({summary['total_pnl_pct']:+.1f}%)[/{pnl_color}]\n"
        f"[bold]종목 수:[/bold] {summary['num_positions']}개"
    )
    console.print(Panel(overview, title="💼 포트폴리오 요약", style="magenta"))

    if not positions:
        console.print("[dim]  보유 종목 없음[/dim]")
        return

    for pos in positions:
        pnl = pos.get("pnl_pct", 0)
        pnl_color = "green" if pnl >= 0 else "red"
        current = pos.get("current_price", pos["entry_price"])
        market_val = pos.get("market_value", pos["entry_price"] * pos["shares"])
        pnl_amt = pos.get("pnl_amount", 0)
        trailing = pos.get("trailing_stop", pos["stop_loss"])

        # 손절매 상태
        if current <= pos["stop_loss"]:
            stop_status = "[bold red]⛔ 손절가 이탈[/bold red]"
        elif current <= trailing:
            stop_status = "[bold yellow]⚠️ 추적손절 도달[/bold yellow]"
        elif current <= trailing * 1.03:
            stop_status = "[yellow]🔶 추적손절 근접[/yellow]"
        else:
            stop_status = "[green]✅ 정상[/green]"

        lines = [
            f"[bold]매수가:[/bold] {pos['entry_price']:,.0f}원 × {pos['shares']}주",
            f"[bold]현재가:[/bold] {current:,.0f}원 | [bold]평가금:[/bold] {market_val:,.0f}원",
            f"[bold]손익:[/bold] [{pnl_color}]{pnl_amt:+,.0f}원 ({pnl:+.1f}%)[/{pnl_color}]",
            f"[bold]손절가:[/bold] {pos['stop_loss']:,.0f}원 | [bold]추적손절:[/bold] {trailing:,.0f}원",
            f"[bold]상태:[/bold] {stop_status}",
        ]
        if pos.get("reason"):
            lines.append(f"[dim]매수이유: {pos['reason']}[/dim]")

        console.print(Panel(
            "\n".join(lines),
            title=f"📈 {pos['name']} ({pos['ticker']})",
            style="cyan",
        ))


def print_trade_history(portfolio: dict):
    history = portfolio.get("history", [])
    if not history:
        console.print("[dim]  거래 내역 없음[/dim]")
        return

    for trade in history[-10:]:  # 최근 10건
        pnl = trade.get("final_pnl_pct", 0)
        pnl_color = "green" if pnl >= 0 else "red"
        console.print(
            f"  {trade.get('sell_date', '')[:10]} "
            f"{trade['name']}({trade['ticker']}) "
            f"매수 {trade['entry_price']:,.0f} → 매도 {trade.get('sell_price', 0):,.0f} "
            f"[{pnl_color}]{pnl:+.1f}%[/{pnl_color}] "
            f"[dim]{trade.get('sell_reason', '')}[/dim]"
        )
