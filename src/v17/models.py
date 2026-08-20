from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Literal

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.v16.models import Market, RuntimeIdentity

from .errors import V17Error


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)


@unique
class Currency(StrEnum):
    KRW = "KRW"
    USD = "USD"


class AccountNamespace(StrictModel):
    account_id: str = Field(min_length=1)
    market: Market
    currency: Currency
    arm_id: str = Field(min_length=1)

    @field_validator("account_id", "arm_id")
    @classmethod
    def canonical_identifier(cls, value: str) -> str:
        if value != value.strip() or ":" in value:
            raise V17Error("INVALID_NAMESPACE", value)
        return value

    @model_validator(mode="after")
    def market_currency_pair(self) -> AccountNamespace:
        if (self.market, self.currency) not in {
            (Market.KR, Currency.KRW),
            (Market.US, Currency.USD),
        }:
            raise V17Error("INVALID_MARKET_CURRENCY", f"{self.market}/{self.currency}")
        return self

    def selector(self) -> str:
        return ":".join((self.market.value, self.currency.value, self.account_id, self.arm_id))


class OpenedPayload(StrictModel):
    opening_cash_minor: int = Field(ge=0)


class AmountPayload(StrictModel):
    amount_minor: int = Field(gt=0)


class PositionPayload(StrictModel):
    symbol: str = Field(min_length=1)
    quantity_delta: int
    average_cost_minor: int = Field(ge=0)

    @field_validator("symbol")
    @classmethod
    def canonical_symbol(cls, value: str) -> str:
        if value != value.strip() or value != value.upper():
            raise V17Error("INVALID_SYMBOL", value)
        return value

    @field_validator("quantity_delta")
    @classmethod
    def nonzero_delta(cls, value: int) -> int:
        if value == 0:
            raise V17Error("INVALID_QUANTITY", "zero")
        return value


class ReservationPayload(StrictModel):
    reservation_id: str = Field(min_length=1)
    amount_minor: int = Field(gt=0)


class ReleasePayload(StrictModel):
    reservation_id: str = Field(min_length=1)


type EventPayload = (
    OpenedPayload | AmountPayload | PositionPayload | ReservationPayload | ReleasePayload
)
type EventType = Literal[
    "account.opened",
    "cash.credited",
    "cash.debited",
    "position.adjusted",
    "reservation.placed",
    "reservation.released",
]


@dataclass(frozen=True, slots=True)
class Command:
    command_type: EventType
    command_id: str
    namespace: AccountNamespace
    identity: RuntimeIdentity
    config_version: str
    policy_version: str
    effective_at: str
    payload: EventPayload
    expected_previous_event_hash: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    event_id: str
    sequence: int
    result_hash: str
    duplicate: bool


@dataclass(frozen=True, slots=True)
class MigrationResult:
    database: Path
    applied: tuple[int, ...]
    schema_head: int
    schema_hash: str
