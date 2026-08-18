from __future__ import annotations

import platform

from .canonical import JsonValue, canonical_hash, content_hash
from .models import IdentityRequest, Market, MarketScope, RuntimeConfig, RuntimeIdentity


def config_value(config: RuntimeConfig) -> JsonValue:
    return {
        "config_schema_version": config.config_schema_version,
        "policy_version": config.policy_version,
        "runtime": {"account_selector": config.runtime.account_selector,
                    "arm_selector": config.runtime.arm_selector, "mode": config.runtime.mode},
        "markets": {market.value: {
            "calendar_version": settings.calendar_version,
            "currency": settings.currency, "timezone": settings.timezone}
            for market, settings in config.markets.items()},
        "data": {"freshness_minutes": {kind: {market.value: minutes
            for market, minutes in limits.items()}
            for kind, limits in config.data.freshness_minutes.items()}},
    }


def build_identity(request: IdentityRequest) -> RuntimeIdentity:
    lock_path = request.root / "uv.lock"
    lock_hash = content_hash(lock_path.read_bytes())
    config_hash = canonical_hash(config_value(request.config))
    markets = (Market.KR, Market.US) if request.scope is MarketScope.ALL else (
        Market(request.scope.value),)
    calendar_versions = {market: request.config.markets[market].calendar_version
                         for market in markets}
    namespaces = tuple(":".join((market.value, request.config.markets[market].currency,
                                  request.config.runtime.account_selector,
                                  request.config.runtime.arm_selector))
                       for market in markets)
    seed: JsonValue = {
        "identity_schema_version": "v16.runtime-identity.1",
        "config_hash": config_hash,
        "policy_version": request.config.policy_version,
        "calendar_versions": {key.value: value for key, value in calendar_versions.items()},
        "input_manifest_hash": request.manifest_hash,
        "python_version": platform.python_version(),
        "lock_hash": lock_hash,
        "account_selector": request.config.runtime.account_selector,
        "arm_selector": request.config.runtime.arm_selector,
        "namespaces": list(namespaces),
    }
    return RuntimeIdentity(identity_schema_version="v16.runtime-identity.1",
                           config_hash=config_hash, policy_version=request.config.policy_version,
                           calendar_versions=calendar_versions,
                           input_manifest_hash=request.manifest_hash,
                           python_version=platform.python_version(), lock_hash=lock_hash,
                           account_selector=request.config.runtime.account_selector,
                           arm_selector=request.config.runtime.arm_selector,
                           namespaces=namespaces,
                           runtime_identity=canonical_hash(seed))
