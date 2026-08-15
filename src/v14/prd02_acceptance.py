from __future__ import annotations

import json

from .prd02_contract import run_acceptance


def main() -> int:
    report = run_acceptance()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["state"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
