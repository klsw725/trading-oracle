from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from .calendar import load_calendar
from .canonical import content_hash
from .config import load_config
from .data_health import health_report
from .errors import FailureCode, V16Failure
from .input_manifest import load_manifest
from .models import (BundleRequest, DatasetArtifact, DatasetRow, HealthRequest,
                     InputHealthReport, InputManifest, Market, MarketScope,
                     RuntimeInputBundle, VerifiedManifest)
from .reporting import EvidenceItem, item
from .runtime import build_runtime_bundle


AS_OF = datetime.fromisoformat("2026-01-05T21:00:00+00:00")


def _verified(manifest: InputManifest) -> VerifiedManifest:
    payload = manifest.model_dump_json().encode("utf-8")
    return VerifiedManifest(manifest=manifest, manifest_hash=content_hash(payload))


def _dataset_actual(report: InputHealthReport, market: Market) -> str:
    selected = next(item for item in report.markets if item.market is market)
    return selected.datasets[0].verdict.value if selected.datasets else "MISSING"


def base_bundle(root: Path) -> RuntimeInputBundle:
    return build_runtime_bundle(BundleRequest(root=root,
        config_path=Path("docs/specs/v16/fixtures/runtime-config.yaml"),
        manifest_path=Path("docs/specs/v16/fixtures/input-manifest.json"),
        as_of=AS_OF, scope=MarketScope.ALL))


def healthy_checks(bundle: RuntimeInputBundle) -> list[EvidenceItem]:
    kr = next(item for item in bundle.health.markets if item.market is Market.KR)
    us = next(item for item in bundle.health.markets if item.market is Market.US)
    bound = bundle.identity.namespaces == tuple(item.namespace for item in bundle.inputs)
    return [item("bundle_build", "BOUND_HEALTHY", "BOUND_HEALTHY" if bound else "UNBOUND"),
            item("kr_health", "HEALTHY", kr.verdict.value),
             item("us_health", "HEALTHY", us.verdict.value)]


def unhealthy_bundle_check(root: Path) -> list[EvidenceItem]:
    with TemporaryDirectory() as directory:
        temporary_root = Path(directory).resolve()
        fixture_root = temporary_root / "docs/specs/v16/fixtures"
        _ = shutil.copytree(root / "docs/specs/v16/fixtures", fixture_root)
        _ = (fixture_root / "dataset-kr.json").write_bytes(b'{"corrupt":true}')
        try:
            _ = build_runtime_bundle(BundleRequest(root=temporary_root,
                config_path=Path("docs/specs/v16/fixtures/runtime-config.yaml"),
                manifest_path=Path("docs/specs/v16/fixtures/input-manifest.json"),
                as_of=AS_OF, scope=MarketScope.KR))
            actual = "UNEXPECTED_PASS"
        except V16Failure as error:
            actual = error.code.value
    return [item("bundle_unhealthy_rejected", FailureCode.INVALID.value, actual)]


def calendar_checks(root: Path) -> list[EvidenceItem]:
    source = (root / "docs/specs/v16/fixtures/calendar-us.json").read_text(encoding="utf-8")
    ambiguous = source.replace("2026-01-05", "2026-11-01").replace(
        '"open":"09:30:00"', '"open":"01:30:00"')
    with TemporaryDirectory() as directory:
        path = Path(directory) / "calendar-us.json"
        _ = path.write_text(ambiguous, encoding="utf-8")
        try:
            _ = load_calendar(path)
            actual = "UNEXPECTED_PASS"
        except V16Failure as error:
            actual = error.code.value
    calendar = load_calendar(root / "docs/specs/v16/fixtures/calendar-kr.json")
    invalid_date = calendar.records[0].model_copy(
        update={"session_date": "not-a-date", "status": "CLOSED", "open": None,
                "close": None, "early_close": False})
    with TemporaryDirectory() as directory:
        invalid_path = Path(directory) / "calendar-kr.json"
        _ = invalid_path.write_text(calendar.model_copy(
            update={"records": (invalid_date,)}).model_dump_json(), encoding="utf-8")
        try:
            _ = load_calendar(invalid_path)
            invalid_date_code = "UNEXPECTED_PASS"
        except V16Failure as error:
            invalid_date_code = error.code.value
    config = load_config(root / "docs/specs/v16/fixtures/runtime-config.yaml")
    verified = load_manifest(root, root / "docs/specs/v16/fixtures/input-manifest.json")
    with TemporaryDirectory() as directory:
        temporary_root = Path(directory)
        fixture_root = temporary_root / "docs/specs/v16/fixtures"
        _ = shutil.copytree(root / "docs/specs/v16/fixtures", fixture_root)
        record = calendar.records[0].model_copy(update={"status": "CLOSED", "open": None,
                                                        "close": None, "early_close": False})
        payload = calendar.model_copy(update={"records": (record,)}).model_dump_json().encode("utf-8")
        _ = (fixture_root / "calendar-kr.json").write_bytes(payload)
        descriptor = verified.manifest.calendars[0].model_copy(
            update={"content_hash": content_hash(payload)})
        manifest = verified.manifest.model_copy(update={"calendars": (
            descriptor, verified.manifest.calendars[1])})
        report = health_report(HealthRequest(root=temporary_root,
            verified_manifest=_verified(manifest), config=config, as_of=AS_OF,
            scope=MarketScope.KR))
        closed = _dataset_actual(report, Market.KR)
    return [item("calendar_closed_date_rejected", FailureCode.CALENDAR_INVALID.value,
                 invalid_date_code),
            item("calendar_closed_session_rejected", "INVALID", closed),
            item("calendar_dst_ambiguity_rejected", FailureCode.CALENDAR_INVALID.value, actual)]


