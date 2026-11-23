"""Redacted provider configuration and diagnostic labels."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import urlsplit

from src.providers.adapters.deepseek import _deepseek_adapter_mode
from src.providers.adapters.reasoning import _sends_top_level_reasoning_effort
from src.providers.registry import get_provider_capabilities
from src.providers.request_guards import _AMBIENT_OPENAI_HEADER_ENV_VARS
from src.providers.settings import resolve_config


def _redact_base_url_for_log(raw: str | None) -> str:
    """Return a diagnostic-safe base URL label for logs."""
    if not raw or not raw.strip():
        return "(unset)"

    try:
        parsed = urlsplit(raw.strip())
    except ValueError:
        return "<base-url>"

    if not parsed.scheme or not parsed.hostname:
        return "<base-url>"

    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"

    return f"{parsed.scheme}://{host}"


def _package_version(package: str) -> str:
    """Return an installed package version or a stable missing label."""
    try:
        return version(package)
    except PackageNotFoundError:
        return "not_installed"


def _redact_env_flag(name: str, environment) -> str:
    """Report whether an env var is set without exposing its value."""
    value = environment.get(name, "")
    return "set" if value else "unset"


def _header_value_diagnostic(value: str) -> dict[str, Any]:
    """Describe a possible HTTP header value without exposing its contents."""
    return {
        "set": bool(value),
        "length": len(value),
        "ascii_only": value.isascii(),
    }


def _redact_proxy_url(name: str, raw: str | None) -> str:
    """Return a credential-free proxy URL label."""
    if not raw:
        return "unset"
    if name.upper().endswith("NO_PROXY"):
        return "set"
    return _redact_base_url_for_log(raw)


def provider_diagnostics(*, policy: ToolPolicy) -> dict[str, Any]:
    """Build a redacted provider diagnostic snapshot.

    Returns:
        Redacted provider/model/package/env/proxy/capability details.
    """
    snapshot = resolve_config()
    environment = snapshot.environment
    provider, model = snapshot.provider, snapshot.model
    options = snapshot.options
    caps = get_provider_capabilities(provider, model)
    key_env = caps.api_key_env
    base_url = snapshot.base_url
    credential_source = key_env if key_env and snapshot.environment.get(key_env) else "OPENAI_API_KEY"
    proxy_names = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ]
    package_names = [
        "langchain-openai",
        "langchain-anthropic",
        "langchain-core",
        "langchain",
        "openai",
        "langchain-deepseek",
    ]
    native_package_version = _package_version(caps.native_adapter_package) if caps.native_adapter_package else None
    adapter_mode = adapter_type = "openai-compatible"
    if snapshot.backend == "anthropic":
        adapter_mode = adapter_type = "native"
    elif snapshot.backend == "deepseek":
        adapter_mode = _deepseek_adapter_mode(options.vibe_trading_deepseek_adapter)
        if adapter_mode != "openai-compatible" and native_package_version not in {None, "not_installed"}:
            adapter_type = "native"

    return {
        "provider": caps.name if provider in {"kimi", "openai_codex"} else provider,
        "model": model,
        "backend": snapshot.backend,
        "base_url": _redact_base_url_for_log(base_url),
        "api_key": {key_env: _redact_env_flag(key_env, environment)} if key_env else {},
        "http_header_env": {
            "authorization": {
                "source": credential_source,
                **_header_value_diagnostic(snapshot.api_key),
            },
            "ambient_openai": {
                name: _header_value_diagnostic(environment.get(name, ""))
                for name in _AMBIENT_OPENAI_HEADER_ENV_VARS
            },
        },
        "env": {
            "LANGCHAIN_PROVIDER": _redact_env_flag("LANGCHAIN_PROVIDER", environment),
            "LANGCHAIN_MODEL_NAME": _redact_env_flag("LANGCHAIN_MODEL_NAME", environment),
            "OPENAI_API_KEY": _redact_env_flag("OPENAI_API_KEY", environment),
            "OPENAI_BASE_URL": _redact_base_url_for_log(environment.get("OPENAI_BASE_URL")),
            "OPENAI_API_BASE": _redact_base_url_for_log(environment.get("OPENAI_API_BASE")),
        },
        "proxy": {
            name: _redact_proxy_url(
                name,
                environment.get(name),
            )
            for name in proxy_names
            if environment.get(name)
        },
        "packages": {name: _package_version(name) for name in package_names},
        "timeout_seconds": options.timeout_seconds,
        "max_retries": options.max_retries,
        "tool_policy": policy.status(legacy_defaults=snapshot.backend == "claude_cli"),
        "reasoning_effort": options.langchain_reasoning_effort.strip().lower(),
        "adapter": {
            "type": adapter_type,
            "mode": adapter_mode,
            "native_package": caps.native_adapter_package,
            "native_package_version": native_package_version,
        },
        "capabilities": {
            "capture_reasoning": caps.capture_reasoning,
            "send_reasoning_content": caps.send_reasoning_content,
            "gemini_thought_signatures": caps.gemini_thought_signatures,
            "openrouter_reasoning_body": caps.openrouter_reasoning_body,
            "top_level_reasoning_effort": (
                adapter_type == "openai-compatible"
                and _sends_top_level_reasoning_effort(caps, model, snapshot.base_url)
            ),
        },
    }


def _redact_provider_error(message: str) -> str:
    """Redact configured secret/proxy values from provider errors."""
    redacted = message
    sensitive_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "PROXY")
    for key, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if any(marker in key.upper() for marker in sensitive_markers):
            redacted = redacted.replace(value, "[redacted]")
    return redacted
