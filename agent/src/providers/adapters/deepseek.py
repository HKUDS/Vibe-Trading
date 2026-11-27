"""Native DeepSeek client and textual DSML tool-call decoding."""

from __future__ import annotations

import html
import json
import logging
import re
from importlib import import_module
from typing import Any

from src.kernel import contracts
from src.providers import request_guards
from src.providers.request_guards import _guard_provider_redirects


logger = logging.getLogger(__name__)


def _deepseek_adapter_mode(value: str = "auto") -> str:
    """Return the configured DeepSeek adapter mode."""
    mode = value.strip().lower()
    aliases = {
        "compat": "openai-compatible",
        "compatible": "openai-compatible",
        "openai": "openai-compatible",
        "openai_compatible": "openai-compatible",
    }
    return aliases.get(mode, mode or "auto")


def _build_native_deepseek(
    *,
    model: str,
    temperature: float,
    snapshot: Any,
    callbacks: Any = None,
) -> Any | None:
    """Build the optional native DeepSeek adapter when installed."""
    try:
        module = import_module("langchain_deepseek")
        chat_deepseek = getattr(module, "ChatDeepSeek")
    except Exception as exc:  # noqa: BLE001 - optional adapter fallback
        logger.info("DeepSeek native adapter unavailable; using OpenAI-compatible path: %s", exc)
        return None

    api_key, base_url = snapshot.api_key, snapshot.base_url
    if not api_key:
        raise RuntimeError("Set DEEPSEEK_API_KEY (or legacy OPENAI_API_KEY) before using the native DeepSeek adapter")
    output_limit = snapshot.options.langchain_max_tokens
    sdk_module = import_module("openai")
    proxy = snapshot.environment.get("OPENAI_PROXY", "")
    clients = request_guards._build_http_clients(sdk=sdk_module) if snapshot.options.vibe_trading_disable_http_proxy else (
        request_guards._build_http_clients(proxy, sdk=sdk_module) if proxy else None
    )
    client = chat_deepseek(
        model=model,
        temperature=temperature,
        timeout=snapshot.options.timeout_seconds,
        max_retries=snapshot.options.max_retries,
        callbacks=callbacks,
        api_key=api_key,
        base_url=base_url,
        openai_proxy="" if clients else proxy,
        **({"http_client": clients[0], "http_async_client": clients[1]} if clients else {}),
        **({"max_tokens": output_limit} if output_limit is not None else {}),
    )
    # Unlike ChatOpenAI, ChatDeepSeek constructs per-instance SDK clients.
    client._vibe_owned_http_clients = clients or (client.root_client, client.root_async_client)
    _guard_provider_redirects(client.root_client, client.root_async_client)
    for sdk in (getattr(client, "root_client", None), getattr(client, "root_async_client", None)):
        if sdk is not None:
            sdk._custom_headers = {}
            sdk.organization = sdk.project = None
    return client


def _native_deepseek_adapter_available() -> bool:
    """Return whether the optional native DeepSeek adapter can be imported."""
    try:
        module = import_module("langchain_deepseek")
    except Exception:  # noqa: BLE001 - optional adapter availability probe
        return False
    return callable(getattr(module, "ChatDeepSeek", None))


