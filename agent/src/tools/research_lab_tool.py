"""Shared agent entry for reproducible, research-only experiments."""

from __future__ import annotations

import json

from src.agent.tools import BaseTool


class ResearchLabTool(BaseTool):
    name = "research_lab"
    description = (
        "Run research-only experiments from saved run artifacts: cost_sensitivity re-executes sealed price inputs; "
        "walk_forward selects constructor parameters on training data then freezes them for OOS/holdout; "
        "factor_audit checks formula/warmup contracts; replay verifies persisted task artifacts without an LLM or network. "
        "Use catalog for available runs, parameters and replay prompts, or show with job_id to recover a report."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["catalog", "show", "cost_sensitivity", "walk_forward", "factor_audit", "replay"],
            },
            "request": {
                "type": "object",
                "description": "Action request. costs: run_dir, scenarios[{name,fee_multiplier,extra_slippage_bps}]. walk_forward: run_dir,candidates[{name,parameters}],train_bars,test_bars, optional holdout_bars,max_folds,objective,training. audit: optional alpha_ids. replay: run_dir, optional case_ids,trace_dir. show: job_id.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def execute(self, **kwargs) -> str:
        from src.research_lab import service
        from src.tools.redaction import redact_text

        try:
            action = kwargs["action"]
            payload = kwargs.get("request") or {}
            result = (
                service.catalog()
                if action == "catalog"
                else service.get_job(payload["job_id"])
                if action == "show"
                else service.run(action, payload)
            )
            if action == "catalog":
                case_id = payload.get("case_id")
                result["cases"] = (
                    [row for row in result["cases"] if row["id"] == case_id]
                    if case_id
                    else [{key: row[key] for key in ("id", "scenario")} for row in result["cases"]]
                )
                result["runs"] = result["runs"][:20]
                result["help"] = "Use catalog with request.case_id to read a task's exact original prompt."
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded) > 9000:
                identifier = result.get("id")
                report = result.get("result", result)
                summary = {key: value for key, value in report.items() if key not in {"rows", "folds", "reports"}}
                result = {key: result[key] for key in ("id", "action", "status", "error") if key in result}
                if report.get("kind") == "factor_audit":
                    summary["findings"] = [
                        {"id": row["id"], "findings": row.get("findings", [])}
                        for row in report.get("rows", [])
                        if not row["valid"]
                    ][:20]
                result.update(
                    summary=summary,
                    omitted="Detailed tables omitted from this tool envelope; open the complete persisted JSON report.",
                )
                if identifier:
                    result["report_path"] = str(service.job_root(identifier) / "report.json")
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded) > 9000:
                result = {key: result[key] for key in ("id", "action", "status", "report_path") if key in result}
                result["omitted"] = "Report exceeds the tool budget. Read the persisted report, or narrow catalog by case_id."
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            return encoded
        except (ValueError, OSError, KeyError) as exc:
            return json.dumps({"status": "error", "error": redact_text(str(exc))}, ensure_ascii=False)
