#!/usr/bin/env python3
"""인과 그래프 구축 — DEMOCRITUS-lite

사용법:
    uv run scripts/build_causal.py                   # 전체 구축 (기본 500 토픽)
    uv run scripts/build_causal.py --max-topics 50   # 소규모 테스트
    uv run scripts/build_causal.py --update 2차전지   # 기존 그래프에 도메인 추가
    uv run scripts/build_causal.py --json            # JSON 출력
    uv run scripts/build_causal.py --info             # 기존 그래프 정보 조회
"""

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common import load_config, json_dump


def cmd_build(args):
    from src.causal.builder import build_graph
    from src.causal.graph import CausalGraph

    config = load_config()
    max_topics = args.max_topics
    llm_config = config.get("llm", {})
    model = llm_config.get("model", "unknown")
    provider = llm_config.get("provider", "anthropic")

    if not args.json:
        print(f"인과 그래프 구축 시작 (최대 {max_topics} 토픽, provider: {provider}, model: {model})")
        print(f"예상 비용: ~${max_topics * 0.01:.2f} (LLM 호출 ~{max_topics * 2}회)")
        print()

    def on_progress(current, total, phase=""):
        if not args.json:
            label = {"expand": "토픽 확장", "triples": "트리플 추출", "resume": "체크포인트 재개"}.get(phase, "진행")
            print(f"\r  [{label}] {current}/{total}", end="", flush=True)

    graph = build_graph(
        config,
        max_topics=max_topics,
        max_depth=args.max_depth,
        resume=not args.fresh,
        on_progress=on_progress,
    )

    graph.save(llm_model=f"{provider}/{model}")

    if not args.json:
        print()
        print()
        print(f"구축 완료: {graph.num_nodes}개 노드, {graph.num_edges}개 엣지, {len(graph.triples)}개 트리플")
        print(f"저장: data/causal_graph.json")
    else:
        print(json_dump({
            "status": "ok",
            "nodes": graph.num_nodes,
            "edges": graph.num_edges,
            "triples": len(graph.triples),
        }))


def cmd_update(args):
    from src.causal.builder import update_graph
    from src.causal.graph import CausalGraph

    config = load_config()
    existing = CausalGraph.load()

    new_domains = [{"topic": d, "domain": d} for d in args.domains]

    if not args.json:
        print(f"기존 그래프: {existing.num_nodes}개 노드, {len(existing.triples)}개 트리플")
        print(f"추가 도메인: {', '.join(args.domains)}")

    graph = update_graph(existing, new_domains, config)
    graph.save()

    if not args.json:
        print(f"갱신 완료: {graph.num_nodes}개 노드, {len(graph.triples)}개 트리플")
    else:
        print(json_dump({
            "status": "ok",
            "nodes": graph.num_nodes,
            "edges": graph.num_edges,
            "triples": len(graph.triples),
        }))


def cmd_info(args):
    from src.causal.graph import CausalGraph

    graph = CausalGraph.load_if_exists()
    if not graph:
        if args.json:
            print(json_dump({"status": "error", "message": "인과 그래프 없음"}))
        else:
            print("인과 그래프가 아직 생성되지 않았습니다.")
            print("  uv run scripts/build_causal.py 로 구축하세요.")
        return

    domains = {}
    for t in graph.triples:
        d = t.get("domain", "기타")
        domains[d] = domains.get(d, 0) + 1

    if args.json:
        print(json_dump({
            "metadata": graph.metadata,
            "nodes": graph.num_nodes,
            "edges": graph.num_edges,
            "triples": len(graph.triples),
            "domains": domains,
        }))
    else:
        m = graph.metadata
        print(f"인과 그래프 정보:")
        print(f"  생성일: {m.get('created_at', 'N/A')}")
        print(f"  갱신일: {m.get('updated_at', 'N/A')}")
        print(f"  모델: {m.get('llm_model', 'N/A')}")
        print(f"  노드: {graph.num_nodes}개")
        print(f"  엣지: {graph.num_edges}개")
        print(f"  트리플: {len(graph.triples)}개")
        print(f"\n  도메인별 트리플:")
        for d, count in sorted(domains.items(), key=lambda x: -x[1]):
            print(f"    {d}: {count}개")


def main():
    parser = argparse.ArgumentParser(description="Trading Oracle — 인과 그래프 구축")
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    sub = parser.add_subparsers(dest="command")

    # build (기본)
    build_p = sub.add_parser("build", help="인과 그래프 전체 구축")
    build_p.add_argument("--max-topics", type=int, default=500, help="최대 토픽 수 (기본: 500)")
    build_p.add_argument("--max-depth", type=int, default=3, help="BFS 깊이 (기본: 3)")
    build_p.add_argument("--fresh", action="store_true", help="체크포인트 무시하고 처음부터")
    build_p.add_argument("--json", action="store_true", help="JSON 출력")

    # update
    update_p = sub.add_parser("update", help="기존 그래프에 도메인 추가")
    update_p.add_argument("domains", nargs="+", help="추가할 도메인 (예: 2차전지 AI)")
    update_p.add_argument("--json", action="store_true", help="JSON 출력")

    # info
    info_p = sub.add_parser("info", help="기존 그래프 정보 조회")
    info_p.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args()

    if args.command == "update":
        cmd_update(args)
    elif args.command == "info":
        cmd_info(args)
    else:
        # 기본 = build
        if not hasattr(args, "max_topics"):
            args.max_topics = 500
            args.max_depth = 3
            args.fresh = False
        cmd_build(args)


if __name__ == "__main__":
    main()
