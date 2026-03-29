#!/usr/bin/env python3
"""인과 그래프 Granger 검증 — Phase 12

사용법:
    uv run scripts/verify_causal.py                   # 검증 실행
    uv run scripts/verify_causal.py --json             # JSON 출력
    uv run scripts/verify_causal.py --detail           # 검증된 트리플 상세
    uv run scripts/verify_causal.py --info             # 기존 검증 결과 조회
"""

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import json_dump


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 인과 그래프 Granger 검증")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument("--detail", action="store_true", help="검증된 트리플 상세")
    parser.add_argument("--info", action="store_true", help="기존 검증 결과 조회")
    args = parser.parse_args()

    if args.info:
        from src.causal.verifier import load_verified_graph
        data = load_verified_graph()
        if not data:
            print("검증 결과 없음. `uv run scripts/verify_causal.py`로 검증 실행하세요.")
            return
        meta = data["metadata"]
        if args.json:
            print(json_dump(meta))
        else:
            print(f"\n인과 그래프 검증 결과:")
            print(f"  전체 트리플: {meta['total_triples']}")
            print(f"  매핑 가능: {meta['mappable']}")
            print(f"  검증 통과: {meta['verified']}")
            print(f"  검증 실패: {meta['failed']}")
            print(f"  매핑 불가: {meta['unmappable']}")
            print(f"  검증일: {meta.get('verified_at', 'N/A')[:10]}")
        return

    # 검증 실행
    from src.causal.verifier import verify_causal_graph

    if not args.json:
        print("인과 그래프 Granger 검증 시작...")

    def on_progress(current, total):
        if not args.json:
            print(f"\r  [{current}/{total}] 검증 중...", end="", flush=True)

    result = verify_causal_graph(on_progress=on_progress)
    meta = result["metadata"]

    if not args.json:
        print()
        print()
        print(f"검증 완료:")
        print(f"  전체: {meta['total_triples']} / 매핑: {meta['mappable']} / 검증 통과: {meta['verified']} / 실패: {meta['failed']}")
        print(f"  Bonferroni α: {meta['corrected_alpha']:.6f}")

    if args.detail or args.json:
        verified = result.get("verified_triples", [])
        if args.json:
            print(json_dump({"metadata": meta, "verified": verified}))
        else:
            print(f"\n검증된 트리플 ({len(verified)}개):")
            for t in sorted(verified, key=lambda x: x["verification"]["confidence"], reverse=True):
                v = t["verification"]
                print(f"  [{v['confidence']:.2f}] {t['subject']} → {t['object']}")
                print(f"         p={v['p_value']:.6f}, lag={v['lag']}일, pair={v['series_pair']}")
    elif not args.json:
        print(json_dump(meta))


if __name__ == "__main__":
    main()
