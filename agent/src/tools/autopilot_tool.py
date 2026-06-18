"""Research Autopilot Phase 1: goal-hypothesis bridge tool.

Connects the Hypothesis Registry to the Research Goal runtime so the agent
can scaffold a full research workflow from a single ``run_research_autopilot``
call instead of manually creating goals, recalling hypothesis IDs, and
wiring criteria by hand.
"""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.hypotheses import HypothesisRegistry


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


def _error(exc: Exception) -> str:
    return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


_AUTOPILOT_OBJECTIVE_TEMPLATE = """<hypothesis-id>{hypothesis_id}</hypothesis-id>
<hypothesis-title>{title}</hypothesis-title>

{thesis}

---
**Autopilot**: This goal was auto-scaffolded from a research hypothesis.
Continue through the workflow: generate backtest code → execute → evaluate → record evidence."""


class RunResearchAutopilotTool(BaseTool):
    """Start a research workflow from a durable hypothesis.

    Reads a hypothesis from the local registry, creates a research goal
    with the hypothesis thesis as its objective, and returns the goal
    snapshot so the agent can continue the backtest → evidence pipeline.
    """

    name = "run_research_autopilot"
    description = (
        "Start a research goal from a saved hypothesis. "
        "Reads the hypothesis, creates a goal with the thesis as objective "
        "and backtest-relevant criteria. Returns a goal snapshot you can "
        "continue from with backtest/evidence tools."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "hypothesis_id": {
                "type": "string",
                "description": "ID of a previously created research hypothesis",
            },
            "session_id": {
                "type": "string",
                "description": "Current session id (host-injected)",
            },
        },
        "required": ["hypothesis_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            hypothesis_id = str(kwargs.get("hypothesis_id", "")).strip()
            if not hypothesis_id:
                return json.dumps(
                    {"status": "error", "error": "hypothesis_id is required"},
                    ensure_ascii=False,
                )

            registry = HypothesisRegistry()
            hypothesis = registry.get(hypothesis_id)
            if hypothesis is None:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"Hypothesis not found: {hypothesis_id}",
                        "hint": "Use search_hypotheses to list available hypotheses.",
                    },
                    ensure_ascii=False,
                )

            session_id = str(kwargs.get("session_id", "")).strip()
            if not session_id:
                return json.dumps(
                    {
                        "status": "error",
                        "error": "session_id is required",
                        "hint": "Ask the host runtime for the current session id.",
                    },
                    ensure_ascii=False,
                )

            objective = _AUTOPILOT_OBJECTIVE_TEMPLATE.format(
                hypothesis_id=hypothesis.hypothesis_id,
                title=hypothesis.title,
                thesis=hypothesis.thesis,
            )

            criteria = [
                "Generate backtest code (signal_engine.py + config.json) from the signal definition",
                "Execute a deterministic backtest with the configured data sources",
                "Evaluate backtest metrics against the hypothesis thesis",
                "Record evidence: link_backtest to hypothesis and add_goal_evidence",
            ]

            from src.goal import GoalStore

            store = GoalStore()

            goal = store.replace_goal(
                session_id=session_id,
                objective=objective,
                criteria=criteria,
                ui_summary=f"Research Autopilot: {hypothesis.title}",
                source="autopilot",
                protocol="thesis_review",
            )

            snapshot = store.get_goal_snapshot(goal.goal_id)

            hypothesis_summary = {
                "hypothesis_id": hypothesis.hypothesis_id,
                "title": hypothesis.title,
                "thesis": hypothesis.thesis[:300],
                "status": hypothesis.status,
                "universe": hypothesis.universe,
                "signal_definition": hypothesis.signal_definition[:300],
                "data_sources": hypothesis.data_sources,
                "skills": hypothesis.skills,
                "run_cards_count": len(hypothesis.run_cards),
            }

            return _ok(
                {
                    "goal": snapshot,
                    "hypothesis": hypothesis_summary,
                    "next_step": "Continue the research workflow. Generate backtest code → execute → add_goal_evidence.",
                }
            )

        except Exception as exc:
            return _error(exc)
