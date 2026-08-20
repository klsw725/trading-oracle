from __future__ import annotations

from typing import final, override


@final
class V17Error(Exception):
    __slots__: tuple[str, ...] = ("code", "detail")
    code: str
    detail: str

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail)
        self.code = code
        self.detail = detail

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@final
class FaultInjected(Exception):
    __slots__: tuple[str, ...] = ("checkpoint",)
    checkpoint: str

    def __init__(self, checkpoint: str) -> None:
        super().__init__(checkpoint)
        self.checkpoint = checkpoint

    @override
    def __str__(self) -> str:
        return f"fault injected at {self.checkpoint}"
