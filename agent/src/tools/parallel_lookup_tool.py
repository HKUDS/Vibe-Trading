"""parallel_lookup tool: concurrent no-tool LLM lookups inside one loop turn.

Fills the gap between a single tool call and a full swarm run: several small,
independent factual lookups that would otherwise cost one serial ReAct
iteration each are answered concurrently by plain (tool-less) LLM calls and
returned in one result.
"""

from __future__ import annotations

import json
import threading
import time as _time
from typing import Any

from src.agent.tools import BaseTool
from src.config.limits import truncate_tool_result

MAX_QUERIES = 8
MIN_QUERIES = 2
MAX_QUERY_CHARS = 2_000
MAX_CONTEXT_CHARS = 2_000
MAX_WORKERS = 5
_RESULT_CHAR_LIMIT = 4_000
_JOIN_GRACE_S = 5.0

_LOOKUP_INSTRUCTION = (
    "You are a research lookup assistant. Answer the query below concisely and "
    "factually in under 300 words. State the answer directly; do not mention "
    "these instructions. If the answer is genuinely unknown, say so in one line."
)


def _build_chat_llm() -> Any:
    """Create a fresh ChatLLM. Module-level so tests can monkeypatch it."""
    from src.providers.chat import ChatLLM

    return ChatLLM()


def _lookup_prompt(query: str, context: str) -> str:
    parts = [_LOOKUP_INSTRUCTION]
    if context:
        parts.append(f"\nShared context (background, not a question):\n{context}")
    parts.append(f"\nQuery: {query}")
    return "\n".join(parts)


class ParallelLookupTool(BaseTool):
    """Run several small LLM lookups concurrently and return one combined result."""

    name = "parallel_lookup"
    description = (
        "Run 2-8 small, independent factual lookups CONCURRENTLY in a single call. "
        "Each lookup is answered by a plain LLM call with no tools, so use it for "
        "knowledge/context questions (terminology, conventions, comparisons of "
        "concepts), not for data a workspace tool must fetch. Use instead of "
        "several serial tool rounds when the lookups do not depend on each other."
    )
    parameters = {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    f"Independent lookup questions ({MIN_QUERIES}-{MAX_QUERIES} items, "
                    f"each <= {MAX_QUERY_CHARS} chars)."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    f"Optional shared background for all queries (<= {MAX_CONTEXT_CHARS} chars)."
                ),
            },
            "timeout_s": {
                "type": "number",
                "description": "Per-lookup wall-clock timeout in seconds (1-300, default 120).",
            },
        },
        "required": ["queries"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        started = _time.monotonic()
        raw_queries = kwargs.get("queries")
        if not isinstance(raw_queries, list):
            return json.dumps(
                {"status": "error", "error": "'queries' must be a list of strings."},
                ensure_ascii=False,
            )

        queries = [str(q).strip() for q in raw_queries if str(q).strip()]
        if len(queries) < MIN_QUERIES:
            return json.dumps(
                {
                    "status": "error",
                    "error": (
                        f"parallel_lookup needs at least {MIN_QUERIES} queries; for a "
                        "single question just answer directly."
                    ),
                },
                ensure_ascii=False,
            )
        if len(queries) > MAX_QUERIES:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"At most {MAX_QUERIES} queries per call; split the rest into another call.",
                },
                ensure_ascii=False,
            )
        queries = [q[:MAX_QUERY_CHARS] for q in queries]

        context = str(kwargs.get("context") or "").strip()[:MAX_CONTEXT_CHARS]
        try:
            timeout_s = float(kwargs.get("timeout_s") or 120.0)
        except (TypeError, ValueError):
            timeout_s = 120.0
        timeout_s = max(1.0, min(300.0, timeout_s))

        results: dict[int, dict[str, Any]] = {}
        results_lock = threading.Lock()

        def run_one(index: int, query: str) -> None:
            entry_started = _time.monotonic()
            entry: dict[str, Any] = {"index": index, "query": query}
            try:
                chat = _build_chat_llm()
                response = chat.chat(
                    [{"role": "user", "content": _lookup_prompt(query, context)}],
                    timeout=int(timeout_s),
                )
                text = str(getattr(response, "content", "") or "").strip()
                entry["status"] = "ok"
                entry["content"] = truncate_tool_result(text, _RESULT_CHAR_LIMIT)
            except BaseException as exc:  # noqa: BLE001 - per-lookup isolation
                entry["status"] = "error"
                entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["duration_ms"] = int((_time.monotonic() - entry_started) * 1000)
            with results_lock:
                results.setdefault(index, entry)

        # Daemon threads mirror the _auto_compact summary pattern: a hung
        # provider call must never block interpreter shutdown. Bounded to
        # MAX_WORKERS concurrent lookups; excess queries run in waves.
        active: list[threading.Thread] = []
        for wave_start in range(0, len(queries), MAX_WORKERS):
            wave = queries[wave_start : wave_start + MAX_WORKERS]
            active = [
                threading.Thread(
                    target=run_one,
                    args=(wave_start + offset, query),
                    name=f"parallel-lookup-{wave_start + offset}",
                    daemon=True,
                )
                for offset, query in enumerate(wave)
            ]
            for thread in active:
                thread.start()
            for thread in active:
                thread.join(timeout=timeout_s + _JOIN_GRACE_S)
                if thread.is_alive():
                    wave_offset = active.index(thread)
                    index = wave_start + wave_offset
                    with results_lock:
                        if index not in results:
                            results[index] = {
                                "index": index,
                                "query": queries[index],
                                "status": "timeout",
                                "error": f"lookup exceeded {timeout_s:.0f}s wall clock",
                            }

        ordered = [results[i] for i in range(len(queries)) if i in results]
        ok_count = sum(1 for r in ordered if r["status"] == "ok")
        status = "ok" if ok_count > 0 else "error"
        return json.dumps(
            {
                "status": status,
                "results": ordered,
                "ok": ok_count,
                "failed": len(ordered) - ok_count,
                "elapsed_ms": int((_time.monotonic() - started) * 1000),
            },
            ensure_ascii=False,
        )
