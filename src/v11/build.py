from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from src.v4.models import JsonValue

from .bundle import seal_bundle
from .fixture_models import Prd01Fixture, Prd02Fixture, Prd03Fixture, Prd04Fixture
from .models import V11ContractError
from .prd02_scenario import build_prd02
from .scenarios import build_prd01, build_prd03, build_prd04


def build_fixture(value: JsonValue) -> JsonValue:
    try:
        match value:  # noqa: MATCH_OK - untrusted JSON boundary rejects remaining variants
            case {"schema_version": "v11.prd01.fixture.2"}:
                fixture = Prd01Fixture.model_validate(value)
                return seal_bundle(1, value, build_prd01(fixture), ())
            case {"schema_version": "v11.prd02.fixture.2"}:
                fixture = Prd02Fixture.model_validate(value)
                from pathlib import Path
                from .canonical import parse_json
                root = Path(__file__).resolve().parents[2]
                prd01 = build_prd01(Prd01Fixture.model_validate(
                    parse_json((root / fixture.prd01_fixture).read_bytes())))
                return seal_bundle(2, value, build_prd02(fixture, prd01), ())
            case {"schema_version": "v11.prd03.fixture.2"}:
                fixture = Prd03Fixture.model_validate(value)
                return seal_bundle(3, value, build_prd03(fixture), ())
            case {"schema_version": "v11.prd04.fixture.2"}:
                fixture = Prd04Fixture.model_validate(value)
                return seal_bundle(4, value, build_prd04(fixture), ())
            case _:
                raise V11ContractError("V11_FIXTURE_ERROR", "schema_version")
    except ValidationError as error:
        raise V11ContractError("V11_FIXTURE_ERROR", str(error)) from error


def prd_number(value: int) -> Literal[1, 2, 3, 4]:
    match value:  # noqa: MATCH_OK - integer boundary rejects values outside PRD inventory
        case 1: return 1
        case 2: return 2
        case 3: return 3
        case 4: return 4
        case _: raise V11ContractError("V11_CLI_ARGUMENT_ERROR", str(value))
