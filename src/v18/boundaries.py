from __future__ import annotations

import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from pathlib import Path
from threading import Lock
from types import ModuleType
from collections.abc import Iterator, Sequence
from typing import Final, override

from .canonical import JsonValue, canonical_hash, content_hash, parse_json
from .errors import V18Error


@dataclass(frozen=True, slots=True)
class BoundaryCounts:
    network: int
    later_import: int
    broker: int
    live: int
    credential: int


class _Observer(MetaPathFinder):
    @override
    def find_spec(
        self, fullname: str, path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        del path, target
        if not _active:
            return None
        lowered = fullname.lower()
        version = fullname.removeprefix("src.v").split(".", maxsplit=1)[0]
        if fullname.startswith("src.v") and version.isdigit() and int(version) >= 19:
            _increment("later")
            raise ImportError(f"later version import blocked: {fullname}")
        if "broker" in lowered:
            _increment("broker")
            raise ImportError(f"broker import blocked: {fullname}")
        if "credential" in lowered:
            _increment("credential")
            raise ImportError(f"credential import blocked: {fullname}")
        if ".live" in lowered or lowered.startswith("live"):
            _increment("live")
            raise ImportError(f"live import blocked: {fullname}")
        return None


_LOCK: Final = Lock()
_OBSERVER: Final = _Observer()
_installed = False
_active = False
_network_count = 0
_later_count = 0
_broker_count = 0
_live_count = 0
_credential_count = 0


def _increment(kind: str) -> None:
    global _network_count, _later_count, _broker_count, _live_count, _credential_count
    with _LOCK:
        match kind:  # noqa: MATCH_OK - observer kinds are closed here.
            case "network":
                _network_count += 1
            case "later":
                _later_count += 1
            case "broker":
                _broker_count += 1
            case "live":
                _live_count += 1
            case "credential":
                _credential_count += 1
            case _:
                raise V18Error("BOUNDARY_KIND_INVALID", kind)


def _audit(event: str, _arguments: tuple[str | int | float | bytes | None, ...]) -> None:
    if _active and event.startswith("socket."):
        _increment("network")
        raise V18Error("BOUNDARY_NETWORK_BLOCKED", event)


def install_observer() -> None:
    global _installed
    if not _installed:
        sys.meta_path.insert(0, _OBSERVER)
        sys.addaudithook(_audit)
        _installed = True


@contextmanager
def observe_boundaries() -> Iterator[None]:
    global _active, _network_count, _later_count, _broker_count, _live_count, _credential_count
    with _LOCK:
        _network_count = _later_count = _broker_count = 0
        _live_count = _credential_count = 0
    _active = True
    try:
        yield
    finally:
        _active = False


def counts() -> BoundaryCounts:
    with _LOCK:
        return BoundaryCounts(
            _network_count, _later_count, _broker_count, _live_count, _credential_count
        )


def later_source_imports(root: Path) -> tuple[str, ...]:
    pattern = re.compile(r"(?:from|import)[ \t]+src[.]v([0-9]+)")
    result: list[str] = []
    for path in sorted((root / "src/v18").glob("*.py")):
        if any(int(match.group(1)) >= 19 for match in pattern.finditer(path.read_text())):
            result.append(path.name)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    exists: bool
    digest: str


def snapshot(path: Path) -> FileSnapshot:
    return FileSnapshot(path.is_file(), content_hash(path.read_bytes() if path.is_file() else b""))


def tracked_snapshot(root: Path) -> str:
    try:
        payload = subprocess.run(
            ("git", "ls-files", "-z"), cwd=root, check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise V18Error("TRACKED_SNAPSHOT_UNAVAILABLE", str(root)) from error
    records: list[JsonValue] = []
    for relative in sorted(item for item in payload.decode("utf-8").split("\0") if item):
        path = root / relative
        records.append(
            {
                "exists": path.is_file(),
                "hash": content_hash(path.read_bytes()) if path.is_file() else "missing",
                "path": relative,
            }
        )
    return canonical_hash(records)


def fresh_boundary_counts(root: Path) -> BoundaryCounts:
    try:
        completed = subprocess.run(
            (sys.executable, "-m", "src.v18.boundary_probe"),
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise V18Error("BOUNDARY_PROBE_FAILED", str(root)) from error
    payload = parse_json(completed.stdout)
    if not isinstance(payload, dict):
        raise V18Error("BOUNDARY_PROBE_FAILED", "invalid payload")
    values: list[int] = []
    for key in ("network", "later_import", "broker", "live", "credential"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise V18Error("BOUNDARY_PROBE_FAILED", key)
        values.append(value)
    return BoundaryCounts(*values)
