"""Built-in LLM vision OCR engine — works with any OpenAI-compatible provider
that has a vision-capable model.

Provider config (base_url, api_key) is resolved via the existing
``provider_env_names()`` function in ``src/providers/capabilities.py``,
which already covers 18+ providers. No separate provider mapping is needed.

Vision capability is not gated. ``is_available()`` returns True if an API
key is configured — the model may or may not support vision, but a failed
API call is clearer feedback than silently refusing to OCR. If the user
explicitly sets ``VIBE_TRADING_OCR_LLM_MODEL``, that choice is trusted.
"""

from __future__ import annotations

import base64
import io
import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

# OCR system prompt design decisions:
# - HTML tables for complex layouts (Markdown can't express merged cells)
# - LaTeX with \( \) and \[ \] delimiters (avoids $ currency conflict)
# - No Unicode math symbols (∈ → \in) — forces portable LaTeX output
# - [unclear] for partial, [illegible] for complete unreadability
# - Reading order preservation for multi-column layouts

_OCR_SYSTEM_PROMPT = """\
You are a high-fidelity document OCR engine. Extract ALL text and structured \
content from the provided image with maximum accuracy.

## Output Format

Output clean Markdown with the following rules:

1. **Reading order**: Follow natural reading order (top-to-bottom, \
left-to-right). For multi-column layouts, read each column fully before \
moving to the next.

2. **Headings and text**: Use `#`, `##`, `###` for headings matching the \
original hierarchy. Use `**bold**` and `*italic*` where the original does. \
Use `- ` or `1. ` for lists.

3. **Tables**: For simple tables, use Markdown pipe tables (`| col |`). \
For tables with merged cells (colspan/rowspan), use HTML `<table>` with \
`colspan` and `rowspan` attributes — Markdown cannot express cell merging.

4. **Mathematical formulas**: Use LaTeX with `\\(...\\)` for inline and \
`\\[...\\]` for display formulas. Do NOT use Unicode math symbols \
(e.g., write `\\in` not `∈`, `\\subset` not `⊂`). Use `\\alpha`, \
`\\beta`, `\\sum` etc. for Greek letters and operators.

5. **Figures and charts**: Insert a placeholder: \
`[FIGURE: brief description of what the figure shows]`. Do NOT attempt to \
describe or interpret figure contents beyond a one-line caption.

6. **Headers and footers**: Wrap in `[HEADER: ...]` and `[FOOTER: ...]`.

7. **Handwriting**: Transcribe in `[HANDWRITTEN: ...]`.

8. **Watermarks and stamps**: Note in `[WATERMARK: ...]` or `[STAMP: ...]`.

9. **Unclear text**: If partially unreadable, output your best guess \
followed by `[?]`. If completely illegible, output `[illegible]`. \
Never guess or hallucinate text you cannot see.

10. **No commentary**: Output ONLY extracted content. No summaries, \
explanations, or meta-comments.

11. **Empty pages**: If no readable text, output an empty string.

12. **Preserve language**: Output in the same language(s) as the original. \
Do not translate.

## Critical Constraints

- Do NOT hallucinate text not visible in the image.
- Do NOT skip any text — include small print, footnotes, and annotations.
- Do NOT merge separate text blocks into one paragraph.
- Do NOT reorder content — follow the original layout.
- Do NOT correct apparent typos in the original.
"""

_OCR_USER_PROMPT = "Extract all text and structured content from this image."

# Vision models are 3-10x slower than text-only; 90s covers network latency
# and complex multi-column layouts (typical single-page OCR: 5-30s).
_OCR_TIMEOUT = 90  # seconds

# Dense A4 page ≈ 2000-4000 tokens; tables/formulas push higher.
# 8192 is a safe upper bound supported by all mainstream vision models
# (GPT-4o, Claude, Gemini, Qwen-VL).
_OCR_MAX_TOKENS = 8192

# OCR is faithful extraction requiring maximum determinism.
# Temperature 0 is the industry standard for extraction/structured-output tasks.
_OCR_TEMPERATURE = 0.0

# Industry-standard "high quality" threshold. JPEG quality ≥70 has negligible
# impact on OCR accuracy; 85 balances file size (5-10x smaller than PNG) with
# text readability. Higher values (90+) increase upload cost with marginal gain.
_OCR_JPEG_QUALITY = 85


