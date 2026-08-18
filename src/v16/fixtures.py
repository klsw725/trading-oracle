from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .canonical import JsonValue, canonical_hash, content_hash
from .errors import FailureCode, V16Failure
from .models import FixtureInventory
from .paths import fixture_file
from .registries import FIXTURE_FILES


def inventory_paths(root: Path) -> tuple[str, ...]:
    path = fixture_file(root, "inventory.json")
    try:
        inventory = FixtureInventory.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise V16Failure(FailureCode.FIXTURE_INVENTORY_MISMATCH,
                         "inventory schema rejected") from error
    return tuple(entry.path for entry in inventory.files)


def verify_inventory(root: Path) -> str:
    path = fixture_file(root, "inventory.json")
    try:
        payload = path.read_bytes()
        inventory = FixtureInventory.model_validate_json(payload)
    except (OSError, ValidationError) as error:
        raise V16Failure(FailureCode.FIXTURE_INVENTORY_MISMATCH,
                         "inventory schema rejected") from error
    declared = tuple(entry.path for entry in inventory.files)
    observed_files = tuple(sorted(
        item.name for item in path.parent.iterdir()
        if item.is_file() and item.name != "inventory.json"
    ))
    if declared != FIXTURE_FILES or observed_files != tuple(sorted(FIXTURE_FILES)):
        raise V16Failure(FailureCode.FIXTURE_INVENTORY_MISMATCH,
                         "fixture file set mismatch")
    observed: list[JsonValue] = []
    for entry in inventory.files:
        digest = content_hash(fixture_file(root, entry.path).read_bytes())
        if digest != entry.sha256:
            raise V16Failure(FailureCode.FIXTURE_INVENTORY_MISMATCH,
                             "fixture digest mismatch")
        observed.append({"path": entry.path, "sha256": digest})
    evidence: JsonValue = {"files": observed, "inventory_hash": content_hash(payload)}
    return canonical_hash(evidence)
