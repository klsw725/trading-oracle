from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict
from src.v16.models import RuntimeIdentity

from .canonical import JsonValue, content_hash, parse_json
from .errors import V17Error
from .identity import verify_runtime_identity

ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURE_ROOT: Final = ROOT / "docs/specs/v17/fixtures"
PRIMARY_RUNTIME_IDENTITY: Final = "sha256:8078b2da4b0320378dbfb3a8f9d5643672aaec9df42c68384d52725410964482"


class InventoryEntry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    path: str
    sha256: str


class Inventory(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    schema_version: str
    files: tuple[InventoryEntry, ...]


class IdentityFixture(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    schema_version: str
    identities: tuple[RuntimeIdentity, ...]


def verify_inventory() -> str:
    inventory = Inventory.model_validate_json((FIXTURE_ROOT / "inventory.json").read_bytes())
    if inventory.schema_version != "v17.fixture-inventory.1":
        raise V17Error("FIXTURE_SCHEMA_INVALID", inventory.schema_version)
    for entry in inventory.files:
        path = (FIXTURE_ROOT / entry.path).resolve()
        if path.parent != FIXTURE_ROOT or content_hash(path.read_bytes()) != entry.sha256:
            raise V17Error("FIXTURE_HASH_MISMATCH", entry.path)
    return content_hash((FIXTURE_ROOT / "inventory.json").read_bytes())


def identities() -> tuple[RuntimeIdentity, ...]:
    fixture = IdentityFixture.model_validate_json(
        (FIXTURE_ROOT / "runtime-identities.json").read_bytes()
    )
    if fixture.schema_version != "v17.runtime-identities.1":
        raise V17Error("FIXTURE_SCHEMA_INVALID", fixture.schema_version)
    if fixture.identities[0].runtime_identity != PRIMARY_RUNTIME_IDENTITY:
        raise V17Error("FIXTURE_IDENTITY_MISMATCH", fixture.identities[0].runtime_identity)
    for identity in fixture.identities:
        verify_runtime_identity(identity)
    return fixture.identities


def event_fixture() -> JsonValue:
    return parse_json((FIXTURE_ROOT / "event-fixtures.json").read_bytes())
