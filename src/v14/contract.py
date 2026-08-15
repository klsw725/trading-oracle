from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, override

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="forbid", strict=True
    )


@dataclass(frozen=True, slots=True)
class V14ContractError(Exception):
    code: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"
