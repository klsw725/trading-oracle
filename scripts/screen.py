#!/usr/bin/env python3
"""주도주 스크리닝 — 시총 상위 모멘텀 + 밸류에이션 필터링

사용법:
    uv run scripts/screen.py                         # 터미널 출력
    uv run scripts/screen.py --json                  # JSON 출력
    uv run scripts/screen.py --top 10                # 상위 N개
"""

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import load_config, json_dump, run_screening


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 주도주 스크리닝")
    parser.add_argument("--top", type=int, help="상위 N개 (기본: max_positions × 2)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    config = load_config()
    candidates = run_screening(config)

    if args.top:
        candidates = candidates[:args.top]

    if not candidates:
        if args.json:
            print(json_dump({"status": "error", "message": "스크리닝 결과 없음"}))
        else:
            print("스크리닝 결과 없음", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json_dump({"candidates": candidates}))
    else:
        from src.output.formatter import console
        console.print(f"\n[bold]주도주 스크리닝 결과 ({len(candidates)}개):[/bold]\n")
        for i, c in enumerate(candidates, 1):
            score_bar = "█" * int(c["score"]) + "░" * (15 - int(c["score"]))
            console.print(
                f"  {i:2d}. {c['name']:12s} ({c['ticker']}) "
                f"점수:{c['score']:5.1f} [{score_bar}] "
                f"PER:{c['per']:6.1f} PBR:{c['pbr']:5.2f} "
                f"5일:{c['ret_5d']:+6.1f}%% 20일:{c['ret_20d']:+6.1f}%%"
            )


if __name__ == "__main__":
    main()
