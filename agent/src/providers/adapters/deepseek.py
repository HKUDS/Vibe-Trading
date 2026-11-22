"""Native DeepSeek client and textual DSML tool-call decoding."""

from __future__ import annotations

import html
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
    """Build the optional native DeepSeek adapter when installed.

    Returns:
        A ChatDeepSeek instance, or ``None`` when the optional package is not
        available.
    """
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


_DSML_BAR = r"(?:\|\||｜｜)"
_DSML_TAG = rf"{_DSML_BAR}\s*DSML\s*{_DSML_BAR}"
_DSML_TOOL_CALLS_RE = re.compile(
    rf"<\s*{_DSML_TAG}\s*tool_calls\s*>(?P<body>.*?)"
    rf"</\s*{_DSML_TAG}\s*tool_calls\s*>",
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
_DSML_ATTR_RE = re.compile(r"""([A-Za-z_][\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_DSML_PREFIXES = ("<||dsml||tool_calls", "<｜｜dsml｜｜tool_calls")


def _parse_dsml_attrs(raw: str) -> dict[str, str]:
    """Parse attributes from a DSML tag."""
    attrs: dict[str, str] = {}
    for match in _DSML_ATTR_RE.finditer(raw):
        attrs[match.group(1)] = html.unescape(match.group(2) or match.group(3) or "")
    return attrs


def _is_possible_dsml_tool_call_prefix(content: str) -> bool:
    """Return True while buffered stream text could still be a DSML call."""
    compact = re.sub(r"\s+", "", content.lstrip()[:80]).lower()
    if not compact:
        return True
    return any(prefix.startswith(compact) or compact.startswith(prefix) for prefix in _DSML_PREFIXES)


def _parse_dsml_tool_calls(content: Any) -> list[contracts.ToolCallRequest]:
    """Parse DeepSeek-style DSML tool calls embedded as assistant content.

    Some OpenAI-compatible relays/models return tool calls as a textual DSML
    block rather than LangChain ``AIMessage.tool_calls``. Treat only pure DSML
    tool-call payloads as executable so examples embedded in normal prose never
    cross into the tool path.
    """
    if not isinstance(content, str):
        return []

    stripped = content.strip()
    blocks = list(_DSML_TOOL_CALLS_RE.finditer(stripped))
    if not blocks:
        return []

    outside = _DSML_TOOL_CALLS_RE.sub("", stripped).strip()
    if outside not in {"", "/"}:
        return []

    tool_calls: list[contracts.ToolCallRequest] = []
    for block in blocks:
        for invoke in _DSML_INVOKE_RE.finditer(block.group("body")):
            invoke_attrs = _parse_dsml_attrs(invoke.group("attrs"))
            name = invoke_attrs.get("name", "").strip()
            if not name:
                continue

            arguments: dict[str, Any] = {}
            for param in _DSML_PARAMETER_RE.finditer(invoke.group("body")):
                param_attrs = _parse_dsml_attrs(param.group("attrs"))
                param_name = param_attrs.get("name", "").strip()
                if param_name:
                    arguments[param_name] = html.unescape(param.group("body")).strip()

            tool_calls.append(
                contracts.ToolCallRequest(
                    id=f"dsml_call_{len(tool_calls) + 1}",
                    name=name,
                    arguments=arguments,
                )
            )

    return tool_calls
