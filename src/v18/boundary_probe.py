import importlib
import sys

from .boundaries import counts, install_observer, observe_boundaries
from .canonical import JsonValue, canonical_json


def main() -> int:
    install_observer()
    with observe_boundaries():
        _ = importlib.import_module("src.v18.cli")
        observed = counts()
    payload: JsonValue = {
        "broker": observed.broker,
        "credential": observed.credential,
        "later_import": observed.later_import,
        "live": observed.live,
        "network": observed.network,
    }
    _ = sys.stdout.buffer.write(canonical_json(payload) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