def isolation_checks(root: Path) -> list[EvidenceItem]:
    config = load_config(root / "docs/specs/v16/fixtures/runtime-config.yaml")
    verified = load_manifest(root, root / "docs/specs/v16/fixtures/input-manifest.json")
    with TemporaryDirectory() as directory:
        temporary_root = Path(directory)
        fixture_root = temporary_root / "docs/specs/v16/fixtures"
        _ = shutil.copytree(root / "docs/specs/v16/fixtures", fixture_root)
        payload = b'{"schema_version":"v16.calendar.1","corrupt":true}'
        _ = (fixture_root / "calendar-kr.json").write_bytes(payload)
        broken = verified.manifest.calendars[0].model_copy(
            update={"content_hash": content_hash(payload)})
        manifest = verified.manifest.model_copy(update={"calendars": (
            broken, verified.manifest.calendars[1])})
        changed = _verified(manifest)
        us = health_report(HealthRequest(root=temporary_root, verified_manifest=changed,
            config=config, as_of=AS_OF, scope=MarketScope.US))
        all_markets = health_report(HealthRequest(root=temporary_root,
            verified_manifest=changed, config=config, as_of=AS_OF,
            scope=MarketScope.ALL))
    isolated = us.status == "PASS" and len(us.markets) == 1 and us.markets[0].market is Market.US
    preserved = len(all_markets.markets) == 2 and all_markets.status == "FAIL" and \
        all_markets.markets[1].verdict.value == "HEALTHY"
    return [item("market_scope_isolation", "ISOLATED", "ISOLATED" if isolated else "LEAKED"),
            item("all_market_detail_preserved", "PRESERVED",
                  "PRESERVED" if preserved else "DROPPED")]


def hash_binding_checks(root: Path) -> list[EvidenceItem]:
    config = load_config(root / "docs/specs/v16/fixtures/runtime-config.yaml")
    verified = load_manifest(root, root / "docs/specs/v16/fixtures/input-manifest.json")
    base = health_report(HealthRequest(root=root, verified_manifest=verified,
        config=config, as_of=AS_OF, scope=MarketScope.KR))
    first, second = verified.manifest.datasets
    descriptor = first.model_copy(update={"symbols": ("005930", "000660")})
    changed = _verified(verified.manifest.model_copy(
        update={"datasets": (descriptor, second)}))
    descriptor_report = health_report(HealthRequest(root=root, verified_manifest=changed,
        config=config, as_of=AS_OF, scope=MarketScope.KR))
    cutoff_report = health_report(HealthRequest(root=root, verified_manifest=verified,
        config=config, as_of=AS_OF + timedelta(minutes=1), scope=MarketScope.KR))
    bound = base.report_hash != descriptor_report.report_hash and \
        base.report_hash != cutoff_report.report_hash
    return [item("health_input_hash_binding", "DESCRIPTOR_AND_AS_OF_BOUND",
                 "DESCRIPTOR_AND_AS_OF_BOUND" if bound else "UNBOUND")]


