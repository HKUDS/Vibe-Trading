"""Fit a list of records into one tool result without dropping the tail silently.

A tool result is cut at :data:`src.config.limits.TOOL_RESULT_LIMIT` characters.
For a JSON envelope that cut lands mid-structure, so the model receives a broken
fragment and — worse — reads the records that survived as if they were the whole
answer. Measured live before this existed:
``get_financial_statements("AAPL.US", statement="income", period="quarter")``
serialized to 28,498 characters for 40 quarters and delivered roughly 12.

Records are therefore paged whole. The envelope carries a ``paging`` block
stating the total, what was returned, and where to resume, so a partial answer
is self-describing rather than indistinguishable from a complete one.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from src.config.limits import TOOL_RESULT_LIMIT


def fit_records(
    records: list[Any],
    offset: int,
    build: Callable[[list[Any], dict[str, Any]], dict[str, Any]],
    *,
    limit: int = TOOL_RESULT_LIMIT,
    max_records: int | None = None,
) -> str:
    """Serialize the largest whole-record page of ``records[offset:]`` that fits.

    Args:
        records: All available records, newest first by the caller's ordering.
        offset: Index to start the page at.
        build: Callback taking ``(page, paging_meta)`` and returning the full
            envelope dict to serialize.
        limit: Character budget for the serialized envelope.
        max_records: Optional ceiling on records per page, applied before the
            character budget.

    Returns:
        The serialized envelope, at most ``limit`` characters, containing whole
        records only.
    """
    remaining = records[offset:]
    count = len(remaining)
    if max_records is not None:
        count = min(count, max_records)

    while True:
        page = remaining[:count]
        next_offset = offset + len(page)
        meta = {
            "total": len(records),
            "offset": offset,
            "returned": len(page),
            "next_offset": None if next_offset >= len(records) else next_offset,
            "complete": next_offset >= len(records),
        }
        payload = json.dumps(build(page, meta), ensure_ascii=False)
        if len(payload) <= limit or count <= 1:
            return payload
        # Shrink proportionally to the overflow, then one further so a page of
        # unusually wide records still converges in a couple of rounds.
        count = max(1, min(count - 1, int(count * limit / len(payload))))
