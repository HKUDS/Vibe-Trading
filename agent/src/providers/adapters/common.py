"""SDK client ownership and endpoint-scoped capability keys."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from packaging.version import InvalidVersion, Version


def _endpoint_model(client: Any) -> tuple[str, str, str]:
    """Scope learned wire behavior to a protocol, endpoint and model."""
    openai = hasattr(client, "model_name")
    return (
        "openai" if openai else "anthropic",
        str(getattr(client, "openai_api_base" if openai else "anthropic_api_url", "") or "").rstrip("/"),
        str(client.model_name if openai else client.model),
    )


def _default_async_client_is_instance_owned(package: str, first_version: str) -> bool:
    """Return whether LangChain creates a default async client per model."""
    try:
        return Version(version(package)) >= Version(first_version)
    except (InvalidVersion, PackageNotFoundError):
        return False
