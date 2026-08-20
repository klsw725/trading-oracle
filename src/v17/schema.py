from typing import Final

SCHEMA_HEAD: Final = 1
EVENT_SCHEMA_VERSION: Final = "v17.event.1"
GENESIS_HASH: Final = "sha256:" + "0" * 64
INT64_MIN: Final = -(2**63)
INT64_MAX: Final = 2**63 - 1
TABLES: Final = (
    "schema_migrations",
    "accounts",
    "events",
    "idempotency_keys",
    "account_balances",
    "account_positions",
    "account_reservations",
    "projection_checkpoints",
)


def require_int64(value: int, field: str) -> int:
    if isinstance(value, bool) or not INT64_MIN <= value <= INT64_MAX:
        from .errors import V17Error

        raise V17Error("INTEGER_OUT_OF_RANGE", field)
    return value
