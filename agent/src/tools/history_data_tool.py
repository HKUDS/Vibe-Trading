"""Bounded historical datasets through the same gateway as API and CLI."""

import json
from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools._result_paging import fit_records


def row_page(value):
    """Preserve units and whole rows within the shared model-output budget."""

    def build(rows, _paging):
        symbols = {row["symbol"] for row in rows}
        next_offset = value["offset"] + len(rows)
        return {
            "ok": True,
            "data": {
                **value,
                "rows": rows,
                "provenance": {key: meta for key, meta in value["provenance"].items() if key in symbols},
                "next_offset": next_offset if next_offset < value["total_rows"] else None,
            },
        }

    encoded = fit_records(value["rows"], 0, build)
    if len(encoded) > TOOL_RESULT_LIMIT:
        raise ValueError("One row and its provenance exceed the tool limit; read this page through API or CLI")
    return encoded


def summarize(value):
    """Keep job responses small enough for agent context; rows remain paginated."""
    if isinstance(value, dict):
        value = {
            key: item for key, item in value.items() if key not in {"chunks", "parts"} or not isinstance(item, list)
        }
        if isinstance(value.get("routes"), dict) and len(value["routes"]) > 10:
            value["routes_total"] = len(value["routes"])
            value["routes_omitted"] = len(value["routes"]) - 10
            value["routes"] = dict(list(value["routes"].items())[:10])
        if isinstance(value.get("spec"), dict) and len(value["spec"].get("codes", [])) > 10:
            spec = value["spec"]
            value["spec"] = {
                **spec,
                "codes": spec["codes"][:10],
                "codes_total": len(spec["codes"]),
                "codes_omitted": len(spec["codes"]) - 10,
            }
    return value


class HistoryDataTool(BaseTool):
    """Plan, download, inspect and read routed historical datasets."""

    name = "history_data"
    description = (
        "Plan and resume large historical datasets with bounded local storage. "
        "Auto routes through compatible existing sources by market and interval; source pins an exact provider. "
        "Plan before create; create returns a job id; start accepts work into the bounded durable catalog; waiting means queued for a worker, with chunk-level turns between jobs; status checks completion. Transient failures retry automatically while the service runs; unfinished started jobs continue when the application reopens. retry_at is the next retry time. Cancel persists across restarts and disables automatic resume. "
        "Rows requires a finished download and returns at most 25 unsampled rows per page with coverage_verified. "
        "Row pages include per-symbol currency, units, timezone and source provenance; null metadata remains unknown. "
        "Downloaded is not verified complete: inspect coverage_verified and never treat a recent tail as full history. "
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
            "interval": {"type": "string", "enum": ["1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"]},
            "source": {"type": "string", "description": "auto (default) or exact registered source"},
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
                    source=kwargs.get("source", "auto"),
                )
            elif action == "rows":
                return row_page(store.read(job, kwargs.get("offset", 0), 25))
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
                    {
                        key: row.get(key)
                        for key in (
                            "id",
                            "state",
                            "pinned",
                            "rows",
                            "completed_chunks",
                            "total_chunks",
                            "auto_resume",
                            "retry_at",
                            "retry_count",
                        )
                    }
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
