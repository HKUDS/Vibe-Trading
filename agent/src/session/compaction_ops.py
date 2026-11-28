"""Message transforms and prompt templates for context compaction."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

KEEP_RECENT = 3

COLLAPSE_PRESERVE_RECENT = 6
COLLAPSE_TEXT_MIN = 2400
COLLAPSE_HEAD = 900
COLLAPSE_TAIL = 500

_STUB_RESULT_CONTENT = "[Result from earlier context — see summary above]"
_HANDOFF_SUMMARY_PREFIX = "[Conversation compressed — handoff summary."

TAIL_TOKEN_BUDGET = 20_000
SUMMARY_CHUNK_CHARS = 80_000


def _summary_chunks(msgs: list, limit: int = SUMMARY_CHUNK_CHARS) -> list[str]:
    """Serialize messages into bounded chunks for lossless summary folding."""
    if limit < 2:
        raise ValueError("summary chunk limit must be at least 2 characters")

    serialized = [json.dumps(msg, default=str, ensure_ascii=False) for msg in msgs]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 2  # The opening and closing brackets.

    def flush_current() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("[" + ", ".join(current) + "]")
            current = []
            current_len = 2

    for part in serialized:
        # Include JSON list brackets when deciding whether a message needs fragmentation.
        if len(part) + 2 <= limit:
            projected_len = current_len + len(part) + (2 if current else 0)
            if current and projected_len > limit:
                flush_current()
            current.append(part)
            current_len += len(part) + (2 if len(current) > 1 else 0)
            continue

        flush_current()

        def fragment_prefix(index: int, total: int) -> str:
            """Label a fragment of an oversized message.

            Args:
                index: One-based fragment number.
                total: Total fragments for that message.

            Returns:
                Prefix identifying the fragment as a raw JSON slice.
            """
            return (
                f"[fragment {index}/{total} of one oversized message — "
                "raw JSON slice, not valid JSON on its own]\n"
            )

        total = 1
        while True:
            capacity = limit - len(fragment_prefix(total, total))
            if capacity <= 0:
                raise ValueError(
                    "summary chunk limit is too small for an oversized-message label"
                )
            needed = max(1, (len(part) + capacity - 1) // capacity)
            if needed <= total:
                break
            total = needed

        for index in range(1, total + 1):
            prefix = fragment_prefix(index, total)
            start = (index - 1) * capacity
            chunks.append(prefix + part[start : start + capacity])

    flush_current()
    return chunks or ["[]"]


# Match the prefix because the marker includes the original length.
_CLEARED_PREFIX = "[CLEARED FROM CONTEXT:"


def _cleared_text(original_len: int) -> str:
    """Build the self-describing placeholder that replaces a pruned result."""
    return (
        f"{_CLEARED_PREFIX} this tool call SUCCEEDED and returned "
        f"{original_len} characters, which were removed to free context "
        "space. This is NOT a tool failure and NOT an empty result. If you "
        "need these values, request the same tool call again; the loop may "
        "restore the prior successful result without refetching it.]"
    )


def _is_cleared(content: Any) -> bool:
    """True when ``content`` is a layer-1 cleared-result marker."""
    return isinstance(content, str) and content.startswith(_CLEARED_PREFIX)


def _microcompact(
    messages: list,
    *,
    target_tokens: Optional[int] = None,
    measure: Optional[Callable[[list], int]] = None,
    preserve_tool_call_ids: Optional[set[str]] = None,
) -> list:
    """Layer 1: prune old tool results, keeping the most recent N intact."""
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    if len(tool_msgs) <= KEEP_RECENT:
        return []
    newly_cleared = []
    for msg in tool_msgs[:-KEEP_RECENT]:
        if target_tokens is not None and measure is not None and measure(messages) <= target_tokens:
            break
        if preserve_tool_call_ids and msg.get("tool_call_id") in preserve_tool_call_ids:
            continue
        content = msg.get("content", "")
        # Re-clearing would replace the original payload size with the marker size.
        if isinstance(content, str) and len(content) > 100 and not _is_cleared(content):
            msg["content"] = _cleared_text(len(content))
            if msg.get("name"):
                newly_cleared.append(msg["name"])
    surviving = {m.get("name") for m in tool_msgs if not _is_cleared(m.get("content"))}
    return sorted(set(newly_cleared) - surviving)


def _result_data_gone(content: Any) -> bool:
    """True when a tool result's real data is gone from context."""
    return _is_cleared(content) or content == _STUB_RESULT_CONTENT


