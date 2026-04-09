#!/usr/bin/env python3
"""종목 추천 — 스크리닝 → 시그널 필터 → 다관점 분석 → BUY 합의

사용법:
    uv run scripts/recommend.py                    # 한국 주도주 BUY 추천
    uv run scripts/recommend.py --market US        # 미국 시장
    uv run scripts/recommend.py --top 10           # 후보 수 조정
    uv run scripts/recommend.py --no-filter        # 시그널 필터 없이 전체 분석
    uv run scripts/recommend.py --no-llm           # 시그널만 (LLM 없이)
    uv run scripts/recommend.py --json             # JSON 출력
"""

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import load_config, json_dump, run_recommend


def _format_binding_constraints(binding_constraints: list[str]) -> str:
    labels = {
        "risk": "리스크",
        "weight": "종목 비중",
        "cash": "가용 현금",
    }
    if not binding_constraints:
        return "-"
    return ", ".join(labels.get(item, item) for item in binding_constraints)


def _int_from_plan(plan: dict[str, object], key: str) -> int:
    value = plan.get(key, 0)
    return int(value) if isinstance(value, (int, float, str)) else 0


def _describe_buy_plan(plan: dict[str, object]) -> str:
    binding_constraints = plan.get("binding_constraints", [])
    if not isinstance(binding_constraints, list):
        binding_constraints = []

    target_shares = _int_from_plan(plan, "target_shares")
    first_tranche_shares = _int_from_plan(plan, "first_tranche_shares")

    if not binding_constraints:
        return f"목표 수량 {target_shares}주 기준으로 1차 매수 {first_tranche_shares}주를 제안합니다"

    labels = {
        "risk": "손절 기준 리스크",
        "weight": "종목 비중",
        "cash": "가용 현금",
    }
    constraints_text = ", ".join(
        labels.get(str(item), str(item)) for item in binding_constraints
    )
    return (
        f"{constraints_text} 제약 때문에 목표 수량이 {target_shares}주로 제한됐고, "
        f"1차 매수는 {first_tranche_shares}주만 제안됩니다"
    )


def _describe_buy_block(plan: dict[str, object]) -> str:
    reason = str(plan.get("reason", ""))

    if "가용 현금" in reason:
        return "종목 자체는 통과했지만, 현재 포트폴리오 현금 여력으로는 1주도 신규 진입할 수 없습니다"
    if "기존 보유 비중" in reason:
        return "기존 보유 비중이 이미 높아, 추가 매수보다 분산 유지가 우선인 상태입니다"
    if "손절 기준 대비 허용 리스크" in reason:
        return "손절폭 대비 허용 리스크가 작아 전략상 의미 있는 신규 진입 수량이 나오지 않습니다"
    if "손절가가 현재가 이상" in reason:
        return "손절가와 현재가 간격이 없어 현재 전략 기준으로는 진입 자체가 성립하지 않습니다"
    return "현재 포트폴리오 제약 또는 진입 조건 때문에 신규 매수가 차단됐습니다"


