"""인과 그래프 — networkx DiGraph 래퍼, JSON 직렬화

SPEC §5-2 저장 형식:
{
  "metadata": {"created_at": "...", "num_topics": N, "num_triples": N, "llm_model": "..."},
  "triples": [{"subject": "...", "relation": "...", "object": "...", "domain": "..."}, ...]
}
"""

import json
from datetime import datetime
from pathlib import Path

import networkx as nx

CAUSAL_GRAPH_PATH = Path("data/causal_graph.json")


class CausalGraph:
    """인과 그래프 — networkx DiGraph 기반"""

    def __init__(self):
        self.graph = nx.DiGraph()
        self.triples: list[dict] = []
        self.metadata: dict = {}

    def add_triple(self, subject: str, relation: str, obj: str, domain: str = ""):
        """인과 트리플 추가."""
        triple = {"subject": subject, "relation": relation, "object": obj, "domain": domain}
        self.triples.append(triple)
        self.graph.add_edge(subject, obj, relation=relation, domain=domain)
        # 노드에 도메인 태깅
        if domain:
            self.graph.nodes[subject].setdefault("domains", set()).add(domain)
            self.graph.nodes[obj].setdefault("domains", set()).add(domain)

    def add_triples(self, triples: list[dict]):
        """여러 트리플 일괄 추가."""
        for t in triples:
            self.add_triple(t["subject"], t["relation"], t["object"], t.get("domain", ""))

    def find_paths(self, source: str, target: str, max_depth: int = 5) -> list[list[str]]:
        """두 노드 사이의 모든 경로 탐색."""
        if source not in self.graph or target not in self.graph:
            return []
        try:
            return list(nx.all_simple_paths(self.graph, source, target, cutoff=max_depth))
        except nx.NetworkXError:
            return []

    def find_causes(self, node: str, depth: int = 2) -> list[dict]:
        """특정 노드의 원인 체인 (역방향 탐색)."""
        if node not in self.graph:
            return []
        causes = []
        visited = set()
        queue = [(node, 0)]
        while queue:
            current, d = queue.pop(0)
            if d > depth:
                break
            for pred in self.graph.predecessors(current):
                if pred not in visited:
                    visited.add(pred)
                    edge = self.graph.edges[pred, current]
                    causes.append({
                        "subject": pred,
                        "relation": edge.get("relation", ""),
                        "object": current,
                        "domain": edge.get("domain", ""),
                        "depth": d + 1,
                    })
                    queue.append((pred, d + 1))
        return causes

    def find_effects(self, node: str, depth: int = 2) -> list[dict]:
        """특정 노드의 결과 체인 (순방향 탐색)."""
        if node not in self.graph:
            return []
        effects = []
        visited = set()
        queue = [(node, 0)]
        while queue:
            current, d = queue.pop(0)
            if d > depth:
                break
            for succ in self.graph.successors(current):
                if succ not in visited:
                    visited.add(succ)
                    edge = self.graph.edges[current, succ]
                    effects.append({
                        "subject": current,
                        "relation": edge.get("relation", ""),
                        "object": succ,
                        "domain": edge.get("domain", ""),
                        "depth": d + 1,
                    })
                    queue.append((succ, d + 1))
        return effects

    def search_nodes(self, keyword: str) -> list[str]:
        """키워드로 노드 검색."""
        keyword_lower = keyword.lower()
        return [n for n in self.graph.nodes if keyword_lower in n.lower()]

    def filter_by_domain(self, domain: str) -> list[dict]:
        """특정 도메인의 트리플만 반환."""
        return [t for t in self.triples if t.get("domain", "") == domain]

    def get_related_chains(self, keywords: list[str], depth: int = 2) -> list[dict]:
        """키워드 관련 인과 체인 조회. 매크로 관점에서 사용."""
        chains = []
        for kw in keywords:
            nodes = self.search_nodes(kw)
            for node in nodes[:3]:  # 키워드당 최대 3개 노드
                causes = self.find_causes(node, depth=depth)
                effects = self.find_effects(node, depth=depth)
                if causes or effects:
                    chains.append({
                        "keyword": kw,
                        "node": node,
                        "causes": causes[:5],
                        "effects": effects[:5],
                    })
        return chains

    def save(self, path: Path | None = None, llm_model: str = ""):
        """JSON으로 저장. SPEC §5-2 형식."""
        path = path or CAUSAL_GRAPH_PATH
        topics = set()
        for t in self.triples:
            topics.add(t["subject"])
            topics.add(t["object"])

        data = {
            "metadata": {
                "created_at": self.metadata.get("created_at", datetime.now().strftime("%Y-%m-%d")),
                "updated_at": datetime.now().strftime("%Y-%m-%d"),
                "num_topics": len(topics),
                "num_triples": len(self.triples),
                "llm_model": llm_model or self.metadata.get("llm_model", ""),
            },
            "triples": self.triples,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Path | None = None) -> "CausalGraph":
        """JSON에서 로드."""
        path = path or CAUSAL_GRAPH_PATH
        if not path.exists():
            return cls()

        data = json.loads(path.read_text())
        graph = cls()
        graph.metadata = data.get("metadata", {})
        graph.add_triples(data.get("triples", []))
        return graph

    @classmethod
    def load_if_exists(cls, path: Path | None = None) -> "CausalGraph | None":
        """그래프 파일이 있으면 로드, 없으면 None."""
        path = path or CAUSAL_GRAPH_PATH
        if not path.exists():
            return None
        return cls.load(path)

    @property
    def num_nodes(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def num_edges(self) -> int:
        return self.graph.number_of_edges()

    def __repr__(self) -> str:
        return f"CausalGraph(nodes={self.num_nodes}, edges={self.num_edges}, triples={len(self.triples)})"
