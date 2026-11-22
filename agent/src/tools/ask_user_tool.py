"""Structured questions which pause a turn until the user answers."""
from __future__ import annotations
import json
import uuid
from typing import Any, Callable, Optional
from src.agent.tools import BaseTool
from src.tools.redaction import redact_text

class AskUserTool(BaseTool):
    name = "ask_user"
    description = "Ask one focused question with 2 to 4 options. An ordinary answer cannot grant permission or approve an order."
    parameters = {"type": "object", "properties": {"prompt": {"type": "string"}, "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}}, "allow_free_text": {"type": "boolean"}}, "required": ["prompt", "options"], "additionalProperties": False}
    repeatable = False
    is_readonly = False
    def __init__(self, default_session_id: Optional[str] = None, event_callback: Optional[Callable[[str, dict], None]] = None) -> None:
        self.session_id, self.event_callback = default_session_id, event_callback
    def execute(self, *, prompt: str, options: list[str], allow_free_text: bool = True, **_: Any) -> str:
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(options, list) or not 2 <= len(options) <= 4 or not all(isinstance(x, str) and x.strip() for x in options):
            return json.dumps({"status": "error", "error": "prompt and 2 to 4 non-empty options are required"})
        question_id = uuid.uuid4().hex
        question = {
            "question_id": question_id,
            "prompt": redact_text(prompt),
            "options": [redact_text(option) for option in options],
            "allow_free_text": bool(allow_free_text),
        }
        if self.event_callback:
            self.event_callback("item.started", {"kind": "item.started", "item": {"type": "question", **question}, "session_id": self.session_id})
        return json.dumps({"status": "waiting_user", **question}, ensure_ascii=False)
