from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from types import TracebackType
from typing import Self, final

from .canonical import JsonValue, canonical_hash, content_hash
from .errors import FailureCode, V16Failure
from .paths import fixture_file
from .registries import FORBIDDEN_INPUT_TOKENS


type AuditArgument = str | int | float | bytes | None | tuple["AuditArgument", ...]


@final
class BoundaryObserver:
    __slots__: tuple[str, ...] = ("active", "network_attempts", "later_imports")
    active: bool
    network_attempts: int
    later_imports: int

    def __init__(self, network_attempts: int = 0, later_imports: int = 0) -> None:
        self.active = True
        self.network_attempts = network_attempts
        self.later_imports = later_imports

    def audit(self, event: str, arguments: tuple[AuditArgument, ...]) -> None:
        if not self.active:
            return
        if event.startswith("socket."):
            self.network_attempts += 1
            raise V16Failure(FailureCode.INVALID, "network access blocked")
        if event == "import" and arguments and isinstance(arguments[0], str):
            name = arguments[0]
            version = name.removeprefix("src.v").split(".", maxsplit=1)[0]
            if name.startswith("src.v") and version.isdigit() and int(version) >= 17:
                self.later_imports += 1
                raise V16Failure(FailureCode.INVALID, "later version import blocked")

    def disable(self) -> None:
        self.active = False

    def __enter__(self) -> Self:
        sys.addaudithook(self.audit)
        return self

    def __exit__(self, exception_type: type[BaseException] | None,
                 exception: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.disable()


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    exists: bool
    digest: str

    def stable(self) -> str:
        return f"{int(self.exists)}:{self.digest}"


@dataclass(frozen=True, slots=True)
class WorktreeSnapshot:
    digest: str


def snapshot(path: Path) -> FileSnapshot:
    if not path.exists():
        return FileSnapshot(False, content_hash(b""))
    return FileSnapshot(True, content_hash(path.read_bytes()))


def _later_module(name: str) -> bool:
    version = name.removeprefix("src.v").split(".", maxsplit=1)[0]
    return name.startswith("src.v") and version.isdigit() and int(version) >= 17


def source_later_imports(root: Path) -> tuple[str, ...]:
    pattern = re.compile(r"(?:from|import)[ \t]+src[.]v([0-9]+)")
    findings: list[str] = []
    for path in sorted((root / "src/v16").glob("*.py")):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            if int(match.group(1)) >= 17:
                findings.append(path.name)
    return tuple(findings)


def observe_boundaries(root: Path, network_attempts: int = 0,
                       later_imports: int = 0) -> BoundaryObserver:
    preloaded = sum(_later_module(name) for name in sys.modules)
    observer = BoundaryObserver(network_attempts,
        later_imports + preloaded + len(source_later_imports(root)))
    sys.addaudithook(observer.audit)
    return observer


def worktree_snapshot(root: Path) -> WorktreeSnapshot:
    try:
        payload = subprocess.run(("git", "ls-files", "-z"), cwd=root, check=True,
                                 capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise V16Failure(FailureCode.INVALID, "tracked snapshot unavailable") from error
    records: list[JsonValue] = []
    for relative in sorted(item for item in payload.decode("utf-8").split("\0") if item):
        path = root / relative
        records.append({"exists": path.is_file(), "hash": content_hash(path.read_bytes())
                        if path.is_file() else "missing", "path": relative})
    return WorktreeSnapshot(canonical_hash(records))


def forbidden_inputs(root: Path, relative_paths: tuple[str, ...]) -> tuple[str, ...]:
    found: set[str] = set()
    for relative in relative_paths:
        text = fixture_file(root, relative).read_text(encoding="utf-8").casefold()
        found.update(token for token in FORBIDDEN_INPUT_TOKENS if token in text)
    return tuple(sorted(found))
