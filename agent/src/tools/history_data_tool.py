"""Bounded historical datasets through the same gateway as API and CLI."""

import json
from src.agent.tools import BaseTool


def summarize(value):
    """Keep job responses small enough for agent context; rows remain paginated."""
    if isinstance(value, dict):
        value = {
            key: item for key, item in value.items() if key not in {"chunks", "parts"} or not isinstance(item, list)
        }
    return value


class HistoryDataTool(BaseTool):
    """Plan, download, inspect and read complete long-minute datasets."""

    name = "history_data"
    description = (
        "Plan and resume large historical datasets with bounded local storage. "
        "Verified source currently BaoStock SH/SZ stocks, 5m/15m/30m/1H, settled dates, up to ten years. "
        "Plan before create; create returns a job id; start downloads in background; status checks completion. "
        "Rows requires a complete dataset and returns at most 25 unsampled rows per page. "
        "Never claim another market or a recent tail is complete multi-year history. "
        "scan_create queues background bar acquisition (explicit 1D/1W/1M interval), "
        "scan_status and scan_cancel inspect/stop it; scan jobs are process-local coverage metadata, not durable datasets. "
        "Storage returns global disk quota/retention; pin protects a dataset from automatic cleanup."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "scan_create",
                    "scan_status",
                    "scan_cancel",
                    "plan",
                    "create",
                    "start",
                    "status",
                    "rows",
                    "cancel",
                    "pin",
                    "unpin",
                    "delete",
                    "storage",
                    "prune",
                ],
            },
            "job": {"type": "string"},
            "codes": {"type": "array", "items": {"type": "string"}, "maxItems": 10000},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "interval": {"type": "string", "enum": ["5m", "15m", "30m", "1H", "1D", "1W", "1M"]},
            "offset": {"type": "integer", "minimum": 0},
        },
        "required": ["action"],
    }

    def execute(self, **kwargs):
        """Dispatch a local data operation and return a bounded JSON envelope.

        Args:
            **kwargs: Action, job identity or historical date/symbol specification.

        Returns:
            JSON with status, provenance or a complete-data row page.
        """
        from src.data_gateway.history_store import get_history_store

        store = get_history_store()
        action, job = kwargs.get("action"), kwargs.get("job")
        try:
            if action in {"scan_create", "scan_status", "scan_cancel"}:
                from src.data_gateway import get_gateway

                queue = get_gateway().scan_queue()
                if action == "scan_create":
                    result = queue.create(
                        codes=kwargs.get("codes") or [],
                        start_date=kwargs.get("start_date"),
                        end_date=kwargs.get("end_date"),
                        interval=kwargs.get("interval", "1D"),
                    )
                else:
                    result = getattr(queue, action.removeprefix("scan_"))(job)
            elif action in {"plan", "create"}:
                result = getattr(store, action)(
                    codes=kwargs.get("codes"),
                    start_date=kwargs.get("start_date"),
                    end_date=kwargs.get("end_date"),
                    interval=kwargs.get("interval", "5m"),
                )
            elif action == "rows":
                result = store.read(job, kwargs.get("offset", 0), 25)
            elif action in {"pin", "unpin"}:
                result = store.pin(job, action == "pin")
            elif action == "storage":
                result = store.settings()
            elif action == "prune":
                result = store.prune()
            elif action == "status" and job is None:
                offset = kwargs.get("offset", 0)
                if not isinstance(offset, int) or offset < 0:
                    raise ValueError("offset must be non-negative")
                jobs = store.status()
                page = [
                    {key: row.get(key) for key in ("id", "state", "pinned", "rows", "completed_chunks", "total_chunks")}
                    for row in jobs[offset : offset + 10]
                ]
                result = {
                    "jobs": page,
                    "total_jobs": len(jobs),
                    "next_offset": offset + 10 if offset + 10 < len(jobs) else None,
                }
            elif action in {"status", "start", "cancel", "delete"}:
                result = getattr(store, action)(job)
            else:
                raise ValueError("Unknown history action")
            return json.dumps({"ok": True, "data": summarize(result)}, ensure_ascii=False, allow_nan=False)
        except (ValueError, OSError) as exc:
            return json.dumps({"ok": False, "error": str(exc)[:240]})
