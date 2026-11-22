"""Build canonical thread fixtures from the evaluator's diagnostic vocabulary."""
import json
from pathlib import Path

from src.session.thread import ThreadItem, diagnostic_records


def write_records(path: Path, records: list[dict]) -> None:
    items = []
    turn = "fixture"
    for record in records:
        kind = record["type"]
        data = dict(record)
        data.pop("type")
        if kind == "start":
            turn = f"turn-{len(items)}"
            payload = {"type": "turn_start", "prompt": data.get("prompt", "")}
        elif kind == "message" and data.get("role") == "user":
            payload = {"type": "user", "content": data["content"], "llm_content": data["content"]}
        elif kind == "tool_call":
            payload = {"type": "assistant", "content": "", "tool_calls": [{"id": data["call_id"], "type": "function", "function": {"name": data["tool"], "arguments": json.dumps(data.get("args", {}))}}]}
            items.append({**payload, "seq": len(items) + 1, "ts": 1, "turn_id": turn})
            payload = {"type": "event", "name": "tool_execution", "data": {k: v for k, v in data.items() if k != "args"}}
        elif kind == "tool_result":
            payload = {"type": "tool_result", "name": data["tool"], "tool_call_id": data["call_id"], "content": data.get("result", ""), "status": data["status"]}
        else:
            payload = {"type": "event", "name": kind, "data": data}
        items.append({**payload, "seq": len(items) + 1, "ts": 1, "turn_id": turn})
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items), encoding="utf-8")


def read_records(path: Path) -> list[dict]:
    return diagnostic_records([ThreadItem.from_dict(json.loads(line)) for line in path.read_text().splitlines()])
