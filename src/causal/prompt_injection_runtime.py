from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from src.v4.models import JsonValue, canonical_hash

from .prompt_injection_models import (
    PROMPT_PACKAGE_ADAPTER,
    VERIFICATION_ARTIFACT_ADAPTER,
    VerifiedPromptRecord,
)


PROMPT_PACKAGE_PATH: Final = (
    Path(__file__).resolve().parents[2] / "data" / "causal_prompt_injection.json"
)
VERIFICATION_ARTIFACT_PATH: Final = (
    Path(__file__).resolve().parents[2] / "data" / "causal_statistical_verification.json"
)
_JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter[JsonValue](JsonValue)


def load_verified_prompt_records(
    keywords: list[str],
    package_path: Path = PROMPT_PACKAGE_PATH,
    as_of: str | None = None,
    source_path: Path = VERIFICATION_ARTIFACT_PATH,
) -> tuple[VerifiedPromptRecord, ...]:
    if not package_path.exists() or not source_path.exists():
        return ()
    try:
        package = PROMPT_PACKAGE_ADAPTER.validate_json(package_path.read_bytes())
        source_value = _JSON.validate_json(source_path.read_bytes())
        _ = VERIFICATION_ARTIFACT_ADAPTER.validate_python(source_value)
        cutoff = datetime.fromisoformat(as_of) if as_of is not None else datetime.now().astimezone()
    except (OSError, ValidationError, ValueError):
        return ()
    if package.source_artifact_hash != canonical_hash(source_value):
        return ()
    if cutoff.tzinfo is None:
        return ()
    if cutoff < package.prompt_cutoff or package.expires_at <= cutoff:
        return ()
    lowered = tuple(
        keyword.strip().lower() for keyword in keywords if keyword.strip()
    )
    if not lowered:
        return ()
    selected: list[VerifiedPromptRecord] = []
    for record in package.verified_prompt_records:
        if (
            record.freshness.verification_expires_at <= cutoff
            or record.freshness.mapping_expires_at <= cutoff
        ):
            continue
        searchable = f"{record.subject_label} {record.object_label}".lower()
        if any(keyword in searchable for keyword in lowered):
            selected.append(record)
    return tuple(selected)
