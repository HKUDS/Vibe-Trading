"""OpenAI Codex OAuth provider."""

from __future__ import annotations

from src.tools.path_utils import FileRoots

import asyncio
import base64
import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional
from urllib.parse import urlparse

from src.config.accessor import get_env_config
from src.config.paths import get_runtime_root
from src.providers.response import usage_metadata
from src.providers.session_context import current_llm_session_id

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
    """Raised when the OpenAI Codex stream responds with an HTTP error."""

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
    """Build the Vibe-owned Codex token store."""
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
        # Lock byte 0 beyond EOF without writing a sentinel byte (see ledger.py).
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
    token_path = storage.get_token_path()
    lock_path = token_path.with_suffix(token_path.suffix + ".lock")
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
class CodexAIMessage:
    """Small LangChain-like message object used by ChatLLM."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=lambda: {"finish_reason": "stop"})
    usage_metadata: dict[str, Any] | None = None

    def __add__(self, other: "CodexAIMessage") -> "CodexAIMessage":
        finish_reason = other.response_metadata.get(
            "finish_reason",
            self.response_metadata.get("finish_reason", "stop"),
        )
        response_metadata = {**self.response_metadata, **other.response_metadata}
        response_metadata["finish_reason"] = finish_reason
        reasoning = self.additional_kwargs.get("reasoning_content", "") + other.additional_kwargs.get(
            "reasoning_content", ""
        )
        additional_kwargs: dict[str, Any] = {"reasoning_content": reasoning} if reasoning else {}
        provider_items = [
            *self.additional_kwargs.get("provider_items", []),
            *other.additional_kwargs.get("provider_items", []),
        ]
        if provider_items:
            additional_kwargs["provider_items"] = provider_items
        return CodexAIMessage(
            content=(self.content or "") + (other.content or ""),
            tool_calls=[*self.tool_calls, *other.tool_calls],
            additional_kwargs=additional_kwargs,
            response_metadata=response_metadata,
            usage_metadata=other.usage_metadata or self.usage_metadata,
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
    """Refresh through oauth-cli-kit without accepting its stale fallback."""
    try:
        from oauth_cli_kit import get_token

        # Force refresh and reject the cached token if the SDK returns it after failure.
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
    """Return a usable Vibe-owned token, refreshing once when required."""
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
    """Validate the only supported ChatGPT Codex OAuth endpoint."""
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


def _prompt_cache_key(instructions: str) -> str:
    """Cache-routing key shared by every request of one conversation."""
    basis = current_llm_session_id() or instructions
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


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


def _convert_tool_output(content: Any, *, roots: FileRoots) -> Any:
    """Convert durable image references to Responses image input parts."""
    if not isinstance(content, list):
        return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    output: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"text", "input_text"}:
            output.append({"type": "input_text", "text": part.get("text", "")})
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url")
            try:
                from src.tools.path_utils import safe_document_path, safe_path

                if not isinstance(url, str) or not url or "://" in url or url.startswith("data:"):
                    raise ValueError("tool images must reference local artifacts")
                try:
                    path = safe_document_path(url, roots=roots)
                except ValueError:
                    session_id = current_llm_session_id()
                    if not session_id:
                        raise
                    session_root = safe_path(session_id, roots.runtime_root / "sessions")
                    workspace = safe_path("workspace", session_root)
                    path = safe_path(url, workspace)
                mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                output.append({"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "auto"})
            except (OSError, ValueError, RuntimeError):
                output.append({"type": "input_text", "text": "[image artifact unavailable: missing or outside allowed roots]"})
    return output or ""


def _split_tool_call_id(tool_call_id: Any) -> tuple[str, str | None]:
    if isinstance(tool_call_id, str) and tool_call_id:
        if "|" in tool_call_id:
            call_id, item_id = tool_call_id.split("|", 1)
            return call_id, item_id or None
        return tool_call_id, None
    return "call_0", None


def _convert_messages(
    messages: list[dict[str, Any]],
    *,
    roots: FileRoots,
    replay_reasoning: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    """Convert loop messages into Responses ``instructions`` + ``input`` items."""
    system_prompt = ""
    instructions_taken = False
    input_items: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            text = content if isinstance(content, str) else ""
            if not instructions_taken:
                system_prompt = text
                instructions_taken = True
            elif text:
                # Map mid-run instructions to developer messages so the original system prompt persists.
                input_items.append(
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_text", "text": text}],
                    }
                )
        elif role == "user":
            input_items.append(_convert_user_message(content))
        elif role == "assistant":
            if replay_reasoning:
                input_items.extend(
                    dict(item)
                    for item in msg.get("provider_items") or []
                    if isinstance(item, dict) and item.get("type") == "reasoning"
                )
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
                function_call = {
                    "type": "function_call",
                    "call_id": call_id or f"call_{idx}",
                    "name": fn.get("name"),
                    "arguments": fn.get("arguments") or "{}",
                }
                # Preserve backend-issued IDs because fabricated IDs collide in parallel batches.
                if item_id:
                    function_call["id"] = item_id
                input_items.append(function_call)
        elif role == "tool":
            call_id, _ = _split_tool_call_id(msg.get("tool_call_id"))
            output = _convert_tool_output(content, roots=roots)
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
                # Disable strict mode so optional schema fields can be omitted.
                "strict": False,
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
    data_lines: list[str] = []
    for line in chain(lines, ("",)):
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif not line and data_lines:
            data = "\n".join(data_lines).strip()
            data_lines.clear()
            if data and data != "[DONE]":
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event is not None:
                    yield event


#: Models whose backend refused a replayed reasoning item (process lifetime).
_REASONING_REPLAY_REJECTED: set[str] = set()
_REASONING_REJECTION_RE = re.compile(r"reasoning|encrypted_content|rs_[A-Za-z0-9]", re.IGNORECASE)


def _has_reasoning_items(body: dict[str, Any]) -> bool:
    return any(item.get("type") == "reasoning" for item in body.get("input") or [])


def _response_usage(usage: Any) -> dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    keys = ("input_tokens", "output_tokens", "total_tokens")
    values = (usage.get(key) for key in keys)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        return None
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens")
    reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens")
    return usage_metadata(
        usage["input_tokens"],
        usage["output_tokens"],
        total=usage["total_tokens"],
        input_details={"cache_read": cached} if isinstance(cached, int) else None,
        output_details={"reasoning": reasoning} if isinstance(reasoning, int) else None,
    )


def _message_chunks_from_events(events: Iterable[dict[str, Any]]) -> Iterable[CodexAIMessage]:
    tool_buffers: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call" and item.get("call_id"):
                tool_buffers[item["call_id"]] = {
                    "id": item.get("id"),
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments") or "",
                }
        elif event_type == "response.output_text.delta":
            delta = event.get("delta") or ""
            if delta:
                yield CodexAIMessage(content=delta)
        elif event_type in {"response.function_call_arguments.delta", "response.function_call_arguments.done"}:
            buffer = tool_buffers.get(event.get("call_id"))
            if buffer is not None:
                if event_type.endswith(".delta"):
                    buffer["arguments"] += event.get("delta") or ""
                else:
                    buffer["arguments"] = event.get("arguments") or ""
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "reasoning" and item.get("encrypted_content"):
                # Kept verbatim (minus plaintext content) for the next request.
                kept = {
                    "type": "reasoning",
                    "summary": item.get("summary") or [],
                    "encrypted_content": item["encrypted_content"],
                }
                if item.get("id"):
                    kept["id"] = item["id"]
                yield CodexAIMessage(additional_kwargs={"provider_items": [kept]})
            elif item.get("type") == "function_call" and item.get("call_id"):
                call_id = item["call_id"]
                buf = tool_buffers.get(call_id) or {}
                args_raw = buf.get("arguments") or item.get("arguments") or "{}"
                item_id = buf.get("id") or item.get("id")
                yield CodexAIMessage(tool_calls=[{
                    "id": f"{call_id}|{item_id}" if item_id else call_id,
                    "name": buf.get("name") or item.get("name") or "",
                    "args": _decode_tool_args(args_raw),
                }])
        elif event_type == "response.completed":
            response = event.get("response") or {}
            status = response.get("status")
            response_metadata = {"finish_reason": _map_finish_reason(status)}
            model = response.get("model")
            if isinstance(model, str) and model.strip():
                response_metadata["model_name"] = model.strip()
            yield CodexAIMessage(
                response_metadata=response_metadata,
                usage_metadata=_response_usage(response.get("usage")),
            )
        elif event_type in {"error", "response.failed"}:
            detail = event.get("error") or event.get("message") or event
            raise RuntimeError(f"OpenAI Codex response failed: {str(detail)[:500]}")


class OpenAICodexLLM:
    """Minimal LangChain-compatible adapter for Vibe-Trading's ChatLLM."""

    def __init__(
        self,
        *,
        model: str,
        roots: FileRoots,
        temperature: float = 0.0,
        timeout: int = 120,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
        codex_url: str | None = None,
    ) -> None:
        if httpx is None:
            raise RuntimeError("OpenAI Codex OAuth requires httpx. Install dependencies first.")
        self.model = model
        self.roots = roots
        self.temperature = temperature
        self.timeout = timeout
        self.tools = tools or []
        self.reasoning_effort = reasoning_effort
        self.codex_url = validate_codex_base_url(codex_url or get_env_config().llm.openai_codex_base_url)

    def bind_tools(self, tools: list[dict[str, Any]]) -> "OpenAICodexLLM":
        return OpenAICodexLLM(
            model=self.model,
            roots=self.roots,
            temperature=self.temperature,
            timeout=self.timeout,
            tools=tools,
            reasoning_effort=self.reasoning_effort,
            codex_url=self.codex_url,
        )

    def _body(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool,
        replay_reasoning: bool = True,
    ) -> dict[str, Any]:
        system_prompt, input_items = _convert_messages(
            messages, roots=self.roots, replay_reasoning=replay_reasoning
        )
        body: dict[str, Any] = {
            "model": _strip_model_prefix(self.model),
            "store": False,
            "stream": stream,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(system_prompt),
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        tools = _convert_tools(self.tools)
        if tools:
            body["tools"] = tools
        if self.reasoning_effort:
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
        replay = _strip_model_prefix(self.model) not in _REASONING_REPLAY_REJECTED
        body = self._body(messages, stream=True, replay_reasoning=replay)
        headers = self._headers()
        refreshed = False
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=True) as client:
            while True:
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

                if status_code == 401 and not refreshed:
                    refreshed = True
                    authorization = headers.get("Authorization", "")
                    rejected_access = authorization[7:] if authorization.startswith("Bearer ") else None
                    headers = self._headers(
                        force_refresh=True,
                        rejected_access=rejected_access,
                    )
                    continue

                if (
                    status_code == 400
                    and replay
                    and _has_reasoning_items(body)
                    and _REASONING_REJECTION_RE.search(raw)
                ):
                    # Retry once without encrypted reasoning when the backend rejects replay.
                    _REASONING_REPLAY_REJECTED.add(_strip_model_prefix(self.model))
                    replay = False
                    body = self._body(messages, stream=True, replay_reasoning=False)
                    continue

                # Keep status so the outer retry policy can reject deterministic 4xx failures.
                raise CodexStreamError(status_code, raw)

    def invoke(self, messages: list[dict[str, Any]], config: Optional[dict[str, Any]] = None) -> CodexAIMessage:
        accumulated: CodexAIMessage | None = None
        for chunk in self.stream(messages, config=config):
            accumulated = chunk if accumulated is None else accumulated + chunk
        return accumulated or CodexAIMessage()

    async def ainvoke(self, messages: list[dict[str, Any]], config: Optional[dict[str, Any]] = None) -> CodexAIMessage:
        return await asyncio.to_thread(self.invoke, messages, config)
