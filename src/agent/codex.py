"""OpenAI Codex (Responses API) provider — OAuth 기반 텍스트 생성"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx

from oauth_cli_kit import get_token, login_oauth_interactive, OPENAI_CODEX_PROVIDER  # pyright: ignore[reportMissingTypeStubs]
from oauth_cli_kit.storage import FileTokenStorage  # pyright: ignore[reportMissingTypeStubs]

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
_DATA_DIR = Path.home() / ".trading-oracle"
_SHACS_DATA_DIR = Path.home() / ".shacs-bot"

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


class CodexError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _GenerationRequest:
    system_prompt: str
    user_prompt: str
    model: str
    timeout_seconds: float


def _get_storage() -> FileTokenStorage:
    """토큰 스토리지 반환. shacs-bot 토큰이 있으면 마이그레이션."""
    storage = FileTokenStorage(
        token_filename=OPENAI_CODEX_PROVIDER.token_filename,
        data_dir=_DATA_DIR,
    )
    if not storage.get_token_path().exists():
        shacs_storage = FileTokenStorage(
            token_filename=OPENAI_CODEX_PROVIDER.token_filename,
            data_dir=_SHACS_DATA_DIR,
        )
        token = shacs_storage.load()
        if token:
            storage.save(token)
    return storage


def _ensure_token() -> tuple[str, str]:
    """(access_token, account_id) 반환. 토큰 없으면 RuntimeError."""
    storage = _get_storage()
    try:
        token = get_token(storage=storage)
    except RuntimeError:
        raise CodexError(
            "Codex OAuth 토큰이 없습니다.\n  uv run main.py codex-login 으로 로그인하세요."
        )
    if not token.account_id:
        raise CodexError("Codex 토큰에 account_id가 없습니다. 재로그인 필요.")
    return token.access, token.account_id


def codex_login():
    """대화형 OAuth 로그인."""
    storage = _get_storage()
    token = login_oauth_interactive(
        print_fn=print,
        prompt_fn=input,
        storage=storage,
    )
    account_id = token.account_id or "unknown"
    print(f"로그인 성공 (account: {account_id[:8]}...)")
    return token


def _prompt_cache_key(system: str, user: str) -> str:
    raw = json.dumps({"s": system, "u": user}, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_sse_stream(response: httpx.Response) -> str:
    """SSE 스트림에서 텍스트 콘텐츠만 추출."""
    content = ""
    buffer: list[str] = []

    for line in response.iter_lines():
        if line == "":
            if buffer:
                data_lines = [l[5:].strip() for l in buffer if l.startswith("data:")]
                buffer = []
                if not data_lines:
                    continue
                data = "\n".join(data_lines).strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = cast(JsonValue, json.loads(data))
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str):
                        content += delta
                elif event_type in ("error", "response.failed"):
                    raw_error = event.get("error")
                    if not isinstance(raw_error, dict):
                        raw_response = event.get("response")
                        raw_error = (
                            raw_response.get("error")
                            if isinstance(raw_response, dict)
                            else None
                        )
                    error = raw_error if isinstance(raw_error, dict) else {}
                    code = error.get("code") or error.get("type")
                    message = error.get("message")
                    detail = ": ".join(str(value) for value in (code, message) if value)
                    raise CodexError(
                        f"Codex API 응답 실패: {detail}"
                        if detail
                        else "Codex API 응답 실패"
                    )
            continue
        buffer.append(line)

    return content


def generate(system_prompt: str, user_prompt: str, model: str = "gpt-5.1-codex") -> str:
    """Codex Responses API로 텍스트 생성. 동기 호출."""
    return _generate(
        _GenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            timeout_seconds=120.0,
        )
    )


def probe_model(model_id: str = "gpt-5.1-codex", timeout_seconds: int = 20) -> str:
    try:
        response = _generate(
            _GenerationRequest(
                system_prompt="Return a short plain-text health response.",
                user_prompt="Respond with OK.",
                model=model_id,
                timeout_seconds=float(timeout_seconds),
            )
        )
    except httpx.HTTPError as error:
        raise CodexError(f"Codex integration probe failed: {error}") from error
    if not response.strip():
        raise CodexError("Codex integration probe returned empty output")
    return response


def _generate(request: _GenerationRequest) -> str:
    access_token, account_id = _ensure_token()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": "trading-oracle",
        "User-Agent": "trading-oracle (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }

    body = {
        "model": request.model,
        "store": False,
        "stream": True,
        "instructions": request.system_prompt,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": request.user_prompt}],
            }
        ],
        "text": {"verbosity": "medium"},
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": _prompt_cache_key(request.system_prompt, request.user_prompt),
    }

    with httpx.Client(timeout=request.timeout_seconds) as client:
        with client.stream("POST", CODEX_URL, headers=headers, json=body) as response:
            if response.status_code == 429:
                raise CodexError("ChatGPT 사용량 한도 초과. 잠시 후 다시 시도하세요.")
            if response.status_code != 200:
                raw = response.read().decode("utf-8", "ignore")
                raise CodexError(f"Codex API 오류 HTTP {response.status_code}: {raw[:300]}")
            return _parse_sse_stream(response)
