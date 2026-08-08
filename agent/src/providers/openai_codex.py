"""OpenAI Codex OAuth provider.

This provider follows the reference OpenAI Codex OAuth path: a ChatGPT account is
authenticated by oauth-cli-kit, then requests are sent to the ChatGPT Codex
Responses endpoint. It is intentionally separate from the standard OpenAI API
key path because ChatGPT OAuth tokens are not OpenAI API keys.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional
from urllib.parse import urlparse

from src.config.accessor import get_env_config
from src.config.paths import get_runtime_root

try:  # pragma: no cover - platform-specific imports are exercised via mocks.
    import fcntl
except ImportError:  # pragma: no cover - Windows.
    fcntl = None  # type: ignore[assignment]

try:  # pragma: no cover - platform-specific imports are exercised via mocks.
    import msvcrt
except ImportError:  # pragma: no cover - POSIX.
    msvcrt = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

DEFAULT_CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_ORIGINATOR = "vibe-trading"
_CODEX_REFRESH_MARGIN_SECONDS = 300
_CODEX_FORCE_REFRESH_TTL_SECONDS = 2_147_483_647
_CODEX_LOGIN_COMMAND = "vibe-trading provider login openai-codex"
_CODEX_TOKEN_FILENAME = "openai-codex.json"
_PERMANENT_REFRESH_ERROR_CODES = {
    "invalid_grant",
    "refresh_token_invalidated",
    "refresh_token_reused",
    "token_invalidated",
}
_TOKEN_REFRESH_THREAD_LOCK = threading.Lock()


class CodexStreamError(RuntimeError):
    """Raised when the OpenAI Codex stream responds with an HTTP error.

    Subclasses ``RuntimeError`` to preserve the historical contract (callers
    historically caught ``RuntimeError`` here) but carries an explicit
    ``status_code`` so the upstream ``ProviderStreamError`` classification
    can distinguish transient (5xx/408/429) failures from deterministic
    4xx that should not be retried. Without this, every Codex failure
    looked ``status_code=None`` → ``retryable=True`` and codex 400/401/403
    responses wasted a retry budget.
    """

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = int(status_code)
        message = f"OpenAI Codex HTTP {self.status_code}: {str(detail)[:500]}"
        super().__init__(message)


class CodexAuthenticationError(CodexStreamError):
    """Raised when a rejected Codex session requires explicit login."""

    def __init__(self, detail: str) -> None:
        message = detail.rstrip(". ")
        if _CODEX_LOGIN_COMMAND not in message:
            message = f"{message}. Run: {_CODEX_LOGIN_COMMAND}"
        super().__init__(401, message)


class _CodexRefreshError(RuntimeError):
    """Internal refresh failure with retry and invalidation metadata."""

    def __init__(self, detail: str, *, status_code: int | None, permanent: bool) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.permanent = permanent


def _build_codex_token_storage(path: Path | None = None) -> Any:
    """Build the Vibe-owned Codex token store.

    The path deliberately does not use oauth-cli-kit's default storage, because
    that backend imports and copies ``~/.codex/auth.json``. A copied rotating
    refresh token gives two processes ownership of one OAuth session and causes
    the ``token_invalidated`` / ``refresh_token_reused`` failure in issue #975.
    """
    try:
        from oauth_cli_kit.storage import FileTokenStorage
    except ImportError as exc:
        raise RuntimeError("oauth-cli-kit is not installed. Run: pip install oauth-cli-kit") from exc

    token_path = path or (get_runtime_root() / "auth" / _CODEX_TOKEN_FILENAME)

    class VibeCodexTokenStorage(FileTokenStorage):
        def get_token_path(self) -> Path:
            return token_path

    return VibeCodexTokenStorage(
        token_filename=_CODEX_TOKEN_FILENAME,
        app_name="vibe-trading",
        import_codex_cli=False,
    )


def _clear_codex_token(storage: Any) -> None:
    """Remove only Vibe's invalid credential cache."""
    try:
        storage.get_token_path().unlink(missing_ok=True)
    except OSError:
        pass


