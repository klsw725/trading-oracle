from __future__ import annotations

import importlib
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .boundaries import counts, observe_boundaries
from .canonical import content_hash
from .errors import V17Error
from .fixtures import FIXTURE_ROOT, ROOT


@dataclass(frozen=True, slots=True)
class FileState:
    exists: bool
    digest: str


@dataclass(frozen=True, slots=True)
class Baseline:
    portfolio: FileState
    fixtures: tuple[tuple[str, FileState], ...]
    tracked: tuple[tuple[str, FileState], ...]


def _state(path: Path) -> FileState:
    return FileState(path.exists(), content_hash(path.read_bytes()) if path.exists() else "ABSENT")


def capture_baseline() -> Baseline:
    fixture_paths = tuple(FIXTURE_ROOT / name for name in (
        "event-fixtures.json", "inventory.json", "runtime-identities.json"))
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True,
    )
    tracked_paths = tuple(Path(item.decode("utf-8"))
                          for item in completed.stdout.split(b"\0") if item)
    return Baseline(
        portfolio=_state(ROOT / "data/portfolio.json"),
        fixtures=tuple((path.name, _state(path)) for path in fixture_paths),
        tracked=tuple((path.as_posix(), _state(ROOT / path)) for path in tracked_paths),
    )


def verify_baseline(expected: Baseline) -> None:
    if capture_baseline() != expected:
        raise V17Error("ACCEPTANCE_BASELINE_CHANGED", "fixture/portfolio/tracked")


def observer_self_test() -> None:
    with observe_boundaries():
        try:
            _ = socket.getaddrinfo("boundary.invalid", 443)
        except V17Error as error:
            if error.code != "BOUNDARY_NETWORK_BLOCKED":
                raise
        else:
            raise V17Error("BOUNDARY_OBSERVER_INACTIVE", "network")
        try:
            _ = importlib.import_module("src.v18.oracle_probe")
        except ImportError as error:
            later_blocked = str(error)
        else:
            raise V17Error("BOUNDARY_OBSERVER_INACTIVE", "later import")
        if "blocked" not in later_blocked:
            raise V17Error("BOUNDARY_OBSERVER_INACTIVE", later_blocked)
        for module in ("broker_probe", "live_probe", "credential_probe"):
            try:
                _ = importlib.import_module(module)
            except ImportError:
                continue
            raise V17Error("BOUNDARY_OBSERVER_INACTIVE", module)
        observed = counts()
        if observed != type(observed)(1, 1, 1, 1, 1):
            raise V17Error("BOUNDARY_OBSERVER_INACTIVE", str(observed))