def _resolve_provider_config() -> dict[str, str]:
    """Resolve base_url, api_key, model from the configured LLM provider.

    Provider credentials use dynamically-named env vars from
    :func:`provider_env_names` (DEEPSEEK_API_KEY, DASHSCOPE_BASE_URL,
    etc.).  These are not part of the static ``EnvConfig`` schema, so
    reads go through ``os.getenv`` directly.
    """
    from src.config.accessor import get_env_config
    from src.providers.capabilities import provider_env_names

    env = get_env_config()
    provider = env.llm.langchain_provider.strip().lower()
    model_name = env.llm.langchain_model_name.strip()

    model_override = env.ocr.vibe_trading_ocr_llm_model

    key_env, base_env = provider_env_names(provider, model_name)

    if key_env is not None:
        api_key = os.getenv(key_env, "") or os.getenv("OPENAI_API_KEY", "")  # env-gate
    else:
        # Provider unknown to provider_env_names() — fall back to OPENAI_API_KEY.
        # Ollama (a local no-auth provider) uses "ollama" as a placeholder key
        # because the OpenAI SDK requires non-empty api_key even for no-auth
        # endpoints. For any other provider, empty string is correct (the user
        # must configure it explicitly via OPENAI_API_KEY).
        if provider == "ollama":
            api_key = os.getenv("OPENAI_API_KEY", "") or "ollama"  # env-gate
        else:
            api_key = os.getenv("OPENAI_API_KEY", "")  # env-gate

    base_url = (
        (os.getenv(base_env, "") if base_env else "")  # env-gate
        or os.getenv("OPENAI_BASE_URL", "")  # env-gate
        or os.getenv("OPENAI_API_BASE", "")  # env-gate
    )

    model = model_override or model_name or ""

    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }


class LlmVisionOcrEngine:
    """Cloud OCR via any OpenAI-compatible multimodal LLM.

    Provider config is resolved via the existing ``provider_env_names()``
    function (no separate provider mapping). Vision capability is not
    gated — a failed API call is clearer feedback than silent refusal.
    """

    name = "llm-vision"
    is_cloud = True
    install_hint = (
        "LLM vision OCR requires a vision-capable model. Set "
        "LANGCHAIN_MODEL_NAME to a vision model (e.g. gpt-4o, "
        "qwen3.7-plus, gemini-2.5-flash, claude-sonnet-4) and "
        "configure the corresponding API key."
    )

    def __init__(self) -> None:
        self._client = None
        self._client_config: dict[str, str] | None = None

    def is_available(self) -> bool:
        """Available if an API key is configured."""
        try:
            from openai import OpenAI  # noqa: F401 — already a core dependency

            config = _resolve_provider_config()
            return bool(config["api_key"])
        except Exception:
            return False

    def _get_client(self, config: dict[str, str]):
        """Return a cached OpenAI client, recreating if config changed."""
        if self._client is not None and self._client_config == config:
            return self._client
        from openai import OpenAI

        self._client = OpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"] or None,
            timeout=_OCR_TIMEOUT,
        )
        self._client_config = dict(config)
        return self._client

    def recognize(self, image: np.ndarray) -> str:
        config = _resolve_provider_config()

        client = self._get_client(config)

        b64 = self._numpy_to_base64(image)

        # 1 retry for transient network errors only.
        # Deterministic failures (4xx client errors like 401/403/404/422)
        # are raised immediately to avoid 90s x 2 pointless delay.
        from openai import APIConnectionError, APITimeoutError, APIStatusError

        for attempt in range(2):
            try:
                response = client.chat.completions.create(
                    model=config["model"],
                    messages=[
                        {
                            "role": "system",
                            "content": [{"type": "text", "text": _OCR_SYSTEM_PROMPT}],
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{b64}",
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": _OCR_USER_PROMPT,
                                },
                            ],
                        },
                    ],
                    max_tokens=_OCR_MAX_TOKENS,
                    temperature=_OCR_TEMPERATURE,
                )
                text = response.choices[0].message.content or ""
                return text.strip()
            except (APITimeoutError, APIConnectionError) as exc:
                # Transient network errors — retry once.
                if attempt == 0:
                    logger.warning("OCR attempt 1 failed (transient), retrying: %s", exc)
                    continue
                logger.error(
                    "LLM vision OCR failed (%s / %s): %s",
                    config["provider"],
                    config["model"],
                    exc,
                )
                return ""
            except APIStatusError as exc:
                # 5xx server errors are transient — retry once.
                if exc.status_code >= 500 and attempt == 0:
                    logger.warning("OCR attempt 1 failed (server %d), retrying: %s", exc.status_code, exc)
                    continue
                # 4xx client errors (401, 403, 404, 422, etc.) are deterministic — raise immediately.
                logger.error(
                    "LLM vision OCR failed (%s / %s): HTTP %d — %s",
                    config["provider"],
                    config["model"],
                    exc.status_code,
                    exc,
                )
                raise
            except Exception as exc:
                # Unexpected errors — do not retry.
                logger.error(
                    "LLM vision OCR failed (%s / %s): %s",
                    config["provider"],
                    config["model"],
                    exc,
                )
                raise
        return ""

    def confidence(self, image: np.ndarray) -> float | None:
        return None

    @staticmethod
    def _numpy_to_base64(image: np.ndarray) -> str:
        """Convert numpy array to base64 JPEG (10x smaller than PNG for OCR)."""
        from PIL import Image

        pil_img = Image.fromarray(image)
        buffer = io.BytesIO()
        pil_img.save(buffer, format="JPEG", quality=_OCR_JPEG_QUALITY)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


# Self-register to built-in engine table
from src.tools.ocr.engine import register_builtin  # noqa: E402

register_builtin("llm-vision", LlmVisionOcrEngine)
