from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from pydantic import TypeAdapter

from .canonical import content_hash
from .errors import V18Error
from .evaluator import price_content_hash
from .models import (
    AdjustedClose,
    CalendarSession,
    Currency,
    Market,
    Namespace,
    SessionStatus,
)
from .sessions import calendar_content_hash

ROOT: Final = Path(__file__).parents[2]
FIXTURE_ROOT: Final = ROOT / "docs/specs/v18/fixtures"
MEASUREMENT_FIXTURE: Final = FIXTURE_ROOT / "measurement-fixture.json"
PREDICTION_FIXTURE: Final = FIXTURE_ROOT / "prediction-kr.json"


class SessionRow(TypedDict):
    market: str
    session: str
    status: str
    close_at: str | None


class PriceRow(TypedDict):
    market: str
    currency: str
    symbol: str
    session: str
    adjusted_close_minor: int


class FixtureBody(TypedDict):
    schema_version: str
    calendar_version: str
    calendar_hash: str
    price_adjustment_version: str
    price_dataset_hash: str
    sessions: list[SessionRow]
    prices: list[PriceRow]


_FIXTURE: Final = TypeAdapter(FixtureBody)


@dataclass(frozen=True, slots=True)
class MeasurementFixture:
    calendar_version: str
    calendar_hash: str
    price_adjustment_version: str
    price_dataset_hash: str
    sessions: tuple[CalendarSession, ...]
    prices: tuple[AdjustedClose, ...]


def load_fixture(
    account_id: str = "fixture-paper", arm_id: str = "fixture-arm"
) -> MeasurementFixture:
    body = _FIXTURE.validate_json(MEASUREMENT_FIXTURE.read_bytes())
    if body["schema_version"] != "v18.fixture.1":
        raise V18Error("FIXTURE_SCHEMA_INVALID", body["schema_version"])
    sessions = tuple(
        CalendarSession(
            market=Market(row["market"]),
            session=row["session"],
            status=SessionStatus(row["status"]),
            close_at=row["close_at"],
            calendar_version=body["calendar_version"],
            calendar_hash=body["calendar_hash"],
        )
        for row in body["sessions"]
    )
    prices = tuple(
        AdjustedClose(
            namespace=Namespace(
                market=Market(row["market"]),
                currency=Currency(row["currency"]),
                account_id=account_id,
                arm_id=arm_id,
                symbol=row["symbol"],
            ),
            session=row["session"],
            adjusted_close_minor=row["adjusted_close_minor"],
            adjustment_version=body["price_adjustment_version"],
            dataset_hash=body["price_dataset_hash"],
        )
        for row in body["prices"]
    )
    if calendar_content_hash(sessions) != body["calendar_hash"]:
        raise V18Error("CALENDAR_IDENTITY_MISMATCH", body["calendar_hash"])
    if price_content_hash(prices) != body["price_dataset_hash"]:
        raise V18Error("PRICE_ADJUSTMENT_MISMATCH", body["price_dataset_hash"])
    return MeasurementFixture(
        body["calendar_version"],
        body["calendar_hash"],
        body["price_adjustment_version"],
        body["price_dataset_hash"],
        sessions,
        prices,
    )


def fixture_inventory() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): content_hash(path.read_bytes())
        for path in (MEASUREMENT_FIXTURE, PREDICTION_FIXTURE)
    }
