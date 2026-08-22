from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .errors import FaultInjected

type FaultPoint = Literal[
    "after_event_insert",
    "after_idempotency_insert",
    "after_projection_write",
    "after_checkpoint",
]


@dataclass(frozen=True, slots=True)
class FaultPlan:
    point: FaultPoint

    def hit(self, point: FaultPoint) -> None:
        if self.point == point:
            raise FaultInjected(point)


class FaultInjector(Protocol):
    def hit(self, point: FaultPoint) -> None: ...


def hit(plan: FaultInjector | None, point: FaultPoint) -> None:
    if plan is not None:
        plan.hit(point)
