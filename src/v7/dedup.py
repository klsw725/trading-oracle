import re
from typing import Final
from urllib.parse import urlsplit

from src.v4.models import JsonValue, canonical_hash

from .quality_derived_models import DerivedSourceEvidence

_PUNCTUATION: Final = re.compile(r"[^a-z0-9가-힣\s]")
_WHITESPACE: Final = re.compile(r"\s+")
_TICKER_SUFFIX: Final = re.compile(r"\s+(?:ks|kq|krx|nasdaq|nyse)$")


def canonical_title(value: str) -> str:
    lowered = _PUNCTUATION.sub(" ", value.lower())
    return _TICKER_SUFFIX.sub("", _WHITESPACE.sub(" ", lowered).strip())


def claim_fingerprint(source: DerivedSourceEvidence) -> str:
    identity: JsonValue = {
        "subject_id": source.subject_id,
        "event_date": source.event_date,
        "predicate": source.predicate,
        "object_value": source.object_value,
        "polarity": source.polarity,
        "claim_text": canonical_title(source.claim_text),
    }
    return str(canonical_hash(identity))


def dedup_key(source: DerivedSourceEvidence) -> str:
    identity: JsonValue = {
        "subject_id": source.subject_id,
        "event_date": source.event_date,
        "source_family": source.source_family.lower().strip(),
        "canonical_url_host": (urlsplit(source.canonical_url).hostname or "").lower(),
        "canonical_title": canonical_title(source.canonical_title),
        "claim_fingerprint": claim_fingerprint(source),
    }
    return str(canonical_hash(identity))


def cluster_id(key: str) -> str:
    return f"qcluster_{key.removeprefix('sha256:')[:20]}"
