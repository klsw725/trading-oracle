from __future__ import annotations

from datetime import datetime

from .models import MinuteBar, SupersedeEvent, V10ContractError


def revision_head(
    versions: tuple[MinuteBar, ...],
    events: tuple[SupersedeEvent, ...],
    cutoff: datetime,
) -> MinuteBar:
    available = tuple(bar for bar in versions if bar.observed_at <= cutoff)
    if not available:
        raise V10ContractError("V10_REPLAY_LOOKAHEAD", cutoff.isoformat())
    head = min(available, key=lambda bar: bar.revision)
    for event in sorted(events, key=lambda item: item.observed_at):
        if event.observed_at > cutoff:
            continue
        if event.prior.artifact_id != head.meta.artifact_id:
            raise V10ContractError("V10_REVISION_MISMATCH", "broken supersede chain")
        replacement = next(
            (bar for bar in available if bar.meta.artifact_id == event.replacement.artifact_id),
            None,
        )
        if replacement is None:
            raise V10ContractError("V10_REPLAY_LOOKAHEAD", event.observed_at.isoformat())
        head = replacement
    return head
