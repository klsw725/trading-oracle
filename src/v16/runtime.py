from __future__ import annotations

from pathlib import Path

from .calendar import load_calendar
from .canonical import JsonValue, canonical_hash
from .config import load_config
from .data_health import descriptor_value, health_report
from .errors import FailureCode, V16Failure
from .identity import build_identity
from .input_manifest import load_manifest
from .models import (
    BundleRequest,
    HealthRequest,
    HealthVerdict,
    IdentityRequest,
    Market,
    MarketInput,
    MarketScope,
    RuntimeInputBundle,
)
from .paths import confined_file, fixture_file


def _markets(scope: MarketScope) -> tuple[Market, ...]:
    return (Market.KR, Market.US) if scope is MarketScope.ALL else (Market(scope.value),)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise V16Failure(FailureCode.CONFIG_PATH_OUTSIDE_ROOT, "path outside root") from None


def build_runtime_bundle(request: BundleRequest) -> RuntimeInputBundle:
    root = request.root.resolve()
    if root != request.root or not root.is_absolute():
        raise V16Failure(FailureCode.PROJECT_ROOT_NOT_FOUND, "root must be canonical absolute path")
    config_path = confined_file(root, request.config_path, (".yaml", ".yml"))
    manifest_path = confined_file(root, request.manifest_path, (".json",))
    config = load_config(config_path)
    verified = load_manifest(root, manifest_path)
    report = health_report(HealthRequest(
        root=root,
        verified_manifest=verified,
        config=config,
        as_of=request.as_of,
        scope=request.scope,
    ))
    if report.status != "PASS":
        raise V16Failure(FailureCode.INVALID, "runtime inputs are unhealthy")
    identity = build_identity(IdentityRequest(
        root=root,
        config=config,
        manifest_hash=verified.manifest_hash,
        scope=request.scope,
    ))
    inputs: list[MarketInput] = []
    for market in _markets(request.scope):
        calendar_descriptor = next(
            item for item in verified.manifest.calendars if item.market is market
        )
        calendar = load_calendar(fixture_file(root, calendar_descriptor.path))
        market_health = next(item for item in report.markets if item.market is market)
        if market_health.verdict is not HealthVerdict.HEALTHY:
            raise V16Failure(FailureCode.INVALID, "unhealthy market cannot enter bundle")
        descriptors = tuple(item for item in verified.manifest.datasets if item.market is market)
        settings = config.markets[market]
        inputs.append(MarketInput(
            namespace=(f"{market.value}:{settings.currency}:"
                       f"{config.runtime.account_selector}:{config.runtime.arm_selector}"),
            market=market,
            currency=settings.currency,
            account_selector=config.runtime.account_selector,
            arm_selector=config.runtime.arm_selector,
            calendar_version=calendar.calendar_version,
            calendar_hash=calendar_descriptor.content_hash,
            sessions=tuple(record.session_date for record in calendar.records),
            datasets=descriptors,
            health=market_health,
        ))
    seed: JsonValue = {
        "as_of": report.as_of,
        "health_hash": report.report_hash,
        "identity": identity.runtime_identity,
        "inputs": [{
            "calendar_hash": item.calendar_hash,
            "calendar_version": item.calendar_version,
            "currency": item.currency,
            "datasets": [descriptor_value(descriptor) for descriptor in item.datasets],
            "market": item.market.value,
            "namespace": item.namespace,
            "sessions": list(item.sessions),
        } for item in inputs],
        "manifest_hash": verified.manifest_hash,
        "scope": request.scope.value,
        "schema_version": "v16.runtime-input-bundle.1",
    }
    return RuntimeInputBundle(
        schema_version="v16.runtime-input-bundle.1",
        project_root=root,
        config_path=_relative(root, config_path),
        as_of=request.as_of,
        scope=request.scope,
        identity=identity,
        manifest_hash=verified.manifest_hash,
        inputs=tuple(inputs),
        health=report,
        bundle_hash=canonical_hash(seed),
    )
