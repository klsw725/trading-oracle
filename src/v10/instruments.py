from __future__ import annotations

from enum import StrEnum


class InstrumentType(StrEnum):
    COMMON = "COMMON"
    ETF = "ETF"
    ETN = "ETN"
    PREFERRED = "PREFERRED"
    ADR = "ADR"
    SPAC = "SPAC"
    UNIT = "UNIT"
    WARRANT = "WARRANT"


def ranking_eligible(instrument_type: InstrumentType) -> bool:
    return instrument_type is InstrumentType.COMMON