def main():
    config = load_config()
    default_market = config.get("recommend", {}).get("default_market", "KR")

    parser = argparse.ArgumentParser(description="Trading Oracle — 종목 추천")
    parser.add_argument(
        "--market",
        default=default_market,
        help="시장 (기본: KR, KR=KOSPI+KOSDAQ, US=NASDAQ+NYSE, ALL=KR+US)",
    )
    parser.add_argument(
        "--top", type=int, default=6, help="최종 분석 대상 수 (기본: 6)"
    )
    parser.add_argument(
        "--no-filter", action="store_true", help="시그널 필터 없이 전체 분석"
    )
    parser.add_argument("--no-llm", action="store_true", help="시그널만 (LLM 없이)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    result = run_recommend(
        config,
        market=args.market,
        top_n=args.top,
        signal_filter=not args.no_filter,
        use_llm=not args.no_llm,
    )

    if args.json:
        print(json_dump(result))
        return

    # 터미널 Rich 출력
    from src.output.formatter import console
    from rich.panel import Panel

    regime = result.get("regime", {})
    regime_label = regime.get("label", "")
    console.print(
        f"\n[bold]🎯 종목 추천[/bold] ({result['market']}, {result['date']}, {regime_label})"
    )

    universe_breakdown = result.get("universe_breakdown", {})
    universe_parts = [
        f"{market} {count}" for market, count in universe_breakdown.items() if count
    ]
    if universe_parts:
        console.print(
            f"  universe: {' + '.join(universe_parts)} = {result.get('universe_size', 0)}"
        )

    constraints = result.get("selection_constraints", {})
    if constraints:
        selection_bits = ["score 우선"]
        sector_cap = constraints.get("sector_cap")
        if sector_cap is not None:
            selection_bits.append(f"섹터 cap {sector_cap}")
        if constraints.get("prefer_market_balance"):
            selection_bits.append("시장 균형 선호")
        if constraints.get("relaxed"):
            selection_bits.append("부족 시 완화 적용")
        console.print(f"  선택 기준: {' + '.join(selection_bits)}")

    console.print(
        f"  스크리닝: {result['screened']}개 후보 → 시그널 필터: {result['signal_filtered']}개 통과 → 분석: {result['analyzed']}개"
    )
    portfolio_sizing = result.get("portfolio_sizing", {})
    if portfolio_sizing:
        cash_display = portfolio_sizing.get(
            "cash_display", f"{portfolio_sizing.get('cash', 0):,.0f}원"
        )
        console.print(
            f"  포트폴리오: 총자산 {portfolio_sizing.get('total_assets', 0):,.0f}원 / "
            f"현재 현금 {cash_display} / "
            f"현금 비중 {portfolio_sizing.get('cash_ratio', 0):.1f}%"
        )
        console.print(
            f"  매수 가능 현금: {portfolio_sizing.get('available_cash', 0):,.0f}원 "
            f"(현금 하한 {portfolio_sizing.get('cash_floor', 0)}% = "
            f"{portfolio_sizing.get('cash_floor_amount', 0):,.0f}원 보호)"
        )
        if not portfolio_sizing.get("can_buy", True) and portfolio_sizing.get(
            "buy_block_reason"
        ):
            console.print(
                f"  [yellow]⚠️ 포트폴리오 제약: {portfolio_sizing['buy_block_reason']}[/yellow]"
            )
    console.print()

    recs = result["recommendations"]
    if not recs:
        reason = result.get("no_recommendation_reason", "추천 종목 없음")
        console.print(f"  [yellow]⚠️  {reason}[/yellow]")
        if regime.get("regime") == "bear":
            console.print(
                "  [dim]시장 레짐이 하락 추세입니다. 현금 비중 유지를 권장합니다.[/dim]"
            )
        console.print()
        return

    verdict_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "N/A": "⚪"}

    for rec in recs:
        consensus = rec.get("consensus")
        sig = rec["signals"]
        plan = rec.get("action_plan")
        price_display = rec.get("price_display") or f"{rec['price']:,.0f}원"
        is_buyable = bool(plan and plan.get("type") == "buy")
        badge = (
            "[bold black on green] 매수 가능 [/bold black on green]"
            if is_buyable
            else "[bold white on red] 매수 불가 [/bold white on red]"
        )
        panel_style = "green"

        lines = []
        lines.append(badge)
        lines.append(f"[bold]현재가:[/bold] {price_display}")
        lines.append(
            f"[bold]시장/섹터:[/bold] {rec.get('market', '-')} / {rec.get('sector', '기타')}"
        )
        if rec.get("selected_by"):
            lines.append(f"[bold]선정 이유:[/bold] {', '.join(rec['selected_by'])}")
        lines.append(
            f"[bold]시그널:[/bold] {sig['verdict']} (Bull {sig['bull_votes']}/6)"
        )

        if consensus:
            lines.append(
                f"[bold]합의도:[/bold] {consensus['consensus_label']} ({consensus['consensus_verdict']})"
            )
            lines.append("")
            for p in consensus.get("perspectives", []):
                emoji = verdict_emoji.get(p["verdict"], "⚪")
                lines.append(
                    f"  {emoji} [bold]{p['perspective']}[/bold]: {p['verdict']} — {p.get('reason', '')}"
                )

        # 매수 전략
        if plan and plan.get("type") == "buy":
            lines.append("")
            lines.append(
                f"  [bold green]💰 매수 전략 (분할 매수 1차 / {plan['first_tranche_pct']}%%)[/bold green]"
            )
            lines.append(
                f"    1차 수량: {plan['first_tranche_shares']}주 (목표 {plan['target_shares']}주)"
            )
            lines.append(f"    투자금: {plan['investment']:,.0f}원")
            lines.append(f"    손절가: {plan['stop_loss']:,.0f}원")
            lines.append(
                f"    최대 손실: {plan['risk_amount']:,.0f}원 (자산의 {plan['risk_pct']}%%)"
            )
            share_limits = plan.get("share_limits") or {}
            if share_limits:
                lines.append(
                    f"    제약 기준: 리스크 {share_limits.get('risk', 0)}주 / "
                    f"비중 {share_limits.get('weight', 0)}주 / "
                    f"현금 {share_limits.get('cash', 0)}주"
                )
                lines.append(
                    f"    최종 제한: {_format_binding_constraints(plan.get('binding_constraints', []))}"
                )
            lines.append(f"    해석: {_describe_buy_plan(plan)}")
            lines.append(
                f"    가용 현금: {plan.get('available_cash', 0):,.0f}원 "
                f"(현금 하한 보호분 {plan.get('cash_floor_amount', 0):,.0f}원)"
            )
            lines.append(
                f"    매수 후 현금: {plan['portfolio_cash_after']:,.0f}원 ({plan['portfolio_cash_ratio_after']}%%)"
            )
            if plan.get("note"):
                lines.append(f"    [dim]ℹ️  {plan['note']}[/dim]")
        elif plan and plan.get("type") == "buy_blocked":
            lines.append("")
            lines.append(f"  [bold yellow]🛑 매수 차단:[/bold yellow] {plan['reason']}")
            lines.append(f"  [dim]해석: {_describe_buy_block(plan)}[/dim]")

        console.print(
            Panel(
                "\n".join(lines),
                title=f"🟢 {rec['name']} ({rec['ticker']}) {badge}",
                style=panel_style,
            )
        )

    console.print()


if __name__ == "__main__":
    main()
