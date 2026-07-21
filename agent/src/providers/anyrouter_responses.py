"""AnyRouter.top regional API-key adapter for Responses-native models.

This transport is separate from :mod:`src.providers.openai_codex`: AnyRouter
regional gateways use a normal inference API key and a dashboard-provided HTTPS
base URL, while the Codex OAuth adapter is intentionally pinned to ChatGPT's
own endpoint.
"""

from __future__ import annotations

import time
from typing import Any, Iterable
from urllib.parse import urlparse

from src.config.accessor import get_env_config
from src.providers.openai_codex import CodexAIMessage, ResponsesLLM


class AnyRouterStreamError(RuntimeError):
    """HTTP error returned by an AnyRouter.top regional gateway."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = int(status_code)
        super().__init__(f"AnyRouter Responses HTTP {self.status_code}: {detail[:500]}")


def validate_anyrouter_base_url(url: str) -> str:
    """Validate and normalize an explicit AnyRouter regional HTTPS base URL."""
    value = (url or "").strip().rstrip("/")
    if not value:
        raise ValueError(
            "AnyRouter Responses requires ANYROUTER_BASE_URL from the AnyRouter.top dashboard"
        )
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AnyRouter Responses base URL must be a credential-free HTTPS URL")
    if not parsed.path:
        return f"{value}/v1"
    return value


def anyrouter_responses_url(base_url: str) -> str:
    """Return the Responses endpoint for an AnyRouter-compatible base URL."""
    base = validate_anyrouter_base_url(base_url)
    if base.endswith("/responses"):
        return base
    return f"{base}/responses"


def anyrouter_models_url(base_url: str) -> str:
    """Return the model-discovery endpoint for an AnyRouter.top base URL."""
    base = validate_anyrouter_base_url(base_url)
    if base.endswith("/responses"):
        base = base[: -len("/responses")]
    return f"{base}/models"


class AnyRouterResponsesLLM(ResponsesLLM):
    """Responses adapter authenticated for an AnyRouter.top regional gateway."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        timeout: int = 120,
        max_retries: int = 2,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        config = get_env_config().llm
        key = (api_key or config.anyrouter_api_key).strip()
        if not key:
            raise RuntimeError("AnyRouter Responses requires ANYROUTER_API_KEY")
        configured_base = base_url or config.anyrouter_base_url
        self.api_key = key
        self.base_url = validate_anyrouter_base_url(configured_base)
        self.max_retries = max(0, int(max_retries))
        super().__init__(
            model=model,
            responses_url=anyrouter_responses_url(self.base_url),
            provider_label="AnyRouter Responses",
            temperature=temperature,
            timeout=timeout,
            tools=tools,
            reasoning_effort=reasoning_effort,
        )

    def _copy_with_tools(self, tools: list[dict[str, Any]]) -> "AnyRouterResponsesLLM":
        return AnyRouterResponsesLLM(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            timeout=self.timeout,
            max_retries=self.max_retries,
            tools=tools,
            reasoning_effort=self.reasoning_effort,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "vibe-trading (python)",
            "accept": "text/event-stream",
            "content-type": "application/json",
        }

    def _http_error(self, status_code: int, detail: str) -> RuntimeError:
        return AnyRouterStreamError(status_code, detail)

    def stream(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
    ) -> Iterable[CodexAIMessage]:
        """Retry transient pre-stream failures without replaying partial output."""
        for attempt in range(self.max_retries + 1):
            yielded_output = False
            try:
                for chunk in super().stream(messages, config=config):
                    yielded_output = True
                    yield chunk
                return
            except AnyRouterStreamError as exc:
                retryable = exc.status_code in {408, 425, 429} or exc.status_code >= 500
                if yielded_output or not retryable or attempt >= self.max_retries:
                    raise
                time.sleep(min(2**attempt, 8))
