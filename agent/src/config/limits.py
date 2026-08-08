"""Shared runtime limits for tool results.

The cap on a tool result used to live in :mod:`src.agent.loop` and was copied as
a bare literal into :mod:`src.swarm.worker`, so the two could drift. It lives
here instead: a leaf module with no imports of its own, which the agent loop,
the swarm worker and individual tools can all read without any of them taking a
dependency on the others.
"""

from __future__ import annotations

#: Maximum characters of a single tool result handed back to the model.
TOOL_RESULT_LIMIT = 10_000

_TRUNCATION_NOTICE = (
    "\n\n[TRUNCATED: {shown} of {total} characters delivered. The remainder was "
    "not sent. Do not treat this as the complete result — narrow the request, "
    "or call the tool again with its paging parameter if it has one.]"
)


def truncate_tool_result(result: str, limit: int = TOOL_RESULT_LIMIT) -> str:
    """Cut an oversized tool result to ``limit`` characters and say so.

    A silent cut is indistinguishable from a complete answer, so the model
    reports a prefix as if it were the whole thing. Measured on live data,
    ``get_financial_statements("AAPL.US", period="quarter")`` returns 28,498
    characters for 40 periods; the silent cut delivered roughly 12 of them.

    Args:
        result: The full tool result.
        limit: Maximum characters to deliver, notice included.

    Returns:
        ``result`` unchanged when it fits, otherwise a prefix of exactly
        ``limit`` characters or fewer, ending in a notice that states how much
        was withheld.
    """
    total = len(result)
    if total <= limit:
        return result
    notice = _TRUNCATION_NOTICE.format(shown=limit, total=total)
    body = limit - len(notice)
    if body <= 0:
        # Pathologically small limit: the notice alone is more useful than a
        # fragment, so deliver it rather than silently cutting to nothing.
        return notice[:limit]
    return result[:body] + _TRUNCATION_NOTICE.format(shown=body, total=total)
