"""Client-facing projection of durable thread items."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.session.replay import trail_arguments
from src.session.thread_schema import ThreadItem


# Only these fields cross the REST/SSE boundary; state and injections stay internal.
_DISPLAY_FIELDS = {
    "turn_start": ("prompt", "model", "provider"),
    "user": ("content",),
    "assistant": ("content", "phase", "reasoning_content"),
    "tool_result": ("tool_call_id", "name", "content", "status", "elapsed_ms", "artifact", "images"),
    "plan": ("plan_id", "steps"),
    "question": ("question_id", "prompt", "options", "allow_free_text"),
    "compaction": ("summary", "replaces_through_seq"),
    "turn_end": (
        "status", "usage", "elapsed_ms", "summary", "error", "run_dir",
        "provider", "model", "pending_inputs", "display",
    ),
}
DISPLAY_ITEM_TYPES = frozenset(_DISPLAY_FIELDS)


def display_item(item: ThreadItem) -> Optional[Dict[str, Any]]:
    """Return the client view of one thread item."""
    if item.type not in DISPLAY_ITEM_TYPES:
        return None
    view: Dict[str, Any] = {
        "seq": item.seq,
        "ts": item.ts,
        "turn_id": item.turn_id,
        "type": item.type,
    }
    view.update((field, item.get(field)) for field in _DISPLAY_FIELDS[item.type])
    if item.type == "assistant":
        view["tool_calls"] = [
            {
                "id": call.get("id"),
                "name": (call.get("function") or {}).get("name"),
                "arguments": trail_arguments((call.get("function") or {}).get("arguments"), None),
            }
            for call in item.get("tool_calls") or []
        ]
    return view


def display_page(
    items: List[ThreadItem],
    *,
    after: int = 0,
    before: Optional[int] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """Page a thread's display items by seq."""
    shown = [
        view for view in (display_item(item) for item in items if item.seq > after)
        if view is not None and (before is None or view["seq"] < before)
    ]
    return {
        "items": shown[:limit] if before is None else shown[-limit:],
        "has_more": len(shown) > limit,
        "cursor": max((item.seq for item in items), default=0),
    }