def _lock_token_file(handle: Any) -> None:
    """Acquire a cross-process lock on an opened token lock file."""
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    if msvcrt is not None:  # pragma: no cover - exercised with a platform mock.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    raise RuntimeError("No supported file-lock backend for Codex OAuth refresh")


def _unlock_token_file(handle: Any) -> None:
    """Release the lock acquired by :func:`_lock_token_file`."""
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:  # pragma: no cover - exercised with a platform mock.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def _codex_refresh_lock(storage: Any) -> Iterator[None]:
    """Serialize refresh-token rotation across threads and processes."""
    lock_path = storage.get_token_path().with_name(f"{storage.get_token_path().name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _TOKEN_REFRESH_THREAD_LOCK:
        with lock_path.open("a+b") as handle:
            try:
                os.chmod(lock_path, 0o600)
            except OSError:
                pass
            _lock_token_file(handle)
            try:
                yield
            finally:
                _unlock_token_file(handle)


def _decode_jwt_claims(access_token: str) -> dict[str, Any]:
    """Decode unverified JWT claims used only for expiry/account metadata."""
    try:
        payload = access_token.split(".", 2)[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded.decode("utf-8"))
    except (IndexError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _token_expiry_ms(token: Any) -> int:
    """Return the access token's real JWT expiry, with stored expiry fallback."""
    access = getattr(token, "access", "")
    claims = _decode_jwt_claims(access) if isinstance(access, str) else {}
    jwt_expiry = claims.get("exp")
    if isinstance(jwt_expiry, (int, float)) and not isinstance(jwt_expiry, bool):
        return int(jwt_expiry * 1000)
    try:
        stored_expiry = int(getattr(token, "expires"))
    except (TypeError, ValueError):
        return 0
    return stored_expiry * 1000 if stored_expiry < 100_000_000_000 else stored_expiry


def _load_codex_oauth_provider() -> Any:
    """Load oauth-cli-kit's provider constants without using its token cache."""
    try:
        from oauth_cli_kit import OPENAI_CODEX_PROVIDER
    except ImportError as exc:
        raise RuntimeError(
            f"OpenAI Codex OAuth requires oauth-cli-kit. Install dependencies, then run: {_CODEX_LOGIN_COMMAND}"
        ) from exc
    return OPENAI_CODEX_PROVIDER


@dataclass
class CodexToolCall:
    """Internal tool-call representation compatible with ChatLLM parsing."""

    id: str
    name: str
    arguments: dict[str, Any]

    def as_langchain_tool_call(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "args": self.arguments}


@dataclass
class CodexAIMessage:
    """Small LangChain-like message object used by ChatLLM."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=lambda: {"finish_reason": "stop"})

    def __add__(self, other: "CodexAIMessage") -> "CodexAIMessage":
        finish_reason = other.response_metadata.get(
            "finish_reason",
            self.response_metadata.get("finish_reason", "stop"),
        )
        reasoning = self.additional_kwargs.get("reasoning_content", "") + other.additional_kwargs.get(
            "reasoning_content", ""
        )
        return CodexAIMessage(
            content=(self.content or "") + (other.content or ""),
            tool_calls=[*self.tool_calls, *other.tool_calls],
            additional_kwargs={"reasoning_content": reasoning} if reasoning else {},
            response_metadata={"finish_reason": finish_reason},
        )


def login_openai_codex(
    print_fn: Callable[[str], None] | None = None,
    prompt_fn: Callable[[str], str] | None = None,
) -> Any:
    """Force interactive ChatGPT/Codex OAuth login into Vibe-owned storage."""
    try:
        from oauth_cli_kit import login_oauth_interactive
    except ImportError as exc:
        raise RuntimeError("oauth-cli-kit is not installed. Run: pip install oauth-cli-kit") from exc

    return login_oauth_interactive(
        print_fn=print_fn or print,
        prompt_fn=prompt_fn or input,
        provider=_load_codex_oauth_provider(),
        originator=DEFAULT_ORIGINATOR,
        storage=_build_codex_token_storage(),
    )


def get_openai_codex_login_status() -> Any | None:
    """Return a usable Vibe-owned OAuth token, if available."""
    try:
        token = _get_codex_token()
    except Exception:
        return None
    if token and getattr(token, "access", None):
        return token
    return None


def _refresh_codex_token(token: Any, storage: Any) -> Any:
    """Refresh through oauth-cli-kit without accepting its stale fallback.

    Args:
        token: Current token carrying the rotating refresh credential.
        storage: Vibe-owned destination store.

    Returns:
        The refreshed token.

    Raises:
        _CodexRefreshError: If oauth-cli-kit cannot obtain a replacement token.
    """
    try:
        from oauth_cli_kit import get_token

        # The very large TTL forces oauth-cli-kit to call the token endpoint.
        # We compare the result with ``token`` below because oauth-cli-kit may
        # otherwise return the old, locally-unexpired token after refresh fails.
        refreshed = get_token(
            provider=_load_codex_oauth_provider(),
            storage=storage,
            min_ttl_seconds=_CODEX_FORCE_REFRESH_TTL_SECONDS,
        )
    except Exception as exc:
        detail = str(exc).lower()
        raise _CodexRefreshError(
            f"Codex OAuth token refresh failed: {type(exc).__name__}",
            status_code=None,
            permanent=any(code in detail for code in _PERMANENT_REFRESH_ERROR_CODES),
        ) from exc
    if not getattr(refreshed, "access", None) or not getattr(refreshed, "account_id", None):
        raise _CodexRefreshError(
            "Codex OAuth token refresh returned incomplete credentials",
            status_code=502,
            permanent=False,
        )
    return refreshed


def _missing_codex_login_error() -> CodexAuthenticationError:
    return CodexAuthenticationError("OpenAI Codex is not logged in")


def _get_codex_token(
    *,
    force_refresh: bool = False,
    rejected_access: str | None = None,
) -> Any:
    """Return a usable Vibe-owned token, refreshing once when required.

    Args:
        force_refresh: Refresh even when the local expiry clock is still fresh.
        rejected_access: Access token rejected by the backend. If another
            process already replaced it while this process waited for the lock,
            the newer token is used without a second refresh rotation.

    Returns:
        A usable OAuth token.

    Raises:
        RuntimeError: If no Vibe-owned credentials exist.
        CodexAuthenticationError: If the OAuth session was invalidated and an
            explicit login is required.
        CodexStreamError: If an expired token cannot be refreshed because of a
            transient OAuth endpoint failure.
    """
    storage = _build_codex_token_storage()
    token = storage.load()
    if not (token and token.access and token.refresh and token.account_id):
        raise _missing_codex_login_error()

    now_ms = int(time.time() * 1000)
    if not force_refresh and _token_expiry_ms(token) - now_ms > _CODEX_REFRESH_MARGIN_SECONDS * 1000:
        return token

    with _codex_refresh_lock(storage):
        latest = storage.load()
        if not (latest and latest.access and latest.refresh and latest.account_id):
            raise _missing_codex_login_error()
        token = latest
        now_ms = int(time.time() * 1000)

        if rejected_access and token.access != rejected_access and _token_expiry_ms(token) > now_ms:
            return token
        if not force_refresh and _token_expiry_ms(token) - now_ms > _CODEX_REFRESH_MARGIN_SECONDS * 1000:
            return token

        try:
            refreshed = _refresh_codex_token(token, storage)
        except _CodexRefreshError as exc:
            if exc.permanent:
                _clear_codex_token(storage)
                raise CodexAuthenticationError("The Vibe-Trading Codex OAuth session was invalidated") from exc
            if not force_refresh and _token_expiry_ms(token) > now_ms:
                return token
            raise CodexStreamError(
                exc.status_code or 503,
                f"Codex OAuth recovery temporarily failed: {exc}",
            ) from exc
        if refreshed.access == token.access:
            if not force_refresh and _token_expiry_ms(token) > now_ms:
                return token
            _clear_codex_token(storage)
            raise CodexAuthenticationError("The Codex backend rejected the access token and refresh did not replace it")
        return refreshed


def validate_codex_base_url(url: str) -> str:
    """Validate the only supported ChatGPT Codex OAuth endpoint.

    ChatGPT OAuth tokens must not be sent to arbitrary OpenAI-compatible base
    URLs. The standard OpenAI API remains API-key authenticated; this provider
    is limited to the ChatGPT Codex backend endpoint used by Codex OAuth.
    """
    value = (url or DEFAULT_CODEX_URL).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "chatgpt.com" or parsed.path != "/backend-api/codex/responses":
        raise ValueError("OpenAI Codex OAuth only supports https://chatgpt.com/backend-api/codex/responses")
    return value


def _build_headers(account_id: str, access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": DEFAULT_ORIGINATOR,
        "User-Agent": "vibe-trading (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _prompt_cache_key(messages: list[dict[str, Any]]) -> str:
    raw = json.dumps(messages, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _convert_user_message(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"role": "user", "content": [{"type": "input_text", "text": content}]}
    if isinstance(content, list):
        converted: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                converted.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url")
                if url:
                    converted.append({"type": "input_image", "image_url": url, "detail": "auto"})
        if converted:
            return {"role": "user", "content": converted}
    return {"role": "user", "content": [{"type": "input_text", "text": ""}]}


def _split_tool_call_id(tool_call_id: Any) -> tuple[str, str | None]:
    if isinstance(tool_call_id, str) and tool_call_id:
        if "|" in tool_call_id:
            call_id, item_id = tool_call_id.split("|", 1)
            return call_id, item_id or None
        return tool_call_id, None
    return "call_0", None


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_prompt = ""
    input_items: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            system_prompt = content if isinstance(content, str) else ""
        elif role == "user":
            input_items.append(_convert_user_message(content))
        elif role == "assistant":
            if isinstance(content, str) and content:
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                        "status": "completed",
                        "id": f"msg_{idx}",
                    }
                )
            for tool_call in msg.get("tool_calls", []) or []:
                fn = tool_call.get("function") or {}
                call_id, item_id = _split_tool_call_id(tool_call.get("id"))
                input_items.append(
                    {
                        "type": "function_call",
                        "id": item_id or f"fc_{idx}",
                        "call_id": call_id or f"call_{idx}",
                        "name": fn.get("name"),
                        "arguments": fn.get("arguments") or "{}",
                    }
                )
        elif role == "tool":
            call_id, _ = _split_tool_call_id(msg.get("tool_call_id"))
            output = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            input_items.append({"type": "function_call_output", "call_id": call_id, "output": output})
    return system_prompt, input_items


def _convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools or []:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        params = fn.get("parameters") or {}
        converted.append(
            {
                "type": "function",
                "name": name,
                "description": fn.get("description") or "",
                "parameters": params if isinstance(params, dict) else {},
            }
        )
    return converted


def _decode_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": raw}


def _map_finish_reason(status: str | None) -> str:
    return {
        "completed": "stop",
        "incomplete": "length",
        "failed": "error",
        "cancelled": "error",
        "content_filter": "content_filter",
    }.get(status or "completed", "stop")


def _events_from_lines(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    buffer: list[str] = []

    def flush() -> dict[str, Any] | None:
        data_lines = [line[5:].strip() for line in buffer if line.startswith("data:")]
        buffer.clear()
        if not data_lines:
            return None
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return None
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None

    for line in lines:
        if line == "":
            if buffer:
                event = flush()
                if event is not None:
                    yield event
            continue
        buffer.append(line)
    if buffer:
        event = flush()
        if event is not None:
            yield event


def _message_chunks_from_events(events: Iterable[dict[str, Any]]) -> Iterable[CodexAIMessage]:
    tool_buffers: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call" and item.get("call_id"):
                tool_buffers[item["call_id"]] = {
                    "id": item.get("id") or "fc_0",
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments") or "",
                }
        elif event_type == "response.output_text.delta":
            delta = event.get("delta") or ""
            if delta:
                yield CodexAIMessage(content=delta)
        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id")
            if call_id in tool_buffers:
                tool_buffers[call_id]["arguments"] += event.get("delta") or ""
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id in tool_buffers:
                tool_buffers[call_id]["arguments"] = event.get("arguments") or ""
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call" and item.get("call_id"):
                call_id = item["call_id"]
                buf = tool_buffers.get(call_id) or {}
                args_raw = buf.get("arguments") or item.get("arguments") or "{}"
                tool = CodexToolCall(
                    id=f"{call_id}|{buf.get('id') or item.get('id') or 'fc_0'}",
                    name=buf.get("name") or item.get("name") or "",
                    arguments=_decode_tool_args(args_raw),
                )
                yield CodexAIMessage(tool_calls=[tool.as_langchain_tool_call()])
        elif event_type == "response.completed":
            status = (event.get("response") or {}).get("status")
            yield CodexAIMessage(response_metadata={"finish_reason": _map_finish_reason(status)})
        elif event_type in {"error", "response.failed"}:
            detail = event.get("error") or event.get("message") or event
            raise RuntimeError(f"OpenAI Codex response failed: {str(detail)[:500]}")


class OpenAICodexLLM:
    """Minimal LangChain-compatible adapter for Vibe-Trading's ChatLLM."""

    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.0,
        timeout: int = 120,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
        codex_url: str | None = None,
    ) -> None:
        if httpx is None:
            raise RuntimeError("OpenAI Codex OAuth requires httpx. Install dependencies first.")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.tools = tools or []
        self.reasoning_effort = reasoning_effort
        self.codex_url = validate_codex_base_url(codex_url or get_env_config().llm.openai_codex_base_url)

    def bind_tools(self, tools: list[dict[str, Any]]) -> "OpenAICodexLLM":
        return OpenAICodexLLM(
            model=self.model,
            temperature=self.temperature,
            timeout=self.timeout,
            tools=tools,
            reasoning_effort=self.reasoning_effort,
            codex_url=self.codex_url,
        )

    def _body(self, messages: list[dict[str, Any]], *, stream: bool) -> dict[str, Any]:
        system_prompt, input_items = _convert_messages(messages)
        body: dict[str, Any] = {
            "model": _strip_model_prefix(self.model),
            "store": False,
            "stream": stream,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(messages),
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        tools = _convert_tools(self.tools)
        if tools:
            body["tools"] = tools
        if self.reasoning_effort and self.reasoning_effort.lower() != "none":
            body["reasoning"] = {"effort": self.reasoning_effort.lower()}
        return body

    def _headers(
        self,
        *,
        force_refresh: bool = False,
        rejected_access: str | None = None,
    ) -> dict[str, str]:
        token = _get_codex_token(
            force_refresh=force_refresh,
            rejected_access=rejected_access,
        )
        return _build_headers(str(token.account_id), str(token.access))

    def stream(
        self, messages: list[dict[str, Any]], config: Optional[dict[str, Any]] = None
    ) -> Iterable[CodexAIMessage]:
        timeout = (config or {}).get("timeout") or self.timeout
        body = self._body(messages, stream=True)
        headers = self._headers()
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=True) as client:
            for attempt in range(2):
                with client.stream(
                    "POST",
                    self.codex_url,
                    headers=headers,
                    json=body,
                ) as response:
                    if response.status_code == 200:
                        yield from _message_chunks_from_events(_events_from_lines(response.iter_lines()))
                        return
                    raw = response.read().decode("utf-8", "ignore")
                    status_code = response.status_code

                if status_code == 401 and attempt == 0:
                    authorization = headers.get("Authorization", "")
                    rejected_access = authorization[7:] if authorization.startswith("Bearer ") else None
                    headers = self._headers(
                        force_refresh=True,
                        rejected_access=rejected_access,
                    )
                    continue

                # Preserve the typed status so deterministic 4xx failures are
                # not retried again by the provider-level retry wrapper.
                raise CodexStreamError(status_code, raw)

    def invoke(self, messages: list[dict[str, Any]], config: Optional[dict[str, Any]] = None) -> CodexAIMessage:
        accumulated: CodexAIMessage | None = None
        for chunk in self.stream(messages, config=config):
            accumulated = chunk if accumulated is None else accumulated + chunk
        return accumulated or CodexAIMessage()

    async def ainvoke(self, messages: list[dict[str, Any]], config: Optional[dict[str, Any]] = None) -> CodexAIMessage:
        return await asyncio.to_thread(self.invoke, messages, config)