def health_mutations(root: Path) -> list[EvidenceItem]:
    config = load_config(root / "docs/specs/v16/fixtures/runtime-config.yaml")
    verified = load_manifest(root, root / "docs/specs/v16/fixtures/input-manifest.json")
    first, second = verified.manifest.datasets
    variants = (
        ("stale_at_replay_cutoff", "STALE", first.model_copy(
            update={"observed_at": AS_OF - timedelta(minutes=11)}), config),
        ("data_hash_forgery", "HASH_MISMATCH", first.model_copy(
            update={"content_hash": "sha256:" + "0" * 64}), config),
        ("market_currency_swap", "INVALID", first.model_copy(update={"currency": "USD"}), config),
    )
    results: list[EvidenceItem] = []
    for mutation_id, expected, descriptor, selected_config in variants:
        changed = verified.manifest.model_copy(update={"datasets": (descriptor, second)})
        report = health_report(HealthRequest(root=root, verified_manifest=_verified(changed),
            config=selected_config, as_of=AS_OF, scope=MarketScope.KR))
        results.append(item(mutation_id, expected, _dataset_actual(report, Market.KR)))
    conflict = config.model_copy(update={"markets": {**config.markets,
        Market.KR: config.markets[Market.KR].model_copy(update={"calendar_version": "conflict"})}})
    report = health_report(HealthRequest(root=root, verified_manifest=verified, config=conflict,
        as_of=AS_OF, scope=MarketScope.KR))
    results.append(item("calendar_conflict", FailureCode.CALENDAR_INVALID.value,
                        report.markets[0].failure_code))
    unknown_values: list[str] = []
    for descriptor in (first.model_copy(update={"source": "unknown-source"}),
                       first.model_copy(update={"dataset_kind": "unknown-kind"})):
        changed = verified.manifest.model_copy(update={"datasets": (descriptor, second)})
        unknown_report = health_report(HealthRequest(root=root,
            verified_manifest=_verified(changed), config=config, as_of=AS_OF,
            scope=MarketScope.KR))
        unknown_values.append(_dataset_actual(unknown_report, Market.KR))
    calendar_source = (root / "docs/specs/v16/fixtures/calendar-kr.json").read_text(
        encoding="utf-8").replace('"status":"OPEN"', '"status":"UNKNOWN"')
    with TemporaryDirectory() as directory:
        path = Path(directory) / "calendar.json"
        _ = path.write_text(calendar_source, encoding="utf-8")
        try:
            _ = load_calendar(path)
            calendar_code = "UNEXPECTED_PASS"
        except V16Failure as error:
            calendar_code = error.code.value
    results.append(item("unknown_source_kind", "UNKNOWN|UNKNOWN|CALENDAR_INVALID",
                        "|".join((*unknown_values, calendar_code))))
    return results


def health_edge_checks(root: Path) -> list[EvidenceItem]:
    config = load_config(root / "docs/specs/v16/fixtures/runtime-config.yaml")
    verified = load_manifest(root, root / "docs/specs/v16/fixtures/input-manifest.json")
    artifact = DatasetArtifact.model_validate_json(
        (root / "docs/specs/v16/fixtures/dataset-kr.json").read_bytes())
    rows = artifact.rows
    outside_start = datetime.fromisoformat("2026-01-05T07:00:00+00:00")
    outside = tuple(row.model_copy(update={"timestamp": outside_start + timedelta(minutes=index * 5)})
                    for index, row in enumerate(rows))
    future = (*rows[:-1], rows[-1].model_copy(update={"timestamp": AS_OF + timedelta(minutes=5)}))
    split_grid = (rows[0], rows[1].model_copy(update={"symbol": "000660"}), rows[2])
    aapl = tuple(row.model_copy(update={"symbol": "AAPL"}) for row in rows)
    cases: tuple[tuple[str, tuple[DatasetRow, ...], str,
                       dict[str, datetime | tuple[str, ...]]], ...] = (
             ("data_duplicate_rejected", (rows[0], rows[0], rows[2]), "INVALID", {}),
             ("data_order_rejected", (rows[1], rows[0], rows[2]), "INVALID", {}),
             ("data_per_symbol_grid_rejected", split_grid, "INCOMPLETE",
                {"symbols": ("005930", "000660")}),
             ("data_missing_interval_rejected", (rows[0], rows[2]), "INCOMPLETE", {}),
             ("data_outside_session_rejected", outside, "INVALID", {"min_timestamp": outside[0].timestamp,
                "max_timestamp": outside[-1].timestamp}),
             ("data_future_rejected", future, "INVALID", {"max_timestamp": future[-1].timestamp}),
             ("data_kr_symbol_syntax_rejected", aapl, "INVALID", {"symbols": ("AAPL",)}),
             ("data_observed_after_as_of_rejected", rows, "INVALID",
                {"observed_at": AS_OF + timedelta(minutes=1)}),
             ("data_required_symbol_rejected", rows, "INCOMPLETE",
                {"symbols": ("005930", "000660")}))
    results: list[EvidenceItem] = []
    with TemporaryDirectory() as directory:
        temporary_root = Path(directory)
        fixture_root = temporary_root / "docs/specs/v16/fixtures"
        _ = shutil.copytree(root / "docs/specs/v16/fixtures", fixture_root)
        for check_id, changed_rows, expected, descriptor_updates in cases:
            payload = artifact.model_copy(update={"rows": changed_rows}).model_dump_json().encode("utf-8")
            _ = (fixture_root / "dataset-kr.json").write_bytes(payload)
            descriptor = verified.manifest.datasets[0].model_copy(
                update={"content_hash": content_hash(payload), **descriptor_updates})
            manifest = verified.manifest.model_copy(update={"datasets": (
                descriptor, verified.manifest.datasets[1])})
            report = health_report(HealthRequest(root=temporary_root,
                verified_manifest=_verified(manifest), config=config, as_of=AS_OF,
                scope=MarketScope.KR))
            results.append(item(check_id, expected, _dataset_actual(report, Market.KR)))
    return results