def _context_collapse(messages: list, *, preserve_tool_call_ids: Optional[set[str]] = None) -> None:
    """Layer 2: fold long text blocks in older messages without LLM call."""
    if len(messages) <= COLLAPSE_PRESERVE_RECENT + 1:
        return
    for msg in messages[1:-COLLAPSE_PRESERVE_RECENT]:
        if msg.get("role") == "tool" and msg.get("tool_call_id") in (preserve_tool_call_ids or ()):
            continue
        content = msg.get("content")
        if not isinstance(content, str) or len(content) <= COLLAPSE_TEXT_MIN:
            continue
        # The handoff may be the only remaining copy of older context.
        if content.startswith(_HANDOFF_SUMMARY_PREFIX):
            continue
        if _result_data_gone(content):
            continue
        head = content[:COLLAPSE_HEAD]
        tail = content[-COLLAPSE_TAIL:]
        trimmed = len(content) - COLLAPSE_HEAD - COLLAPSE_TAIL
        msg["content"] = f"{head}\n\n...[{trimmed} chars collapsed]...\n\n{tail}"

    # Fold arguments only if their result was cleared, preserving call ID and name.
    cleared_ids = {
        m.get("tool_call_id")
        for m in messages
        if m.get("role") == "tool" and _result_data_gone(m.get("content"))
    }
    for msg in messages[1:-COLLAPSE_PRESERVE_RECENT]:
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function")
            if not isinstance(fn, dict):
                continue
            args = fn.get("arguments")
            if (
                isinstance(args, str)
                and len(args) > COLLAPSE_TEXT_MIN
                and tc.get("id") in cleared_ids
            ):
                fn["arguments"] = "{}"


def _msg_estimate_chars(msg: dict) -> int:
    """Rough character size of a message for token budgeting."""
    size = len(str(msg.get("content", "")))
    reasoning_content = msg.get("reasoning_content")
    if reasoning_content is not None:
        size += len(str(reasoning_content))
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function")
        if isinstance(fn, dict) and fn.get("arguments") is not None:
            size += len(str(fn["arguments"]))
    return size


def _tail_cut_index(body: list, budget: int = TAIL_TOKEN_BUDGET) -> int:
    """First index of the preserved ``body`` tail that fits ``budget`` tokens."""
    accumulated = 0
    cut_idx = len(body)
    for i in range(len(body) - 1, -1, -1):
        msg_tokens = (_msg_estimate_chars(body[i]) // 4) + 10
        if accumulated + msg_tokens > budget:
            cut_idx = i + 1
            break
        accumulated += msg_tokens
        cut_idx = i
    while 0 < cut_idx < len(body) and body[cut_idx].get("role") == "tool":
        cut_idx += 1
    return cut_idx


def _fix_tool_pairs(messages: list) -> None:
    """Repair the compacted tail in place, retaining surviving message identities."""
    from src.providers.messages import MessagePairing

    pairing = MessagePairing(_STUB_RESULT_CONTENT, missing_first=True)
    for message in messages:
        pairing.add(message)
    pairing.close_block()
    messages[:] = pairing.messages


# -- Structured summary templates ------------------------------------------

_STRUCTURED_SUMMARY_PROMPT = """\
Summarize this conversation for handoff to a fresh context window.
This summary is the ONLY context available — omitted information is lost.

Use EXACTLY this structure:

## Goal
What the user is trying to accomplish.

## Constraints & Preferences
User-stated requirements: risk tolerance, strategy parameters, asset preferences.

## Progress
### Done
- Completed steps with key results and specific numbers.
### In Progress
- Current work when compression triggered.

## Key Decisions
Choices made and rationale.

## Resolved Questions
Questions already answered — do NOT re-answer these.

## Pending User Asks
Unfinished requests still needing action.

## Relevant Files
File paths, run_dir, signal engines, artifact locations.

## Remaining Work
What still needs to be done (background reference, NOT active instructions).

## Critical Context
Specific numbers, parameters, error messages, configuration values.

## Tools & Patterns
Which tools worked, what failed, effective approaches.

IMPORTANT: This is a handoff — background reference, NOT active instructions.
Preserve ALL specific numbers, file paths, and parameter values.
{focus_section}
Conversation to summarize:
"""

_FOCUS_SECTION = """
FOCUS TOPIC: {topic}
Allocate 60-70% of the summary budget to content related to this topic.
Aggressively compress unrelated content to make room.
"""

_ITERATIVE_UPDATE_PROMPT = """\
Update the existing summary with new conversation turns.

PREVIOUS SUMMARY:
{previous_summary}

NEW TURNS TO INCORPORATE:
{new_turns}

Rules:
- PRESERVE all existing information from the previous summary.
- ADD new progress, decisions, and findings.
- Move "In Progress" items to "Done" when completed.
- Move answered questions to "Resolved Questions".
- Keep the same section structure.
- Do NOT drop any critical context from the previous summary.
{focus_section}"""
