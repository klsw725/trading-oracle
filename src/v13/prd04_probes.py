from __future__ import annotations

from collections.abc import Callable

from src.v13.coverage import verify_inventory
from src.v13.models import V13ContractError


def inventory_checks(probe_ids: tuple[str, ...]) -> dict[str, bool]:
    return {
        "probe_missing_rejected": _rejected(lambda: verify_inventory(probe_ids[:-1])),
        "probe_duplicate_rejected": _rejected(lambda: verify_inventory(
            (*probe_ids, probe_ids[0]))),
        "probe_unexpected_rejected": _rejected(lambda: verify_inventory(
            (*probe_ids[:-1], "unexpected"))),
    }


def _rejected(operation: Callable[[], None]) -> bool:
    try:
        operation()
    except V13ContractError as error:
        return error.code == "V13_PROBE_INVENTORY"
    return False
