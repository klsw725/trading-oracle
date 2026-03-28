"""OpenAI Codex (Responses API) provider — OAuth 기반 텍스트 생성"""

import hashlib
import json
from pathlib import Path

import httpx

from oauth_cli_kit import get_token, login_oauth_interactive, OPENAI_CODEX_PROVIDER
from oauth_cli_kit.storage import FileTokenStorage

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
_DATA_DIR = Path.home() / ".trading-oracle"
_SHACS_DATA_DIR = Path.home() / ".shacs-bot"


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
        raise RuntimeError(
            "Codex OAuth 토큰이 없습니다.\n"
            "  uv run main.py codex-login 으로 로그인하세요."
        )
    if not token.account_id:
        raise RuntimeError("Codex 토큰에 account_id가 없습니다. 재로그인 필요.")
    return token.access, token.account_id


def codex_login():
    """대화형 OAuth 로그인."""
    storage = _get_storage()
    token = login_oauth_interactive(
        print_fn=print,
        prompt_fn=input,
        storage=storage,
    )
    print(f"로그인 성공 (account: {token.account_id[:8]}...)")
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
                    event = json.loads(data)
                except Exception:
                    continue
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    content += event.get("delta") or ""
                elif event_type in ("error", "response.failed"):
                    raise RuntimeError("Codex API 응답 실패")
            continue
        buffer.append(line)

    return content


def generate(system_prompt: str, user_prompt: str, model: str = "gpt-5.1-codex") -> str:
    """Codex Responses API로 텍스트 생성. 동기 호출."""
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
        "model": model,
        "store": False,
        "stream": True,
        "instructions": system_prompt,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            }
        ],
        "text": {"verbosity": "medium"},
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": _prompt_cache_key(system_prompt, user_prompt),
    }

    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", CODEX_URL, headers=headers, json=body) as response:
            if response.status_code == 429:
                raise RuntimeError("ChatGPT 사용량 한도 초과. 잠시 후 다시 시도하세요.")
            if response.status_code != 200:
                raw = response.read().decode("utf-8", "ignore")
                raise RuntimeError(f"Codex API 오류 HTTP {response.status_code}: {raw[:300]}")
            return _parse_sse_stream(response)
