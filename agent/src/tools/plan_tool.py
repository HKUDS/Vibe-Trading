"""Durable short plans shown in the conversation."""
from __future__ import annotations
import json
import uuid
from typing import Any, Callable, Optional
from src.agent.tools import BaseTool
from src.tools.redaction import redact_text

class PlanTool(BaseTool):
    name = "plan"
    description = "Maintain a short visible plan. Do not use this for a single-step question."
    parameters = {"type": "object", "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "object", "properties": {"step": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]}}, "required": ["step", "status"], "additionalProperties": False}}}, "required": ["steps"], "additionalProperties": False}
    repeatable = True
    is_readonly = False
    def __init__(self, default_session_id: Optional[str] = None, event_callback: Optional[Callable[[str, dict], None]] = None) -> None:
        self.session_id, self.event_callback = default_session_id, event_callback
    def execute(self, *, steps: list[dict[str, str]], **_: Any) -> str:
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            return json.dumps({"status": "error", "error": "steps must contain 1 to 12 items"})
        normalized = []
        for item in steps:
            if not isinstance(item, dict) or not isinstance(item.get("step"), str) or item.get("status") not in {"pending", "in_progress", "completed", "cancelled"}:
                return json.dumps({"status": "error", "error": "each step needs step and a valid status"})
            normalized.append({"step": redact_text(item["step"]), "status": item["status"]})
        plan_id = uuid.uuid4().hex
        if self.event_callback:
            self.event_callback("item.started", {"kind": "item.started", "item": {"type": "plan", "plan_id": plan_id, "steps": normalized}, "session_id": self.session_id})
        return json.dumps({"status": "ok", "plan_id": plan_id, "steps": normalized}, ensure_ascii=False)
