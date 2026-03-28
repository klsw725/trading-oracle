"""인과 그래프 구축 — 토픽 확장 + 인과 진술 생성 + 트리플 추출

SPEC §5-1:
1. 루트 토픽에서 BFS 3단계 확장 (최대 500 토픽)
2. 각 토픽에서 "X causes Y" 인과 진술 3개 생성
3. 트리플 (subject, relation, object, domain) 추출
4. 체크포인트 저장으로 중단 시 재개 가능
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.causal.graph import CausalGraph
from src.perspectives.base import call_llm, extract_json

CHECKPOINT_PATH = Path("data/causal_checkpoint.json")

ROOT_TOPICS = [
    {"topic": "매크로경제", "domain": "매크로"},
    {"topic": "반도체", "domain": "반도체"},
    {"topic": "자동차", "domain": "자동차"},
    {"topic": "방산", "domain": "방산"},
    {"topic": "금융", "domain": "금융"},
    {"topic": "바이오", "domain": "바이오"},
    {"topic": "에너지", "domain": "에너지"},
    {"topic": "소비재", "domain": "소비재"},
]

EXPAND_SYSTEM = """\
당신은 한국 주식 시장 도메인 전문가입니다. 주어진 토픽에서 관련 하위 토픽을 확장합니다.

## 규칙
- 한국 주식 시장과 직접 관련된 토픽만 생성
- 각 하위 토픽은 독립적이고 구체적
- 중복이나 너무 일반적인 토픽 금지
- 반드시 JSON 형식으로만 응답

## 출력 형식
```json
{"subtopics": ["하위토픽1", "하위토픽2", "하위토픽3", "하위토픽4", "하위토픽5"]}
```
"""

CAUSAL_SYSTEM = """\
당신은 한국 주식 시장의 인과관계 전문가입니다. 주어진 토픽에서 인과 관계 진술을 추출합니다.

## 규칙
- 한국 주식 시장에 직접 적용 가능한 인과관계만
- "X가 Y를 야기한다" 형태의 명확한 인과 진술
- 관계는 increases, decreases, causes, enables, blocks 중 하나
- 반드시 JSON 형식으로만 응답

