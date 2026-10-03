"""Context-compaction and message-normalization helpers for the agent loop.

Split out of ``loop.py`` (#1624): these functions transform message lists
(``_microcompact``, ``_context_collapse``, chunked summary folding, tool-pair
repair, thought-signature attachment) and read only the constants below. No
``AgentLoop`` state, no config accessors. ``loop.py`` re-exports every public
name, so existing imports keep working.
"""

from __future__ import annotations

import copy
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


def _verification_ledger(messages: list) -> str:
    """Extract terse deterministic-verification records from a message list.

    Walks the conversation for successful financial_rigor tool results
    (the deterministic calculator/verifier) and renders each as a short
    "already verified" line. Re-attached to the compressed context after
    auto-compact so the model does not re-run identical expressions it can
    no longer see (2026-08-20 INTC run re-ran the same calcs 5-9x each
    after compaction cleared the outputs).

    Args:
        messages: Message list to scan (tool results only).

    Returns:
        Newline-joined ledger lines, or an empty string when nothing found.
    """
    lines: list[str] = []
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except Exception:  # noqa: BLE001 - non-JSON results are skipped
            continue
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            continue
        command = payload.get("command")
        if command == "calc" and payload.get("result_exact") is not None:
            expr = payload.get("expr", "?")
            result_exact = payload.get("result_exact")
            lines.append(f"calc {expr} = {result_exact}")
        elif command == "verify_market_cap" and payload.get("verdict") is not None:
            verdict = payload.get("verdict")
            deviation_pct = payload.get("deviation_pct")
            lines.append(f"market_cap verdict={verdict} dev={deviation_pct}%")
        elif command == "verify_valuation" and payload.get("metrics"):
            metrics = payload["metrics"]
            if isinstance(metrics, dict) and metrics:
                summary = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:8])
                lines.append(f"valuation {summary}")
        elif command == "cross_validate" and payload.get("all_consistent") is not None:
            field_name = payload.get("field", "?")
            all_consistent = payload.get("all_consistent")
            lines.append(f"cross_validate field={field_name} consistent={all_consistent}")
        elif command == "benford" and payload.get("reliable") is not None:
            reliable = payload.get("reliable")
            conformity = payload.get("conformity", "?")
            lines.append(f"benford reliable={reliable} conformity={conformity}")
    # Deduplicate while preserving order; cap the ledger size.
    seen: set[str] = set()
    unique: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
        if len(unique) >= 60:
            break
    return "\n".join(unique)

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


def _replay_context_result(result: str) -> str:
    """Annotate a restored readonly result with planner guidance.

    Replay exists to recover evidence that context compaction removed, not to
    trigger another fetch under slightly different freshness arguments. Keep
    the original payload intact and add a reserved metadata field when the
    result is a JSON object; non-JSON results get a short textual suffix.
    """
    notice = (
        "Exact prior successful result restored after context compaction. "
        "Treat this payload as available evidence and continue the analysis. "
        "Do not change cache/freshness arguments merely to bypass replay; "
        "request a fresh fetch only when the evidence itself is stale/cached "
        "or the task genuinely requires newer data."
    )
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return f"{result}\n\n[Replay notice: {notice}]"
    if not isinstance(payload, dict):
        return f"{result}\n\n[Replay notice: {notice}]"
    replay_payload = dict(payload)
    replay_payload["_vibe_replay"] = {
        "restored": True,
        "notice": notice,
    }
    return json.dumps(replay_payload, ensure_ascii=False)


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
    """Repair orphaned tool_call / tool_result pairs after compression.

    Two fixes:
      1. Remove tool results whose matching tool_call was compressed away.
      2. Insert stub results for tool_calls whose results were compressed away.

    Args:
        messages: Message list (mutated in place).
    """
    # Collect all tool_call IDs from assistant messages
    call_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id", "")
                if tc_id:
                    call_ids.add(tc_id)

    # Remove orphaned tool results
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "tool" and msg.get("tool_call_id") not in call_ids:
            messages.pop(i)
        else:
            i += 1

    # Collect existing result IDs
    result_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tcid = msg.get("tool_call_id", "")
            if tcid:
                result_ids.add(tcid)

    # Insert stub results for orphaned tool_calls
    inserts: list[tuple[int, dict]] = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            tc_id = tc.get("id", "")
            if tc_id and tc_id not in result_ids:
                stub = {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "content": _STUB_RESULT_CONTENT,
                }
                inserts.append((idx + 1, stub))
                result_ids.add(tc_id)

    for pos, stub in reversed(inserts):
        messages.insert(pos, stub)


def _attach_tool_call_thought_signatures(message: dict[str, Any], tool_calls: list) -> dict[str, Any]:
    """Attach Gemini thought signatures to assistant replay tool calls.

    The replay message is later converted back into LangChain messages from a
    plain dict history. Keep signatures in both the provider-neutral
    ``extra_content.thought_signature`` slot and Gemini's OpenAI-compatible
    ``extra_content.google.thought_signature`` slot so both local replay tests
    and the Gemini request injector can recover the value.
    """
    outbound_tool_calls = message.get("tool_calls")
    if not isinstance(outbound_tool_calls, list):
        return message

    signatures_by_id: dict[str, str] = {}
    signatures_by_index: dict[int, str] = {}
    for index, tc in enumerate(tool_calls):
        extra_content = getattr(tc, "extra_content", None)
        signature = None
        if isinstance(extra_content, dict):
            signature = extra_content.get("thought_signature")
            google_extra = extra_content.get("google")
            if not signature and isinstance(google_extra, dict):
                signature = google_extra.get("thought_signature") or google_extra.get(
                    "thoughtSignature"
                )
        signature = signature or getattr(tc, "thought_signature", None)
        if not signature:
            continue
        tc_id = getattr(tc, "id", None)
        if tc_id:
            signatures_by_id[str(tc_id)] = signature
        signatures_by_index[index] = signature

    if not signatures_by_id and not signatures_by_index:
        return message

    def attach(raw_tool_call: Any, index: int) -> None:
        if not isinstance(raw_tool_call, dict):
            return
        signature = signatures_by_id.get(str(raw_tool_call.get("id"))) or signatures_by_index.get(index)
        if not signature:
            return
        extra_content = raw_tool_call.setdefault("extra_content", {})
        if not isinstance(extra_content, dict):
            extra_content = {}
            raw_tool_call["extra_content"] = extra_content
        extra_content["thought_signature"] = signature
        google = extra_content.setdefault("google", {})
        if not isinstance(google, dict):
            google = {}
            extra_content["google"] = google
        google["thought_signature"] = signature

    for index, raw_tool_call in enumerate(outbound_tool_calls):
        attach(raw_tool_call, index)

    additional_kwargs = message.setdefault("additional_kwargs", {})
    raw_tool_calls = additional_kwargs.setdefault(
        "tool_calls",
        copy.deepcopy(outbound_tool_calls),
    )
    if isinstance(raw_tool_calls, list):
        for index, raw_tool_call in enumerate(raw_tool_calls):
            attach(raw_tool_call, index)

    return message


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
