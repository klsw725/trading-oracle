"""다관점 병렬 호출 — 5개 관점 동시 실행, 부분 실패 허용

SPEC §4-2: asyncio/ThreadPool 병렬, 파싱 실패 1회 재시도 (각 관점 내부),
전체 실패 시 N/A 처리.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from src.perspectives.base import PerspectiveInput, PerspectiveResult, Perspective, make_na_result
from src.perspectives.kwangsoo import KwangsooPerspective
from src.perspectives.ouroboros import OuroborosPerspective
from src.perspectives.quant_perspective import QuantPerspective
from src.perspectives.macro import MacroPerspective
from src.perspectives.value import ValuePerspective


ALL_PERSPECTIVES: list[Perspective] = [
    KwangsooPerspective(),
    OuroborosPerspective(),
    QuantPerspective(),
    MacroPerspective(),
    ValuePerspective(),
]


def run_all_perspectives(data: PerspectiveInput, max_workers: int = 5) -> list[PerspectiveResult]:
    """5개 관점을 병렬 실행하고 결과를 수집한다.

    부분 실패 허용 — 실패한 관점은 N/A로 처리.
    반환 순서: kwangsoo, ouroboros, quant, macro, value (고정).
    """
    results: dict[str, PerspectiveResult] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(_safe_analyze, perspective, data): perspective.name
            for perspective in ALL_PERSPECTIVES
        }

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = make_na_result(name, f"예외 발생: {e}")

    # 고정 순서로 반환
    order = ["kwangsoo", "ouroboros", "quant", "macro", "value"]
    return [results.get(name, make_na_result(name, "결과 누락")) for name in order]


def _safe_analyze(perspective: Perspective, data: PerspectiveInput) -> PerspectiveResult:
    """관점 분석 실행. 예외 발생 시 N/A 반환."""
    try:
        return perspective.analyze(data)
    except Exception as e:
        return make_na_result(perspective.name, f"분석 실패: {e}")
