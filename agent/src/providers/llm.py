"""LLM factory and JSON extraction helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None  # type: ignore

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None  # type: ignore


if ChatOpenAI is not None:
    class ChatOpenAIWithReasoning(ChatOpenAI):  # type: ignore[misc,valid-type]
        """ChatOpenAI that preserves provider reasoning across invoke + stream.

        langchain-openai 0.3.x drops non-standard fields in three paths:
          * _convert_dict_to_message — invoke / ainvoke (inbound)
          * _convert_delta_to_message_chunk — stream / astream (inbound)
          * _convert_message_to_dict — request serialization (outbound)
        Moonshot/DeepSeek emit `reasoning_content`; OpenRouter relays as
        `reasoning`. Inbound paths normalize to additional_kwargs["reasoning_content"];
        outbound path re-injects it so strict providers (kimi-k2.5) accept
        multi-turn continuations.
        """

        @staticmethod
        def _capture(src: Any, msg: Any) -> None:
            if value := src.get("reasoning_content") or src.get("reasoning"):
                msg.additional_kwargs["reasoning_content"] = value

        def _create_chat_result(self, response, generation_info=None):  # type: ignore[override]
            result = super()._create_chat_result(response, generation_info)
            raw = response if isinstance(response, dict) else response.model_dump()
            for gen, choice in zip(result.generations, raw["choices"]):
                self._capture(choice["message"], gen.message)
            return result

        def _convert_chunk_to_generation_chunk(  # type: ignore[override]
            self,
            chunk: dict,
            default_chunk_class: type,
            base_generation_info: Optional[dict],
        ):
            gen = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if gen is None:
                return None
            choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices")
            if choices:
                self._capture(choices[0]["delta"], gen.message)
            return gen

        def _get_request_payload(  # type: ignore[override]
            self,
            input_: Any,
            *,
            stop: Optional[list[str]] = None,
            **kwargs: Any,
        ) -> dict:
            """Re-inject reasoning_content and normalize assistant content.

            LangChain strips ``reasoning_content`` when serializing AIMessages
            back to OpenAI wire format. Moonshot kimi-k2.5 also rejects
            assistant turns where ``content`` is null or ``reasoning_content``
            is absent, breaking ReAct continuations after a tool call (#39).
            """
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            messages = super()._convert_input(input_).to_messages()
            for i, m in enumerate(payload["messages"]):
                if m.get("role") != "assistant":
                    continue
                if m.get("content") is None:
                    m["content"] = ""
                m["reasoning_content"] = messages[i].additional_kwargs.get("reasoning_content", "")
            return payload
else:
    ChatOpenAIWithReasoning = None  # type: ignore


_ANTHROPIC_STOP_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "pause_turn": "stop",
    "refusal": "content_filter",
}


def _normalize_anthropic_message(msg: Any, llm_output: Optional[Dict[str, Any]] = None) -> None:
    """Flatten Anthropic content blocks and map stop_reason → finish_reason.

    When extended thinking is enabled, ChatAnthropic returns ``content`` as a
    list of typed blocks (``{"type": "thinking", ...}``, ``{"type": "text", ...}``).
    The rest of Vibe-Trading expects ``content`` to be a string and surfaces
    chain-of-thought through ``additional_kwargs["reasoning_content"]``. Also,
    Anthropic reports the terminal condition as ``stop_reason``; the rest of
    the codebase reads ``finish_reason`` (OpenAI-style).

    Tool calls are extracted by ``ChatAnthropic._format_output`` into
    ``msg.tool_calls`` *before* this function runs, so flattening the content
    list never destroys a tool call — and we have to flatten unconditionally
    because the rest of Vibe-Trading (e.g. ``swarm/worker.py:411`` calls
    ``response.content.strip()``) assumes ``content`` is a string. On the next
    ReAct turn LangChain reconstructs the Anthropic-format content blocks
    from the string content plus ``tool_calls``.

    ``llm_output`` is the ``ChatResult.llm_output`` that ChatAnthropic emits
    alongside the message; ``stop_reason`` lives there at the point this
    function is called from ``_generate`` (BaseChatModel merges it onto the
    message a step later, but we don't want to depend on that ordering).
    """
    metadata = dict(getattr(msg, "response_metadata", None) or {})
    if llm_output:
        # Merge llm_output (read-only view) into metadata so we have stop_reason
        # available without depending on the BaseChatModel post-merge step.
        for k, v in llm_output.items():
            metadata.setdefault(k, v)

    content = getattr(msg, "content", None)
    if isinstance(content, list):
        # Always flatten — tool_use blocks have already been lifted into
        # ``msg.tool_calls`` by ChatAnthropic._format_output, so leaving them
        # in ``content`` would break the rest of Vibe-Trading, which assumes
        # ``response.content`` is a string (e.g. swarm/worker.py:411 calls
        # ``response.content.strip()``). On the next ReAct turn LangChain
        # reconstructs the Anthropic-format content list from the string
        # content + tool_calls field, so dropping the typed blocks here does
        # not break multi-turn tool use.
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            elif btype == "redacted_thinking":
                thinking_parts.append("[redacted_thinking]")
            # tool_use / input_json_delta / other typed blocks: skipped;
            # they survive via msg.tool_calls (or get aggregated by the chunk
            # __add__ path for streams).
        msg.content = "".join(text_parts)
        if thinking_parts and "reasoning_content" not in msg.additional_kwargs:
            msg.additional_kwargs["reasoning_content"] = "".join(thinking_parts)

    stop_reason = metadata.get("stop_reason")
    if stop_reason and "finish_reason" not in metadata:
        metadata["finish_reason"] = _ANTHROPIC_STOP_REASON_MAP.get(stop_reason, stop_reason)

    msg.response_metadata = metadata


if ChatAnthropic is not None:
    class ChatAnthropicWithReasoning(ChatAnthropic):  # type: ignore[misc,valid-type]
        """ChatAnthropic adapter that normalizes content + stop_reason.

        Vibe-Trading's :class:`ChatLLM` parser expects a string ``content``
        field and an OpenAI-style ``finish_reason`` in ``response_metadata``.
        Anthropic instead returns a list of typed content blocks when extended
        thinking is enabled and uses ``stop_reason``. We flatten both shapes
        here so every downstream consumer (ReAct loop, swarm worker, run-card
        writer) sees the same envelope regardless of provider.

        Hooks at ``_generate`` / ``_agenerate`` / ``_stream`` / ``_astream``
        because ChatAnthropic (langchain-anthropic 0.3.x) does not call
        ``_create_chat_result`` — it overrides ``_generate`` directly and
        emits the message via ``_format_output``.
        """

        def _generate(self, *args: Any, **kwargs: Any):  # type: ignore[override]
            result = super()._generate(*args, **kwargs)
            for gen in result.generations:
                _normalize_anthropic_message(gen.message, result.llm_output)
            return result

        async def _agenerate(self, *args: Any, **kwargs: Any):  # type: ignore[override]
            result = await super()._agenerate(*args, **kwargs)
            for gen in result.generations:
                _normalize_anthropic_message(gen.message, result.llm_output)
            return result

        def _stream(self, *args: Any, **kwargs: Any):  # type: ignore[override]
            for chunk in super()._stream(*args, **kwargs):
                # Chunks expose generation_info / response_metadata directly
                # on the chunk; pass llm_output=None — the chunk itself
                # already carries stop_reason on the terminal chunk.
                _normalize_anthropic_message(chunk.message)
                yield chunk

        async def _astream(self, *args: Any, **kwargs: Any):  # type: ignore[override]
            async for chunk in super()._astream(*args, **kwargs):
                _normalize_anthropic_message(chunk.message)
                yield chunk
else:
    ChatAnthropicWithReasoning = None  # type: ignore


AGENT_DIR = Path(__file__).resolve().parents[2]

# .env search order: ~/.vibe-trading/.env → agent/.env → $CWD/.env
_ENV_CANDIDATES = [
    Path.home() / ".vibe-trading" / ".env",
    AGENT_DIR / ".env",
    Path.cwd() / ".env",
]

_dotenv_loaded: bool = False


def _load_env_file(path: Path) -> None:
    """Load a single .env file into os.environ (setdefault, no override)."""
    if load_dotenv is not None:
        load_dotenv(dotenv_path=path, override=False)
    else:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _ensure_dotenv() -> None:
    """Load `.env` from the first found candidate path."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    for candidate in _ENV_CANDIDATES:
        if candidate.exists():
            _load_env_file(candidate)
            break
    _dotenv_loaded = True


def _sync_provider_env() -> None:
    """Map provider-specific env vars to OPENAI_* for ChatOpenAI.

    Each entry: provider_name -> (api_key_env, base_url_env).
    All base URLs must be set explicitly in .env — no hardcoded defaults.
    api_key_env=None means no key required (e.g. Ollama local).
    """
    _ensure_dotenv()
    provider = os.getenv("LANGCHAIN_PROVIDER", "openai").lower()

    if provider in {"openai-codex", "openai_codex"}:
        codex_url = os.getenv("OPENAI_CODEX_BASE_URL", "https://chatgpt.com/backend-api/codex/responses")
        os.environ["OPENAI_API_BASE"] = codex_url
        os.environ["OPENAI_BASE_URL"] = codex_url
        os.environ.pop("OPENAI_API_KEY", None)
        return

    if provider in {"anthropic", "claude"}:
        # ChatAnthropic reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL itself; do
        # not project the Anthropic key into OPENAI_API_KEY so it cannot leak
        # to OpenAI-compatible clients on a later provider switch within the
        # same process.
        base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
        if base_url:
            os.environ.setdefault("ANTHROPIC_API_URL", base_url)
        return

    # (api_key_env, base_url_env)
    _PROVIDER_MAP: dict[str, tuple[str | None, str]] = {
        "openai":     ("OPENAI_API_KEY",     "OPENAI_BASE_URL"),
        "openrouter": ("OPENROUTER_API_KEY",  "OPENROUTER_BASE_URL"),
        "deepseek":   ("DEEPSEEK_API_KEY",    "DEEPSEEK_BASE_URL"),
        "gemini":     ("GEMINI_API_KEY",      "GEMINI_BASE_URL"),
        "groq":       ("GROQ_API_KEY",        "GROQ_BASE_URL"),
        "dashscope":  ("DASHSCOPE_API_KEY",   "DASHSCOPE_BASE_URL"),
        "qwen":       ("DASHSCOPE_API_KEY",   "DASHSCOPE_BASE_URL"),
        "zhipu":      ("ZHIPU_API_KEY",       "ZHIPU_BASE_URL"),
        "moonshot":   ("MOONSHOT_API_KEY",    "MOONSHOT_BASE_URL"),
        "minimax":    ("MINIMAX_API_KEY",     "MINIMAX_BASE_URL"),
        "mimo":       ("MIMO_API_KEY",        "MIMO_BASE_URL"),
        "zai":        ("ZAI_API_KEY",         "ZAI_BASE_URL"),
        "ollama":     (None,                  "OLLAMA_BASE_URL"),
    }

    spec = _PROVIDER_MAP.get(provider, _PROVIDER_MAP["openai"])
    key_env, base_env = spec

    # Resolve API key: provider-specific env → OPENAI_API_KEY fallback
    if key_env is not None:
        api_key = os.getenv(key_env, "") or os.getenv("OPENAI_API_KEY", "")
    else:
        api_key = os.getenv("OPENAI_API_KEY", "") or "ollama"

    # Resolve base URL: provider-specific env → OPENAI_BASE_URL fallback
    base_url = os.getenv(base_env, "") or os.getenv("OPENAI_BASE_URL", "") or os.getenv("OPENAI_API_BASE", "")

    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
    if base_url:
        os.environ["OPENAI_API_BASE"] = base_url
        os.environ.setdefault("OPENAI_BASE_URL", base_url)


def build_llm(*, model_name: Optional[str] = None, callbacks: Any = None) -> Any:
    """Construct a ChatOpenAI instance.

    Args:
        model_name: Model name; defaults to LANGCHAIN_MODEL_NAME.
        callbacks: Optional LangChain callbacks.

    Returns:
        ChatOpenAI instance.

    Raises:
        RuntimeError: If langchain-openai is missing or LANGCHAIN_MODEL_NAME is unset.
    """
    _sync_provider_env()
    name = model_name or os.getenv("LANGCHAIN_MODEL_NAME", "").strip()
    if not name:
        raise RuntimeError("LANGCHAIN_MODEL_NAME is not set")
    temperature = float(os.getenv("LANGCHAIN_TEMPERATURE", "0.0"))
    provider = os.getenv("LANGCHAIN_PROVIDER", "openai").lower()
    if provider in {"openai-codex", "openai_codex"}:
        from src.providers.openai_codex import OpenAICodexLLM

        effort = os.getenv("LANGCHAIN_REASONING_EFFORT", "").strip().lower()
        return OpenAICodexLLM(
            model=name,
            temperature=temperature,
            timeout=int(os.getenv("TIMEOUT_SECONDS", "120")),
            reasoning_effort=effort or None,
        )

    if provider in {"anthropic", "claude"}:
        if ChatAnthropicWithReasoning is None:
            raise RuntimeError(
                "langchain-anthropic is not installed. Run: pip install langchain-anthropic"
            )
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (required for the anthropic provider)")
        kwargs: Dict[str, Any] = {
            "model": name,
            "temperature": temperature,
            "timeout": int(os.getenv("TIMEOUT_SECONDS", "120")),
            "max_retries": int(os.getenv("MAX_RETRIES", "2")),
            "api_key": api_key,
            "callbacks": callbacks,
        }
        base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
        if base_url:
            kwargs["base_url"] = base_url
        max_tokens = os.getenv("ANTHROPIC_MAX_TOKENS", "").strip()
        if max_tokens:
            kwargs["max_tokens"] = int(max_tokens)
        effort = os.getenv("LANGCHAIN_REASONING_EFFORT", "").strip().lower()
        if effort and effort != "none":
            # Per docs.anthropic.com (Models overview), Claude Opus 4.7 supports
            # ``adaptive thinking`` but NOT ``extended thinking`` — the
            # ``thinking={type:enabled}`` kwarg only applies to Sonnet 4.6 +
            # Haiku 4.5 (and the 4.x legacy family). Refuse the misconfiguration
            # at build time rather than letting the API silently reject or
            # ignore the field.
            if name.startswith("claude-opus-4-7"):
                raise RuntimeError(
                    "claude-opus-4-7 does not support extended thinking — it uses "
                    "adaptive thinking automatically. Unset LANGCHAIN_REASONING_EFFORT, "
                    "or switch to claude-sonnet-4-6 / claude-haiku-4-5 for budgeted "
                    "extended thinking."
                )
            # Anthropic extended thinking is opt-in. Map effort → budget_tokens
            # so the existing LANGCHAIN_REASONING_EFFORT control plane works
            # across all providers that support a reasoning toggle.
            budget = {"low": 1024, "medium": 4096, "high": 12288, "max": 24576}.get(effort)
            if budget is not None:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
                # Extended thinking requires temperature=1.
                kwargs["temperature"] = 1.0
                # max_tokens must exceed budget_tokens.
                kwargs.setdefault("max_tokens", budget + 4096)
        return ChatAnthropicWithReasoning(**kwargs)

    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed")
    # MiniMax requires temperature in (0.0, 1.0] — clamp to 0.01 when the
    # default 0.0 is used to avoid an API validation error.
    if provider == "minimax" and temperature <= 0.0:
        temperature = 0.01
    # Optional reasoning activation for relays requiring opt-in (e.g. OpenRouter).
    # Moonshot/DeepSeek official APIs emit reasoning by default and ignore this field.
    effort = os.getenv("LANGCHAIN_REASONING_EFFORT", "").strip().lower()
    return ChatOpenAIWithReasoning(
        model=name,
        temperature=temperature,
        timeout=int(os.getenv("TIMEOUT_SECONDS", "120")),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        callbacks=callbacks,
        extra_body={"reasoning": {"effort": effort}} if effort else None,
    )


def _extract_balanced_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract the outermost JSON object from text using bracket balancing.

    Args:
        text: Text that may embed a JSON object.

    Returns:
        Parsed dict, or None on failure.
    """
    start = -1
    depth = 0
    in_string = False
    escape = False

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
    return None
