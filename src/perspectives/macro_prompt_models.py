from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from src.causal.prompt_injection_runtime import (
    PROMPT_PACKAGE_PATH,
    VERIFICATION_ARTIFACT_PATH,
)
from src.v4.models import JsonValue


class PromptModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")


class SignalData(PromptModel):
    current_price: float
    change_20d: float
    change_5d: float
    high_52w: float
    low_52w: float


class FundamentalData(PromptModel):
    per: str | float | int | None = None
    pbr: str | float | int | None = None


class RegimeData(PromptModel):
    label: str
    description: str


class IndexData(PromptModel):
    name: str
    close: float
    change_5d: float
    change_20d: float


class NewsItem(PromptModel):
    title: str = ""
    date: str = ""


class WebMacroData(PromptModel):
    kr_macro: tuple[NewsItem, ...] = ()
    us_macro: tuple[NewsItem, ...] = ()
    rates: tuple[NewsItem, ...] = ()
    fx: tuple[NewsItem, ...] = ()


class MarketContextData(PromptModel):
    regime: RegimeData | None = None
    kospi: IndexData | None = None
    kosdaq: IndexData | None = None
    nasdaq: IndexData | None = None
    sp500: IndexData | None = None
    web_macro: WebMacroData = Field(default_factory=WebMacroData)


class WebContextData(PromptModel):
    searched_at: str = ""
    news: tuple[NewsItem, ...] = ()
    sector_0: tuple[NewsItem, ...] = ()
    sector_1: tuple[NewsItem, ...] = ()


class FxMomentum(PromptModel):
    direction: str = ""
    usd_krw_5d: float = 0.0


class FxAlignment(PromptModel):
    boost: str = "NEUTRAL"


class FxComponents(PromptModel):
    momentum: FxMomentum | None = None
    regime_alignment: FxAlignment | None = None
    cross_currency: dict[str, JsonValue] = Field(default_factory=dict)


class FxSignalData(PromptModel):
    fx_class: str = "neutral"
    fx_beta: str | float | int | None = "N/A"
    components: FxComponents = Field(default_factory=FxComponents)
    fx_verdict: str = "NEUTRAL"
    fx_confidence: float = 0.0


class MacroPromptSource(PromptModel):
    ticker: str
    name: str
    signals: SignalData
    fundamentals: FundamentalData = Field(default_factory=FundamentalData)
    market_context: MarketContextData = Field(default_factory=MarketContextData)
    web_context: WebContextData = Field(default_factory=WebContextData)
    fx_signal: FxSignalData | None = None


@dataclass(frozen=True, slots=True)
class MacroPromptRuntime:
    package_path: Path = PROMPT_PACKAGE_PATH
    source_path: Path = VERIFICATION_ARTIFACT_PATH
    as_of: str | None = None
    causal_context: str | None = None
    quantitative_context: str | None = None


@dataclass(frozen=True, slots=True)
class MacroPromptBuild:
    text: str
    verified_record_ids: tuple[str, ...]
    section_order: tuple[str, ...]


MACRO_PROMPT_SOURCE_ADAPTER = TypeAdapter(MacroPromptSource)
