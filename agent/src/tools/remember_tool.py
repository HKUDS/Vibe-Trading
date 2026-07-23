"""Remember tool: LLM-initiated persistent memory operations (save / recall / forget / reinforce)."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.memory.lifecycle import MemoryLifecycle
from src.memory.persistent import PersistentMemory


class RememberTool(BaseTool):
    """Save, recall, or forget cross-session memories.

    Memories persist to ~/.vibe-trading/memory/ and survive across sessions.
    """

    name = "remember"
    description = (
        "Persistent cross-session memory. "
        "save: store user preferences, strategy insights, or project context. "
        "recall: search past memories by keyword. "
        "forget: remove a memory by title. "
        "reinforce: provide quality feedback on a memory."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "recall", "forget", "reinforce"],
                "description": "save | recall | forget | reinforce",
            },
            "title": {
                "type": "string",
                "description": "Memory title (for save/forget)",
            },
            "content": {
                "type": "string",
                "description": "Memory content (for save)",
            },
            "memory_type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": "Memory category (default: project)",
            },
            "query": {
                "type": "string",
                "description": "Search query (for recall)",
            },
            "event": {
                "type": "string",
                "enum": ["task_success", "task_failure", "user_confirm", "user_reject"],
                "description": "Feedback event type (for reinforce)",
            },
            "source": {
                "type": "string",
                "enum": ["user", "system"],
                "description": "Feedback source: user (full confidence) or system (discounted). Default: system",
            },
        },
        "required": ["action"],
    }
    repeatable = True

    def __init__(self, memory: PersistentMemory | None = None) -> None:
        """Initialize RememberTool.

        Args:
            memory: PersistentMemory instance (auto-created if omitted).
        """
        self._memory = memory or PersistentMemory()
        self._lifecycle = MemoryLifecycle(self._memory)

    def execute(self, **kwargs: Any) -> str:
        """Execute a memory action.

        Args:
            **kwargs: Must include action; other params depend on action.

        Returns:
            JSON result string.
        """
        action = kwargs.get("action", "save")

        if action == "save":
            return self._save(kwargs)
        if action == "recall":
            return self._recall(kwargs)
        if action == "forget":
            return self._forget(kwargs)
        if action == "reinforce":
            return self._reinforce(kwargs)
        return json.dumps({"status": "error", "error": f"Unknown action: {action}"})

    def _save(self, kwargs: dict) -> str:
        title = kwargs.get("title", "")
        content = kwargs.get("content", "")
        if not title or not content:
            return json.dumps(
                {"status": "error", "error": "title and content required"}
            )
        memory_type = kwargs.get("memory_type", "project")
        try:
            path = self._memory.add(title, content, memory_type, description=title)
        except ValueError as exc:
            return json.dumps({"status": "error", "error": str(exc)})
        if path is None:
            return json.dumps(
                {
                    "status": "skipped",
                    "message": f"Duplicate write blocked for: {title}",
                }
            )
        return json.dumps(
            {"status": "ok", "message": f"Saved: {title}", "path": str(path)}
        )

    def _recall(self, kwargs: dict) -> str:
        query = kwargs.get("query", "")
        if not query:
            return json.dumps({"status": "error", "error": "query required"})
        entries = self._memory.find_relevant(query)
        # Track access for each recalled entry so importance decay
        # reflects actual usage patterns.
        for e in entries:
            self._lifecycle.track_access(e)
        results = [
            {"title": e.title, "type": e.memory_type, "content": e.body[:2000]}
            for e in entries
        ]
        return json.dumps(
            {"status": "ok", "count": len(results), "memories": results},
            ensure_ascii=False,
        )

    def _forget(self, kwargs: dict) -> str:
        title = kwargs.get("title", "")
        if not title:
            return json.dumps({"status": "error", "error": "title required"})
        removed = self._memory.remove(title)
        msg = f"Removed: {title}" if removed else f"Not found: {title}"
        return json.dumps({"status": "ok" if removed else "not_found", "message": msg})

    def _reinforce(self, kwargs: dict) -> str:
        title = kwargs.get("title", "")
        event = kwargs.get("event", "")
        if not title or not event:
            return json.dumps({"status": "error", "error": "title and event required"})
        source = kwargs.get("source", "system")
        if source not in ("user", "system"):
            source = "system"
        success = self._lifecycle.reinforce(title, event, source)
        if success:
            return json.dumps(
                {"status": "ok", "message": f"Reinforced: {title} ({event})"}
            )
        return json.dumps(
            {"status": "skipped", "message": f"Reinforce skipped for: {title}"}
        )
