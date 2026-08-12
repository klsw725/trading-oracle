from __future__ import annotations

from src.v4.models import JsonValue

from .canonical import artifact_ref, seal_meta
from .models import MinuteBar, SupersedeEvent, V10ContractError


def supersede(prior: MinuteBar, replacement: MinuteBar) -> SupersedeEvent | None:
    if prior.symbol != replacement.symbol or prior.interval_start != replacement.interval_start:
        raise V10ContractError("V10_REVISION_MISMATCH", replacement.symbol)
    if replacement.revision == prior.revision:
        if replacement.meta.content_hash == prior.meta.content_hash:
            return None
        raise V10ContractError("V10_REVISION_MISMATCH", "revision reused with new content")
    if replacement.revision <= prior.revision or replacement.observed_at <= prior.observed_at:
        raise V10ContractError("V10_REVISION_MISMATCH", "non-monotonic revision")
    prior_ref = artifact_ref("prior", prior)
    replacement_ref = artifact_ref("replacement", replacement)
    body: JsonValue = {
        "prior": prior_ref.model_dump(mode="json"),
        "replacement": replacement_ref.model_dump(mode="json"),
        "reason": "late_source_revision",
        "observed_at": replacement.observed_at.isoformat(),
    }
    return SupersedeEvent(
        meta=seal_meta("supersede_event", body),
        prior=prior_ref,
        replacement=replacement_ref,
        reason="late_source_revision",
        observed_at=replacement.observed_at,
    )
