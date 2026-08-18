from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .canonical import content_hash
from .errors import FailureCode, V16Failure
from .models import InputManifest, Market, VerifiedManifest


def load_manifest(root: Path, path: Path) -> VerifiedManifest:
    fixture_root = (root / "docs/specs/v16/fixtures").resolve()
    resolved = path.resolve()
    try:
        _ = resolved.relative_to(fixture_root)
    except ValueError:
        raise V16Failure(FailureCode.MANIFEST_INVALID, "manifest outside fixture root") from None
    try:
        payload = resolved.read_bytes()
        manifest = InputManifest.model_validate_json(payload)
    except (OSError, ValidationError) as error:
        raise V16Failure(FailureCode.MANIFEST_INVALID, "manifest schema rejected") from error
    calendar_markets = tuple(item.market for item in manifest.calendars)
    dataset_markets = {item.market for item in manifest.datasets}
    if set(calendar_markets) != {Market.KR, Market.US} or len(calendar_markets) != 2 or \
            dataset_markets != {Market.KR, Market.US}:
        raise V16Failure(FailureCode.MANIFEST_INVALID, "KR and US inputs required")
    if len({item.id for item in manifest.datasets}) != len(manifest.datasets):
        raise V16Failure(FailureCode.MANIFEST_INVALID, "dataset IDs must be unique")
    return VerifiedManifest(manifest=manifest, manifest_hash=content_hash(payload))
