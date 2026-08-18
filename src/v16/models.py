from __future__ import annotations

from enum import StrEnum, unique
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


@unique
class Market(StrEnum):
    KR = "KR"
    US = "US"


@unique
class MarketScope(StrEnum):
    KR = "KR"
    US = "US"
    ALL = "ALL"


@unique
class HealthVerdict(StrEnum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    HASH_MISMATCH = "HASH_MISMATCH"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class RuntimeSettings(StrictModel):
    mode: Literal["paper"]
    account_selector: str
    arm_selector: str


class MarketSettings(StrictModel):
    currency: str
    timezone: str
    calendar_version: str


class DataSettings(StrictModel):
    freshness_minutes: dict[str, dict[Market, Annotated[int, Field(strict=True, gt=0)]]]


class RuntimeConfig(StrictModel):
    config_schema_version: str
    policy_version: str
    runtime: RuntimeSettings
    markets: dict[Market, MarketSettings]
    data: DataSettings


class RuntimeIdentity(StrictModel):
    identity_schema_version: Literal["v16.runtime-identity.1"]
    config_hash: str
    policy_version: str
    calendar_versions: dict[Market, str]
    input_manifest_hash: str
    python_version: str
    lock_hash: str
    account_selector: str
    arm_selector: str
    namespaces: tuple[str, ...]
    runtime_identity: str


class CalendarRecord(StrictModel):
    market: Market
    session_date: str
    status: Literal["OPEN", "CLOSED", "EARLY_CLOSE"]
    timezone: str
    open: str | None
    close: str | None
    early_close: bool


class CalendarArtifact(StrictModel):
    schema_version: Literal["v16.calendar.1"]
    calendar_version: str
    market: Market
    records: tuple[CalendarRecord, ...]


class DatasetDescriptor(StrictModel):
    id: str
    dataset_kind: str
    market: Market
    currency: str
    session: str
    source: str
    source_version: str
    observed_at: AwareDatetime
    expected_interval_minutes: Annotated[int, Field(strict=True, gt=0)]
    row_count: Annotated[int, Field(strict=True, gt=0)]
    min_timestamp: AwareDatetime
    max_timestamp: AwareDatetime
    content_hash: str
    path: str
    symbols: tuple[str, ...]


class CalendarDescriptor(StrictModel):
    market: Market
    calendar_version: str
    content_hash: str
    path: str


class InputManifest(StrictModel):
    schema_version: Literal["v16.input-manifest.1"]
    calendars: tuple[CalendarDescriptor, ...]
    datasets: tuple[DatasetDescriptor, ...]


class VerifiedManifest(StrictModel):
    manifest: InputManifest
    manifest_hash: str


class DatasetRow(StrictModel):
    timestamp: AwareDatetime
    symbol: str
    close: str


class DatasetArtifact(StrictModel):
    schema_version: Literal["v16.dataset.1"]
    rows: tuple[DatasetRow, ...]


class InventoryEntry(StrictModel):
    path: str
    sha256: str


class FixtureInventory(StrictModel):
    schema_version: Literal["v16.fixture-inventory.1"]
    files: tuple[InventoryEntry, ...]


class DatasetHealth(StrictModel):
    id: str
    verdict: HealthVerdict
    failure_code: str
    expected: str
    actual: str
    descriptor_hash: str
    evidence_hash: str


class CalendarHealth(StrictModel):
    verdict: HealthVerdict
    failure_code: str
    version: str
    content_hash: str
    expected: str
    actual: str
    evidence_hash: str


class MarketHealth(StrictModel):
    market: Market
    verdict: HealthVerdict
    failure_code: str
    calendar: CalendarHealth
    datasets: tuple[DatasetHealth, ...]
    evidence_hash: str


class InputHealthReport(StrictModel):
    schema_version: Literal["v16.input-health.1"]
    status: Literal["PASS", "FAIL"]
    as_of: str
    manifest_hash: str
    markets: tuple[MarketHealth, ...]
    report_hash: str


class MarketInput(StrictModel):
    namespace: str
    market: Market
    currency: str
    account_selector: str
    arm_selector: str
    calendar_version: str
    calendar_hash: str
    sessions: tuple[str, ...]
    datasets: tuple[DatasetDescriptor, ...]
    health: MarketHealth


class RuntimeInputBundle(StrictModel):
    schema_version: Literal["v16.runtime-input-bundle.1"]
    project_root: Path
    config_path: str
    as_of: AwareDatetime
    scope: MarketScope
    identity: RuntimeIdentity
    manifest_hash: str
    inputs: tuple[MarketInput, ...]
    health: InputHealthReport
    bundle_hash: str


class BundleRequest(StrictModel):
    root: Path
    config_path: Path
    manifest_path: Path
    as_of: AwareDatetime
    scope: MarketScope


class HealthRequest(StrictModel):
    root: Path
    verified_manifest: VerifiedManifest
    config: RuntimeConfig
    as_of: AwareDatetime
    scope: MarketScope


class IdentityRequest(StrictModel):
    root: Path
    config: RuntimeConfig
    manifest_hash: str
    scope: MarketScope