_DSML_BARS = ("||", "｜｜")
_DSML_WRAPPERS = ("calls", "tool_calls")
_DSML_BAR = "(?:" + "|".join(map(re.escape, _DSML_BARS)) + ")"
_DSML_TAG = rf"{_DSML_BAR}\s*DSML\s*{_DSML_BAR}"
_DSML_TOOL_CALLS_RE = re.compile(
    rf"<\s*{_DSML_TAG}\s*(?P<wrapper>{'|'.join(_DSML_WRAPPERS)})\s*>(?P<body>.*?)"
    rf"</\s*{_DSML_TAG}\s*(?P=wrapper)\s*>",
    re.DOTALL,
)
_DSML_INVOKE_RE = re.compile(
    rf"<\s*{_DSML_TAG}\s*invoke\b(?P<attrs>[^>]*)>(?P<body>.*?)"
    rf"</\s*{_DSML_TAG}\s*invoke\s*>",
    re.DOTALL,
)
_DSML_PARAMETER_RE = re.compile(
    rf"<\s*{_DSML_TAG}\s*parameter\b(?P<attrs>[^>]*)>(?P<body>.*?)"
    rf"</\s*{_DSML_TAG}\s*parameter\s*>",
    re.DOTALL,
)
_DSML_ATTR_RE = re.compile(r"""\s+([A-Za-z_][\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_DSML_MARKUP_RE = re.compile(rf"</?\s*{_DSML_TAG}")
_DSML_PREFIXES = tuple(
    f"<{left}DSML{right}{wrapper}>"
    for left in _DSML_BARS for right in _DSML_BARS for wrapper in _DSML_WRAPPERS
)


def _dsml_sequence(pattern: re.Pattern[str], text: str) -> list[re.Match[str]] | None:
    """Read a sequence of elements separated only by whitespace."""
    matches = []
    end = 0
    for match in pattern.finditer(text):
        if text[end:match.start()].strip():
            return None
        matches.append(match)
        end = match.end()
    return None if text[end:].strip() else matches


def _parse_dsml_attrs(raw: str) -> dict[str, str] | None:
    """Parse a DSML tag's attributes, rejecting malformed or duplicate keys."""
    matches = _dsml_sequence(_DSML_ATTR_RE, raw)
    if matches is None:
        return None
    attrs: dict[str, str] = {}
    for match in matches:
        key = match.group(1)
        if key in attrs:
            return None
        attrs[key] = html.unescape(match.group(2) or match.group(3) or "")
    return attrs


def _is_possible_dsml_tool_call_prefix(content: str) -> bool:
    """Return True while buffered stream text could still be a DSML call."""
    compact = re.sub(r"\s+", "", content.lstrip()[:80])
    return any(prefix.startswith(compact) or compact.startswith(prefix) for prefix in _DSML_PREFIXES)


def _reject_dsml_json_constant(value: str) -> None:
    """Reject JavaScript numeric constants outside JSON."""
    raise ValueError(f"Invalid DSML JSON constant: {value}")


def _parse_dsml_tool_calls(content: Any) -> list[contracts.ToolCallRequest]:
    """Parse a complete assistant payload of DeepSeek-style DSML tool calls."""
    if not isinstance(content, str):
        return []

    # Some relays append a slash after the last wrapper.
    blocks = _dsml_sequence(_DSML_TOOL_CALLS_RE, content.strip().removesuffix("/"))
    if not blocks:
        return []

    tool_calls: list[contracts.ToolCallRequest] = []
    for block in blocks:
        invokes = _dsml_sequence(_DSML_INVOKE_RE, block.group("body"))
        if not invokes:
            return []
        for invoke in invokes:
            attrs = _parse_dsml_attrs(invoke.group("attrs"))
            name = (attrs or {}).get("name", "").strip()
            params = _dsml_sequence(_DSML_PARAMETER_RE, invoke.group("body"))
            if not name or params is None:
                return []

            arguments: dict[str, Any] = {}
            for param in params:
                param_attrs = _parse_dsml_attrs(param.group("attrs")) or {}
                param_name = param_attrs.get("name", "").strip()
                raw = param.group("body")
                string = param_attrs.get("string", "true")
                if not param_name or param_name in arguments or _DSML_MARKUP_RE.search(raw):
                    return []
                value = html.unescape(raw).strip()
                if string == "true":
                    arguments[param_name] = value
                elif string == "false":
                    try:
                        arguments[param_name] = json.loads(value, parse_constant=_reject_dsml_json_constant)
                    except (ValueError, RecursionError):
                        return []
                else:
                    return []

            tool_calls.append(
                contracts.ToolCallRequest(
                    id=f"dsml_call_{len(tool_calls) + 1}",
                    name=name,
                    arguments=arguments,
                )
            )

    return tool_calls
