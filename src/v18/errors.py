from dataclasses import dataclass
from typing import override


@dataclass(frozen=True, slots=True)
class V18Error(Exception):
    code: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class FaultInjected(Exception):
    checkpoint: str

    @override
    def __str__(self) -> str:
        return f"fault injected at {self.checkpoint}"


@dataclass(frozen=True, slots=True)
class InputValueError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail
