from collections.abc import Callable
from hashlib import sha256
import re
import unicodedata
from typing import Final

from src.causal.canonical_models import DirectionKind, NodeDirection, Polarity
from src.v4.models import JsonValue, canonical_json


_FORMATTING = re.compile(r"[/·_]+")
_WHITESPACE = re.compile(r"\s+")
_EXCHANGE_ALIASES: Final = {
    "원달러 환율 상승": "원달러 환율 상승",
    "usdkrw 상승": "원달러 환율 상승",
    "달러 대비 원화 약세": "원달러 환율 상승",
    "원화 약세": "원달러 환율 상승",
}
_GENERIC_OWNERS: Final = frozenset({"가격", "마진", "매출", "비용", "수요", "공급", "투자"})
type DirectionResolver = Callable[[str], NodeDirection]


def canonical_node_id_value(
    canonical_label: str,
    normalized_label: str,
    direction: tuple[str, str],
) -> str:
    direction_kind, direction_polarity = direction
    seed: JsonValue = {
        "schema_version": "causal-node-canonicalization.1",
        "canonical_label": canonical_label,
        "normalized_label": normalized_label,
        "direction": {
            "kind": direction_kind,
            "polarity": direction_polarity,
        },
    }
    return f"cnode_{sha256(canonical_json(seed)).hexdigest()[:20]}"


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    normalized = _FORMATTING.sub("", normalized)
    normalized = _WHITESPACE.sub(" ", normalized)
    return _EXCHANGE_ALIASES.get(normalized.casefold(), normalized)


def infer_direction(text: str) -> NodeDirection:
    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    if "원화 강세" in normalized:
        return NodeDirection(DirectionKind.LEVEL_CHANGE, Polarity.DOWN)
    if any(term in normalized for term in ("원달러", "usd/krw", "usdkrw", "원화 약세")):
        if "하락" in normalized or "감소" in normalized or "축소" in normalized:
            polarity = Polarity.DOWN
        elif (
            "상승" in normalized
            or "증가" in normalized
            or "확대" in normalized
            or "원화 약세" in normalized
        ):
            polarity = Polarity.UP
        else:
            polarity = Polarity.UNKNOWN
        return NodeDirection(DirectionKind.LEVEL_CHANGE, polarity)
    if any(term in normalized for term in ("증가", "감소")):
        polarity = Polarity.DOWN if "감소" in normalized else Polarity.UP
        return NodeDirection(DirectionKind.FLOW_CHANGE, polarity)
    if any(term in normalized for term in ("개선", "악화", "완화", "긴축")):
        polarity = Polarity.DOWN if "악화" in normalized or "긴축" in normalized else Polarity.UP
        return NodeDirection(DirectionKind.STATE, polarity)
    if any(term in normalized for term in ("갈등", "전쟁", "규제")):
        return NodeDirection(DirectionKind.EVENT, Polarity.NEUTRAL)
    if "상승" in normalized or "확대" in normalized:
        return NodeDirection(DirectionKind.LEVEL_CHANGE, Polarity.UP)
    if "하락" in normalized or "축소" in normalized:
        return NodeDirection(DirectionKind.LEVEL_CHANGE, Polarity.DOWN)
    return NodeDirection(DirectionKind.UNKNOWN, Polarity.UNKNOWN)


def direction_conflict_reason(text: str, direction: NodeDirection) -> str | None:
    inferred = infer_direction(text)
    if inferred.polarity is Polarity.UNKNOWN:
        return None
    if inferred.polarity is not direction.polarity:
        return "misleading_direction"
    return None


def concept_key(label: str) -> str:
    if "원달러" in label or "원화 강세" in label:
        return "원달러 환율"
    return re.sub(r"(상승|하락|증가|감소|개선|악화|확대|축소)$", "", label).strip()


def requires_owner_review(label: str) -> bool:
    words = label.split()
    return len(words) <= 2 and bool(words) and words[0] in _GENERIC_OWNERS
