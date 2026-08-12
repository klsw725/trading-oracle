from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from .models import V11ContractError


def fill_cap(target_volume: int) -> int:
    if target_volume < 0:
        raise V11ContractError("V11_VOLUME_MALFORMED", str(target_volume))
    return int((Decimal(target_volume) * Decimal("0.05")).to_integral_value(rounding=ROUND_DOWN))


def verify_causal_sizing(used_target_volume: bool) -> None:
    if used_target_volume:
        raise V11ContractError("V11_LOOKAHEAD", "future_volume")
