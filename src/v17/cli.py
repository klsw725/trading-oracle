from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from .canonical import JsonValue
from .cli_contract import run_cli
from .errors import V17Error
from .migrations import migrate_database
from .replay import replay_database
from .store import verify_database


ROOT: Final = Path(__file__).resolve().parents[2]
PRODUCTION_COMMANDS: Final = frozenset({"migrate", "verify", "replay"})
ACCEPTANCE_COMMANDS: Final = frozenset({
    "acceptance", "prd01-acceptance", "prd02-acceptance",
    "prd03-acceptance", "prd04-acceptance",
})


def _database_path(raw: str) -> Path:
    candidate = Path(raw)
    resolved = (ROOT / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_relative_to(ROOT):
        raise V17Error("DATABASE_PATH_OUTSIDE_ROOT", str(resolved))
    return resolved


def _run(arguments: list[str]) -> JsonValue:
    match arguments:  # noqa: MATCH_OK - CLI boundary rejects unknown argument shapes.
        case [command] if command in ACCEPTANCE_COMMANDS:
            from .acceptance import run_acceptance

            return run_acceptance()
        case ["migrate", "--database", raw]:
            database = _database_path(raw)
            result = migrate_database(database)
            return {"schema_version": "v17.migrate.1", "status": "PASS",
                    "schema_head": result.schema_head, "schema_hash": result.schema_hash,
                    "applied": list(result.applied)}
        case ["verify", "--database", raw]:
            database = _database_path(raw)
            return {"schema_version": "v17.verify.1", "status": "PASS",
                    "projection_hash": verify_database(database)}
        case ["replay", "--database", raw]:
            database = _database_path(raw)
            return {"schema_version": "v17.replay.1", "status": "PASS",
                    "projection_hash": replay_database(database)}
        case _:
            raise V17Error("CLI_USAGE_ERROR", "invalid arguments")


def main(arguments: list[str] | None = None) -> int:
    return run_cli(sys.argv[1:] if arguments is None else arguments,
                   sys.stdout.buffer, sys.stderr.buffer, _run)


if __name__ == "__main__":
    raise SystemExit(main())
