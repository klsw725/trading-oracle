from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import BinaryIO, Final

from pydantic import ValidationError

from .canonical import JsonValue, canonical_json
from .errors import V17Error

type Dispatcher = Callable[[list[str]], JsonValue]

HELP: Final = (
    b"usage: python -m src.v17.cli {migrate,verify,replay,prd01-acceptance," +
    b"prd02-acceptance,prd03-acceptance,prd04-acceptance,acceptance}\n"
)


def run_cli(
    arguments: list[str], stdout: BinaryIO, stderr: BinaryIO, dispatch: Dispatcher
) -> int:
    if arguments == ["--help"]:
        _ = stdout.write(HELP)
        return 0
    try:
        report = dispatch(arguments)
    except (V17Error, ValidationError, sqlite3.Error) as error:
        code = error.code if isinstance(error, V17Error) else "INVALID_INPUT"
        payload: JsonValue = {"schema_version": "v17.error.1", "status": "FAIL", "code": code}
        _ = stdout.write(canonical_json(payload) + b"\n")
        return 2
    except Exception:  # noqa: BROAD_EXCEPT_OK - final CLI boundary redacts defects.
        payload = {"schema_version": "v17.error.1", "status": "ERROR", "code": "INTERNAL_ERROR"}
        _ = stdout.write(canonical_json(payload) + b"\n")
        _ = stderr.write(b"INTERNAL_ERROR\n")
        return 1
    _ = stdout.write(canonical_json(report) + b"\n")
    return 0
