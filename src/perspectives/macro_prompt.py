from __future__ import annotations

from src.causal.prompt_injection_runtime import load_verified_prompt_records
from src.data.market import is_us_ticker

from .macro_context import causal_context, verified_keywords
from .macro_prompt_models import (
    MacroPromptBuild,
    MacroPromptRuntime,
    MacroPromptSource,
    NewsItem,
)


def _quantitative_context() -> str:
    try:
        from src.data.macro import format_macro_for_prompt, get_macro_snapshot

        return format_macro_for_prompt(get_macro_snapshot())
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
        return ""


def _web_context_lines(source: MacroPromptSource) -> list[str]:
    lines: list[str] = []
    if source.web_context.news:
        searched_at = source.web_context.searched_at[:10]
        lines.append(f"### 최근 뉴스 (웹 검색 {searched_at})")
        for news in source.web_context.news[:5]:
            lines.append(f"- [{news.date[:10]}] {news.title}")
        lines.append("")
    sectors: tuple[NewsItem, ...] = (
        *source.web_context.sector_0,
        *source.web_context.sector_1,
    )
    if sectors:
        lines.append("### 섹터 동향 (웹 검색)")
        lines.extend(f"- {item.title[:80]}" for item in sectors[:6])
        lines.append("")
    return lines


def _fx_lines(source: MacroPromptSource) -> list[str]:
    fx = source.fx_signal
    if fx is None:
        return []
    labels = {"export": "수출주", "import": "내수/수입주", "neutral": "중립"}
    lines = [
        "### 환율 팩터",
        f"- 종목 환율 민감도: {labels.get(fx.fx_class, '중립')} (β={fx.fx_beta})",
    ]
    momentum = fx.components.momentum
    if momentum is not None:
        directions = {
            "weakening": "원화 약세 방향",
            "strengthening": "원화 강세 방향",
            "flat": "횡보",
        }
        lines.append(
            f"- USD/KRW 5일 변화: {momentum.usd_krw_5d:+.2f}%% ({directions.get(momentum.direction, '')})"
        )
    alignment = fx.components.regime_alignment
    if alignment is not None:
        lines.append(f"- 환율-종목 정합성: {alignment.boost}")
    currency_labels = {"JPY_KRW": "엔화", "CNY_KRW": "위안화", "EUR_KRW": "유로"}
    for currency, signal in fx.components.cross_currency.items():
        lines.append(f"- {currency_labels.get(currency, currency)} 시그널: {signal}")
    lines.extend(
        (
            f"- **환율 종합 판정: {fx.fx_verdict}** (신뢰도 {fx.fx_confidence:.0%})",
            "",
        )
    )
    return lines


def build_macro_prompt(
    source: MacroPromptSource,
    runtime: MacroPromptRuntime | None = None,
) -> MacroPromptBuild:
    active_runtime = runtime if runtime is not None else MacroPromptRuntime()
    is_us = is_us_ticker(source.ticker)
    currency = "$" if is_us else ""
    unit = "" if is_us else "원"
    price_format = ",.2f" if is_us else ",.0f"
    lines: list[str] = [f"## 종목: {source.name} ({source.ticker})"]
    if is_us:
        lines.append("(미국 시장 종목)")
    lines.extend(
        (
            "",
            "### 시장 데이터",
            f"- 현재가: {currency}{source.signals.current_price:{price_format}}{unit}",
            f"- 20일 수익률: {source.signals.change_20d:+.2f}%%",
            f"- 5일 수익률: {source.signals.change_5d:+.2f}%%",
            f"- 52주 고가: {currency}{source.signals.high_52w:{price_format}}{unit} / 저가: {currency}{source.signals.low_52w:{price_format}}{unit}",
            "",
        )
    )
    if source.fundamentals.per is not None or source.fundamentals.pbr is not None:
        lines.append("### 펀더멘털")
        if source.fundamentals.per is not None:
            lines.append(f"- PER: {source.fundamentals.per}")
        if source.fundamentals.pbr is not None:
            lines.append(f"- PBR: {source.fundamentals.pbr}")
        lines.append("")
    market = source.market_context
    indexes = tuple(
        item for item in (market.kospi, market.kosdaq, market.nasdaq, market.sp500)
        if item is not None
    )
    if market.regime is not None or indexes:
        lines.append("### 시장 환경")
        if market.regime is not None:
            lines.append(
                f"- **시장 레짐: {market.regime.label}** ({market.regime.description})"
            )
        for index in indexes:
            lines.append(
                f"- {index.name}: {index.close:,.2f} (5일 {index.change_5d:+.1f}%%, 20일 {index.change_20d:+.1f}%%)"
            )
        lines.append("")
    fx_class = source.fx_signal.fx_class if source.fx_signal is not None else None
    records = load_verified_prompt_records(
        verified_keywords(source.name, fx_class),
        active_runtime.package_path,
        active_runtime.as_of,
        active_runtime.source_path,
    )
    sections: list[str] = []
    if records:
        sections.append("verified")
        lines.append("### 인과 체인 (데이터 검증됨 — 통계적 선행 근거)")
        lines.extend(f"- {record.render_text}" for record in records)
        lines.append("")
    unverified = (
        causal_context(source.name, source.ticker)
        if active_runtime.causal_context is None
        else active_runtime.causal_context
    )
    if unverified:
        sections.append("unverified")
        lines.extend(("### 인과 그래프 참조 (참고용 — 미검증)", unverified, ""))
    quantitative = (
        _quantitative_context()
        if active_runtime.quantitative_context is None
        else active_runtime.quantitative_context
    )
    if quantitative:
        lines.extend((quantitative, ""))
    macro_news = (
        *market.web_macro.kr_macro,
        *market.web_macro.us_macro,
        *market.web_macro.rates,
        *market.web_macro.fx,
    )
    if macro_news:
        lines.append("### 매크로 최신 동향 (웹 검색)")
        lines.extend(f"- {news.title[:80]}" for news in macro_news[:7])
        lines.append("")
    lines.extend(_web_context_lines(source))
    lines.extend(_fx_lines(source))
    lines.extend(
        (
            "위 데이터를 기반으로 매크로 인과 관점에서 분석하고 JSON으로 응답하세요.",
            "이 기업의 이익에 가장 큰 영향을 미치는 매크로 변수를 식별하고, 인과 체인을 구성하세요.",
        )
    )
    if unverified:
        lines.append("인과 그래프의 배경 지식을 참고하되, 현재 시장 상황에 맞게 판단하세요.")
    return MacroPromptBuild(
        text="\n".join(lines),
        verified_record_ids=tuple(record.prompt_record_id for record in records),
        section_order=tuple(sections),
    )
