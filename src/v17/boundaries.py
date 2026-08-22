from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from threading import Lock
from types import ModuleType
from collections.abc import Iterator, Sequence
from typing import Final, override

from .errors import V17Error


@dataclass(frozen=True, slots=True)
class BoundaryCounts:
    network: int
    later_import: int
    broker: int
    live: int
    credential: int


class _Observer(MetaPathFinder):
    @override
    def find_spec(self, fullname: str, path: Sequence[str] | None = None,
                  target: ModuleType | None = None) -> ModuleSpec | None:
        del path, target
        if not _active:
            return None
        lowered = fullname.lower()
        if fullname.startswith(tuple(f"src.v{version}" for version in range(18, 100))):
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
        match kind:  # noqa: MATCH_OK - internal observer kinds are closed here.
            case "network": _network_count += 1
            case "later": _later_count += 1
            case "broker": _broker_count += 1
            case "live": _live_count += 1
            case "credential": _credential_count += 1
            case _: raise V17Error("BOUNDARY_KIND_INVALID", kind)


def _audit(event: str, _args: tuple[str | int | float | bytes | None, ...]) -> None:
    if _active and event in {"socket.connect", "socket.getaddrinfo"}:
        _increment("network")
        raise V17Error("BOUNDARY_NETWORK_BLOCKED", event)


def install_observer() -> None:
    global _installed
    if _installed:
        return
    sys.meta_path.insert(0, _OBSERVER)
    sys.addaudithook(_audit)
    _installed = True


def _reset() -> None:
    global _network_count, _later_count, _broker_count, _live_count, _credential_count
    with _LOCK:
        _network_count = _later_count = _broker_count = 0
        _live_count = _credential_count = 0


@contextmanager
def observe_boundaries() -> Iterator[None]:
    global _active
    _reset()
    _active = True
    try:
        yield
    finally:
        _active = False


def counts() -> BoundaryCounts:
    with _LOCK:
        return BoundaryCounts(_network_count, _later_count, _broker_count,
                              _live_count, _credential_count)
