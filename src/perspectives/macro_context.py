from __future__ import annotations

import json
from typing import ClassVar, Protocol

import networkx as nx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from src.causal.graph import CausalGraph
from src.data.market import is_us_ticker
from src.v4.models import JsonValue


class _ContextModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")


class _CausalEdge(_ContextModel):
    subject: str
    relation: str
    object: str


class _CausalChain(_ContextModel):
    causes: tuple[_CausalEdge, ...] = ()
    effects: tuple[_CausalEdge, ...] = ()


_CHAINS = TypeAdapter(tuple[_CausalChain, ...])


class _ChainReader(Protocol):
    def get_related_chains(
        self, keywords: list[str], depth: int = 2
    ) -> list[dict[str, JsonValue]]: ...


def _related_chains(
    reader: _ChainReader, keywords: list[str]
) -> list[dict[str, JsonValue]]:
    return reader.get_related_chains(keywords, depth=2)


def verified_keywords(name: str, fx_class: str | None) -> list[str]:
    keywords = [name, "환율", "원달러"]
    if "전자" in name or "하이닉스" in name:
        keywords.extend(["반도체", "금리", "수출 경쟁력"])
    elif "자동차" in name or "기아" in name or "현대" in name:
        keywords.extend(["자동차", "엔화", "수출 경쟁력"])
    elif "에어로" in name:
        keywords.extend(["방산", "금리"])
    elif "금융" in name or "은행" in name:
        keywords.extend(["금리", "금융"])
    elif "화학" in name or "철강" in name or "포스코" in name:
        keywords.extend(["위안화", "원자재 수입", "환율 비용"])
    elif "조선" in name:
        keywords.extend(["유로", "수출 경쟁력"])
    if fx_class == "export":
        keywords.extend(["수출 경쟁력", "원화 약세 수혜"])
    elif fx_class == "import":
        keywords.extend(["원자재 수입", "환율 비용"])
    return keywords


def _unverified_keywords(name: str, ticker: str) -> list[str]:
    keywords = [name]
    if is_us_ticker(ticker):
        name_upper = name.upper()
        ticker_upper = ticker.upper()
        if ticker_upper in ("NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "TSM") or "SEMICONDUCTOR" in name_upper:
            keywords.extend(["반도체", "AI 반도체", "메모리", "GPU"])
        elif ticker_upper in ("AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN") or "TECH" in name_upper:
            keywords.extend(["빅테크", "클라우드", "AI"])
        elif ticker_upper in ("TSLA", "RIVN", "LCID", "NIO", "LI", "XPEV"):
            keywords.extend(["전기차", "자율주행", "배터리"])
        elif ticker_upper in ("JPM", "BAC", "GS", "MS", "C", "WFC"):
            keywords.extend(["금리", "금융", "미국 금리"])
        elif ticker_upper in ("XOM", "CVX", "COP", "SLB", "OXY"):
            keywords.extend(["원유", "에너지", "원자재"])
        elif ticker_upper in ("JNJ", "PFE", "UNH", "ABBV", "MRK", "LLY"):
            keywords.extend(["헬스케어", "바이오", "신약"])
        elif ticker_upper in ("LMT", "RTX", "NOC", "GD", "BA"):
            keywords.extend(["방산", "지정학"])
        else:
            keywords.extend(["미국 금리", "빅테크"])
    elif "전자" in name or "반도체" in name or "하이닉스" in name:
        keywords.extend(["반도체", "메모리", "디램"])
    elif "자동차" in name or "기아" in name or "현대" in name:
        keywords.extend(["자동차", "전기차"])
    elif "에어로" in name or "한화" in name:
        keywords.extend(["방산", "무기"])
    elif "금융" in name or "은행" in name or "지주" in name:
        keywords.extend(["금리", "금융"])
    elif "바이오" in name or "제약" in name:
        keywords.extend(["바이오", "신약"])
    elif "에너지" in name or "배터리" in name:
        keywords.extend(["에너지", "배터리", "2차전지"])
    return keywords


def causal_context(name: str, ticker: str) -> str:
    try:
        graph = CausalGraph.load_if_exists()
        if graph is None:
            return ""
        chains = _CHAINS.validate_python(
            _related_chains(graph, _unverified_keywords(name, ticker))
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValidationError, nx.NetworkXError):
        return ""
    seen: set[tuple[str, str, str]] = set()
    lines: list[str] = []
    for chain in chains[:5]:
        for edges in (chain.causes[:2], chain.effects[:2]):
            for edge in edges:
                key = (edge.subject, edge.relation, edge.object)
                if key not in seen:
                    seen.add(key)
                    lines.append(f"- {edge.subject} → ({edge.relation}) → {edge.object}")
    return "\n".join(lines)
