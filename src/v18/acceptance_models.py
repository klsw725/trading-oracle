from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProbeResult:
    id: str
    status: str
    expected: str


def passed(identifier: str, expected: str) -> ProbeResult:
    return ProbeResult(identifier, "PASS", expected)