## 출력 형식
```json
{"triples": [
  {"subject": "원인", "relation": "increases|decreases|causes|enables|blocks", "object": "결과"},
  {"subject": "원인", "relation": "...", "object": "결과"},
  {"subject": "원인", "relation": "...", "object": "결과"}
]}
```
"""


def _save_checkpoint(completed_topics: list[str], all_topics: list[dict], triples: list[dict]):
    """진행 상태 체크포인트 저장."""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps({
        "completed": completed_topics,
        "topics": all_topics,
        "triples": triples,
    }, ensure_ascii=False, indent=2))


def _load_checkpoint() -> dict | None:
    """체크포인트 로드."""
    if not CHECKPOINT_PATH.exists():
        return None
    return json.loads(CHECKPOINT_PATH.read_text())


def expand_topic(topic: str, config: dict) -> list[str]:
    """토픽에서 하위 토픽 5개 확장."""
    prompt = f"토픽: {topic}\n\n이 토픽에서 한국 주식 시장과 관련된 하위 토픽 5개를 생성하세요."
    try:
        text = call_llm(EXPAND_SYSTEM, prompt, config, max_tokens=512)
        parsed = extract_json(text)
        if parsed and "subtopics" in parsed:
            return parsed["subtopics"][:5]
    except Exception:
        pass
    return []


def extract_triples(topic: str, domain: str, config: dict) -> list[dict]:
    """토픽에서 인과 트리플 3개 추출."""
    prompt = f"토픽: {topic}\n도메인: {domain}\n\n이 토픽에서 한국 주식 시장의 인과관계 트리플 3개를 추출하세요."
    try:
        text = call_llm(CAUSAL_SYSTEM, prompt, config, max_tokens=512)
        parsed = extract_json(text)
        if parsed and "triples" in parsed:
            result = []
            for t in parsed["triples"][:3]:
                if "subject" in t and "relation" in t and "object" in t:
                    t["domain"] = domain
                    result.append(t)
            return result
    except Exception:
        pass
    return []


def expand_all_topics(config: dict, max_topics: int = 500, max_depth: int = 3, on_progress=None, roots: list[dict] | None = None) -> list[dict]:
    """BFS로 토픽 확장. 루트 → depth 3, 최대 max_topics개."""
    root_list = roots or ROOT_TOPICS
    all_topics = [{"topic": r["topic"], "domain": r["domain"], "depth": 0} for r in root_list]
    seen = {r["topic"] for r in ROOT_TOPICS}
    queue = list(all_topics)

    while queue and len(all_topics) < max_topics:
        batch = queue[:5]  # 5개씩 병렬 처리
        queue = queue[5:]

        current_depth = batch[0]["depth"] if batch else 0
        if current_depth >= max_depth:
            continue

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(expand_topic, item["topic"], config): item
                for item in batch
            }
            for future in as_completed(futures):
                parent = futures[future]
                subtopics = future.result()
                for st in subtopics:
                    if st not in seen and len(all_topics) < max_topics:
                        seen.add(st)
                        entry = {"topic": st, "domain": parent["domain"], "depth": parent["depth"] + 1}
                        all_topics.append(entry)
                        if entry["depth"] < max_depth:
                            queue.append(entry)

        if on_progress:
            on_progress(len(all_topics), max_topics)

    return all_topics


def build_graph(
    config: dict,
    max_topics: int = 500,
    max_depth: int = 3,
    resume: bool = True,
    on_progress=None,
) -> CausalGraph:
    """전체 파이프라인: 토픽 확장 → 인과 진술 → 트리플 → 그래프.

    resume=True면 체크포인트에서 재개.
    """
    checkpoint = _load_checkpoint() if resume else None

    if checkpoint:
        all_topics = checkpoint["topics"]
        completed = set(checkpoint["completed"])
        all_triples = checkpoint["triples"]
        if on_progress:
            on_progress(len(completed), len(all_topics), phase="resume")
    else:
        if on_progress:
            on_progress(0, max_topics, phase="expand")
        all_topics = expand_all_topics(config, max_topics=max_topics, max_depth=max_depth, on_progress=on_progress)
        completed = set()
        all_triples = []

    # 트리플 추출
    remaining = [t for t in all_topics if t["topic"] not in completed]
    total = len(all_topics)

    for i in range(0, len(remaining), 5):
        batch = remaining[i:i + 5]
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(extract_triples, item["topic"], item["domain"], config): item
                for item in batch
            }
            for future in as_completed(futures):
                item = futures[future]
                triples = future.result()
                all_triples.extend(triples)
                completed.add(item["topic"])

        # 체크포인트 저장 (5개 토픽마다)
        _save_checkpoint(list(completed), all_topics, all_triples)
        if on_progress:
            on_progress(len(completed), total, phase="triples")

    # 그래프 구축
    graph = CausalGraph()
    graph.add_triples(all_triples)
    graph.metadata["created_at"] = checkpoint["topics"][0].get("created_at") if checkpoint else None

    # 체크포인트 삭제
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()

    return graph


def update_graph(
    existing: CausalGraph,
    new_domains: list[dict],
    config: dict,
    on_progress=None,
) -> CausalGraph:
    """기존 그래프에 새 도메인 토픽 추가 (증분 갱신).

    new_domains: [{"topic": "2차전지", "domain": "2차전지"}, ...]
    """
    new_topics = expand_all_topics(
        config,
        max_topics=100,
        max_depth=3,
        on_progress=on_progress,
        roots=new_domains,
    )
    all_triples = []
    for topic_entry in new_topics:
        triples = extract_triples(topic_entry["topic"], topic_entry["domain"], config)
        all_triples.extend(triples)

    existing.add_triples(all_triples)
    return existing
