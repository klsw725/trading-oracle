from __future__ import annotations

from src.v4.models import JsonValue

from .build_prd01 import build as build_prd01
from .build_prd02 import build as build_prd02
from .build_prd03 import build as build_prd03
from .build_prd04 import build as build_prd04
from .models import V10ContractError


def build_fixture(value: JsonValue) -> JsonValue:
    match value:  # noqa: MATCH_OK - untrusted JSON boundary rejects unsupported variants
        case {"schema_version": "v10.prd01.fixture.1"}:
            return build_prd01(value)
        case {"schema_version": "v10.prd02.fixture.1"}:
            return build_prd02(value)
        case {"schema_version": "v10.prd03.fixture.1"}:
            return build_prd03(value)
        case {"schema_version": "v10.prd04.fixture.1"}:
            return build_prd04(value)
        case {"schema_version": str() as version}:
            raise V10ContractError("V10_FIXTURE_ERROR", version)
        case dict():
            raise V10ContractError("V10_FIXTURE_ERROR", "schema_version missing")
        case _:
            raise V10ContractError("V10_FIXTURE_ERROR", "object fixture required")
