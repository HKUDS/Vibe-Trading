"""Client-facing projection of durable thread items."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.session.replay import trail_arguments
from src.session.thread_schema import ThreadItem


#: Thread item types a client is shown. ``state`` (identity ledger records,
#: loaded tools, workspace) and ``inject`` (the loop's own ``<system>``
#: directives) are runtime internals: they advance the cursor but are never
#: sent, by event or by the thread endpoint.
DISPLAY_ITEM_TYPES = frozenset(
    {"turn_start", "user", "assistant", "tool_result", "plan", "question", "compaction", "turn_end"}
)


def display_item(item: ThreadItem) -> Optional[Dict[str, Any]]:
    """Return the client view of one thread item.

    The view carries what the log holds for display and nothing the model
    alone needs: never a user item's ``llm_content`` (the ``<agent-state>``
    envelope and recalled memories), an assistant item's ``provider_items``
    or thought signatures, or any ``state`` / ``inject`` item. Tool results
    are the delivered content the log holds, which is already redacted;
    tool-call arguments are redacted here, as the live event does.

    Args:
        item: A thread item.

    Returns:
        The display dict, or None for an item type clients are not shown.
    """
    if item.type not in DISPLAY_ITEM_TYPES:
        return None
    view: Dict[str, Any] = {
        "seq": item.seq,
        "ts": item.ts,
        "turn_id": item.turn_id,
        "type": item.type,
    }
    if item.type == "turn_start":
        view.update(prompt=item.get("prompt"), model=item.get("model"), provider=item.get("provider"))
    elif item.type == "user":
        view["content"] = item.get("content")
    elif item.type == "assistant":
        view.update(
            content=item.get("content"),
            phase=item.get("phase"),
            reasoning_content=item.get("reasoning_content"),
            tool_calls=[
                {
                    "id": call.get("id"),
                    "name": (call.get("function") or {}).get("name"),
                    "arguments": trail_arguments((call.get("function") or {}).get("arguments"), None),
                }
                for call in item.get("tool_calls") or []
            ],
        )
    elif item.type == "tool_result":
        view.update(
            tool_call_id=item.get("tool_call_id"),
            name=item.get("name"),
            content=item.get("content"),
            status=item.get("status"),
            elapsed_ms=item.get("elapsed_ms"),
            artifact=item.get("artifact"),
            images=item.get("images"),
        )
    elif item.type == "plan":
        view.update(plan_id=item.get("plan_id"), steps=item.get("steps"))
    elif item.type == "question":
        view.update(question_id=item.get("question_id"), prompt=item.get("prompt"), options=item.get("options"), allow_free_text=item.get("allow_free_text"))
    elif item.type == "compaction":
        view.update(summary=item.get("summary"), replaces_through_seq=item.get("replaces_through_seq"))
    elif item.type == "turn_end":
        view.update(
            status=item.get("status"),
            usage=item.get("usage"),
            elapsed_ms=item.get("elapsed_ms"),
            summary=item.get("summary"),
            error=item.get("error"),
            run_dir=item.get("run_dir"),
            provider=item.get("provider"),
            model=item.get("model"),
            pending_inputs=item.get("pending_inputs"),
            display=item.get("display"),
        )
    return view


def display_page(
    items: List[ThreadItem],
    *,
    after: int = 0,
    before: Optional[int] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """Page a thread's display items by seq.

    Args:
        items: The thread's items in write order.
        after: Return items with ``seq > after``, oldest first.
        before: When given, return the ``limit`` newest items with
            ``after < seq < before`` instead (for loading history backwards).
        limit: Maximum number of items.

    Returns:
        ``items``, ``has_more`` (more items beyond the page in the paging
        direction) and ``cursor``: the highest seq in the log, which a client
        passes to the event stream to continue live from this read.
    """
    shown = [
        view for view in (display_item(item) for item in items if item.seq > after)
        if view is not None and (before is None or view["seq"] < before)
    ]
    return {
        "items": shown[:limit] if before is None else shown[-limit:],
        "has_more": len(shown) > limit,
        "cursor": max((item.seq for item in items), default=0),
    }
