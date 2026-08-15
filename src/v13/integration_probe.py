from __future__ import annotations

from collections.abc import Callable
from typing import Literal, NotRequired, TypedDict


MODEL_ID = "gpt-5.1-codex"
TIMEOUT_SECONDS = 20

type ModelProbe = Callable[[str, int], str]


class IntegrationProbeReport(TypedDict):
    state: Literal["disabled", "pass", "fail"]
    explicit_opt_in: bool
    provider_call_count: int
    model_id: str
    timeout_seconds: int
    retry_count: int
    tools_enabled: bool
    error_code: NotRequired[str]


def run_integration_probe(
    explicit_opt_in: bool,
    probe: ModelProbe | None = None,
) -> IntegrationProbeReport:
    report = IntegrationProbeReport(
        state="disabled",
        explicit_opt_in=explicit_opt_in,
        provider_call_count=0,
        model_id=MODEL_ID,
        timeout_seconds=TIMEOUT_SECONDS,
        retry_count=0,
        tools_enabled=False,
    )
    if not explicit_opt_in:
        return report

    if probe is None:
        from src.agent.codex import probe_model

        probe = probe_model

    try:
        response = probe(MODEL_ID, TIMEOUT_SECONDS)
    except RuntimeError:
        report["state"] = "fail"
        report["provider_call_count"] = 1
        report["error_code"] = "codex_integration_failed"
        return report

    report["provider_call_count"] = 1
    if not response.strip():
        report["state"] = "fail"
        report["error_code"] = "codex_empty_response"
        return report
    report["state"] = "pass"
    return report
