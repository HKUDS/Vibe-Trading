"""Message transforms and prompt templates for context compaction."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

KEEP_RECENT = 3

COLLAPSE_PRESERVE_RECENT = 6
COLLAPSE_TEXT_MIN = 2400
COLLAPSE_HEAD = 900
COLLAPSE_TAIL = 500

# The stub ``_fix_tool_pairs`` inserts for a call whose result a layer-3 fold
# consumed. The other "data is gone" placeholder is layer 1's cleared marker,
# which is not a constant — it embeds the original payload length, so it is
# built by ``_cleared_text`` and matched by ``_is_cleared``.
_STUB_RESULT_CONTENT = "[Result from earlier context — see summary above]"
_HANDOFF_SUMMARY_PREFIX = "[Conversation compressed — handoff summary."

TAIL_TOKEN_BUDGET = 20_000
SUMMARY_CHUNK_CHARS = 80_000


def _summary_chunks(msgs: list, limit: int = SUMMARY_CHUNK_CHARS) -> list[str]:
    """Serialize messages into bounded chunks for lossless summary folding.

    Messages are packed by whole-message boundaries so that ordinary chunks
    remain valid JSON arrays and a summary call never receives a message that
    was silently cut off. A single oversized message is split into explicitly
    labeled raw-JSON fragments instead: the label tells the summarizer that a
    fragment is not valid JSON by itself, while retaining every character
    instead of dropping or silently truncating part of the conversation.

    Args:
        msgs: Messages to serialize and divide into chunks.
        limit: Maximum number of characters allowed in each returned chunk.

    Returns:
        JSON-array strings, or labeled raw-JSON fragments for an oversized
        message, each no longer than ``limit`` characters.

    Raises:
        ValueError: If ``limit`` cannot accommodate an empty JSON array or an
            oversized-message fragment label.
    """
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
        # The two brackets are part of the chunk, so a message that only fits
        # below ``limit`` as a raw JSON string may still need fragmentation.
        if len(part) + 2 <= limit:
            projected_len = current_len + len(part) + (2 if current else 0)
            if current and projected_len > limit:
                flush_current()
            current.append(part)
            current_len += len(part) + (2 if len(current) > 1 else 0)
            continue

        flush_current()

        def fragment_prefix(index: int, total: int) -> str:
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


# Marker written over a tool result whose payload layer 1 removed. Matched by
# PREFIX because the text carries the original length, so no two cleared
# results are the same string; never compare a content to it with ``==``.
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
    """Layer 1: prune old tool results, keeping the most recent N intact.

    Args:
        messages: Message list (mutated in place).
        target_tokens: Stop clearing, oldest first, once ``measure(messages)``
            is at or below this. ``None`` clears every result but the last
            ``KEEP_RECENT`` — clearing everything a cross-sectional question
            still needs is what made it re-fetch its evidence until
            ``no_progress``, so the loop passes a target.
        measure: Prompt-size function for ``target_tokens``.
        preserve_tool_call_ids: Replayed results no successful model request
            has carried yet; they are never cleared here.

    Returns:
        Names of tools whose every result just became unreadable (legacy
        helper contract). The loop reconciles its dedup ledger separately by
        exact successful call identity, not by these tool names.
    """
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
        # Skip a result already cleared: the marker is itself >100 chars, so
        # re-clearing it would rewrite the recorded original size with the
        # MARKER's length ("returned 287 characters") and re-report the tool
        # as newly unreadable on every later pass.
        if isinstance(content, str) and len(content) > 100 and not _is_cleared(content):
            # A bare "[cleared]" is indistinguishable from a tool that
            # returned nothing, so the model reports "no data was retrieved"
            # for data it did receive and this layer then deleted. Say which
            # it is, and say the result is recoverable.
            msg["content"] = _cleared_text(len(content))
            if msg.get("name"):
                newly_cleared.append(msg["name"])
    # Identified by prefix, not equality: the marker carries the original
    # length, so every cleared result is a different string.
    surviving = {m.get("name") for m in tool_msgs if not _is_cleared(m.get("content"))}
    return sorted(set(newly_cleared) - surviving)


def _result_data_gone(content: Any) -> bool:
    """True when a tool result's real data is gone from context.

    Two sources, and they must both be recognised: layer 1 overwrites an old
    result with the ``_CLEARED_PREFIX`` marker, and ``_fix_tool_pairs``
    inserts ``_STUB_RESULT_CONTENT`` for a call whose result a layer-3 fold
    consumed. The marker is matched by prefix, never equality — it embeds the
    original payload length, so no two cleared results are the same string.
    """
    return _is_cleared(content) or content == _STUB_RESULT_CONTENT


def _context_collapse(messages: list, *, preserve_tool_call_ids: Optional[set[str]] = None) -> None:
    """Layer 2: fold long text blocks in older messages without LLM call.

    Preserves head + tail of large text, collapses the middle.
    Zero API cost — pure string operation.

    Args:
        messages: Message list (mutated in place).
    """
    if len(messages) <= COLLAPSE_PRESERVE_RECENT + 1:
        return
    for msg in messages[1:-COLLAPSE_PRESERVE_RECENT]:
        if msg.get("role") == "tool" and msg.get("tool_call_id") in (preserve_tool_call_ids or ()):
            continue
        content = msg.get("content")
        if not isinstance(content, str) or len(content) <= COLLAPSE_TEXT_MIN:
            continue
        # The handoff summary is the only surviving copy of older context
        # after layer 3.  Layer 2 must leave it intact for the next turn.
        if content.startswith(_HANDOFF_SUMMARY_PREFIX):
            continue
        if _result_data_gone(content):
            continue
        head = content[:COLLAPSE_HEAD]
        tail = content[-COLLAPSE_TAIL:]
        trimmed = len(content) - COLLAPSE_HEAD - COLLAPSE_TAIL
        msg["content"] = f"{head}\n\n...[{trimmed} chars collapsed]...\n\n{tail}"

    # Zero-cost relief for oversized tool-call payloads whose paired result
    # was already compacted away (``[cleared]``): the arguments blob is now
    # useless to the model (the data it requested is gone), so fold it to a
    # valid JSON stub. The call id/name survive, so tool pairing and the
    # model's "I called tool X" memory are intact, and the provider still
    # receives well-formed ``arguments``. Nothing re-reads historical
    # arguments for re-dispatch, so this is safe.
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
    """Rough character size of a message for token budgeting.

    Sizes ``content`` plus ``reasoning_content`` plus every tool-call
    ``arguments`` payload. Assistant tool-call messages carry their payload in
    ``tool_calls[].function.arguments`` with empty ``content``; sizing them by
    content alone made the layer-3 tail budget count a 100 KB arguments blob
    as ~10 tokens. A thinking-model turn's ``reasoning_content`` (Kimi K2.5,
    DeepSeek reasoner, Qwen thinking) is the same failure mode: ``estimate_tokens``
    counts it via full JSON serialization, so leaving it out here undercounts
    the tail relative to the trigger that decided compaction was needed.
    """
    size = len(str(msg.get("content", "")))
    reasoning_content = msg.get("reasoning_content")
    if reasoning_content is not None:
        size += len(str(reasoning_content))
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function")
        if isinstance(fn, dict) and fn.get("arguments") is not None:
            # Sized via ``str`` (matches ``estimate_tokens``' full-serialization
            # gate) so dict/object arguments count instead of being ignored.
            size += len(str(fn["arguments"]))
    return size


def _tail_cut_index(body: list, budget: int = TAIL_TOKEN_BUDGET) -> int:
    """First index of the preserved ``body`` tail that fits ``budget`` tokens.

    Walks back from the end accumulating each message's estimated tokens and
    returns the earliest index that fits, never splitting a tool_call /
    tool_result pair. Sized with ``_msg_estimate_chars`` so oversized tool-call
    arguments push their message into the folded head instead of being counted
    as a handful of tokens in the preserved tail.
    """
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
