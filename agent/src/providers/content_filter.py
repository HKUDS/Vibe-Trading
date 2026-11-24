"""Content-filter resilience helpers shared by AgentRuntime and swarm worker."""

from __future__ import annotations


from src.config.accessor import get_env_config

CONTENT_FILTER_WARNING_THRESHOLD_ENV = "CONTENT_FILTER_WARNING_THRESHOLD"
DEFAULT_CONTENT_FILTER_THRESHOLD = 0.05

# Stop repeated moderation blocks before they consume the iteration budget.
MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS = 10

CONTENT_FILTER_SKIP_MESSAGE = (
    "[SYSTEM] The previous response was blocked by content "
    "moderation. Skip the current item and continue with the "
    "next one. Do not retry the same content."
)

# Recognize Gemini enum values passed through OpenAI-compatible endpoints (#307).
GEMINI_SAFETY_FINISH_REASONS = frozenset({
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
})


def is_content_filter_triggered(finish_reason: object) -> bool:
    """Return True when ``finish_reason`` indicates content moderation blocked the response."""
    if not isinstance(finish_reason, str):
        return False
    if finish_reason == "content_filter":
        return True
    return finish_reason.upper() in GEMINI_SAFETY_FINISH_REASONS


def get_content_filter_threshold() -> float:
    """Return the configured content-filter warning threshold."""
    return get_env_config().agent_tuning.content_filter_warning_threshold


def compute_content_filter_warnings(
    content_filter_count: int,
    total_iterations: int,
) -> list[str]:
    """Compute content-filter warnings based on the hit ratio."""
    if content_filter_count == 0:
        return []
    denominator = max(1, total_iterations)
    ratio = content_filter_count / denominator
    threshold = get_content_filter_threshold()
    if ratio > threshold:
        return [
            f"{content_filter_count}/{denominator} LLM responses"
            f" ({ratio:.0%}) were blocked by content moderation."
            " Consider switching to a provider with less aggressive"
            " filtering for event-driven analysis."
        ]
    return []
