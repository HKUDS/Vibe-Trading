"""Research Autopilot: goal-hypothesis bridge + backtest config generation.

Phase 1: Connects the Hypothesis Registry to the Research Goal runtime.
Phase 2: Auto-generates backtest config.json from hypothesis metadata.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.hypotheses import HypothesisRegistry


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


def _error(exc: Exception) -> str:
    return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


def _get_hypothesis(hypothesis_id: str):
    """Return a hypothesis by id, or None when absent."""
    for hypothesis in HypothesisRegistry().list():
        if hypothesis.hypothesis_id == hypothesis_id:
            return hypothesis
    return None


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
        "and backtest-relevant criteria. NOTE: this replaces the session's "
        "current research goal. Returns a goal snapshot you can continue "
        "from with backtest/evidence tools."
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

    def __init__(
        self,
        *,
        default_session_id: str | None = None,
        event_callback: Any = None,
    ) -> None:
        """Initialize the autopilot tool.

        Args:
            default_session_id: Session id injected by the host runtime, so the
                tool can create a goal without the LLM ever knowing the id.
            event_callback: Optional host callback, accepted for registry
                construction parity with the goal tools (currently unused).
        """
        self._default_session_id = default_session_id
        self._event_callback = event_callback

    def execute(self, **kwargs: Any) -> str:
        try:
            hypothesis_id = str(kwargs.get("hypothesis_id", "")).strip()
            if not hypothesis_id:
                return json.dumps(
                    {"status": "error", "error": "hypothesis_id is required"},
                    ensure_ascii=False,
                )

            hypothesis = _get_hypothesis(hypothesis_id)
            if hypothesis is None:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"Hypothesis not found: {hypothesis_id}",
                        "hint": "Use search_hypotheses to list available hypotheses.",
                    },
                    ensure_ascii=False,
                )

            session_id = str(
                kwargs.get("session_id") or self._default_session_id or ""
            ).strip()
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


_UNIVERSE_CODES: dict[str, list[str]] = {
    "csi 300": ["000300.SH"],
    "csi300": ["000300.SH"],
    "csi 500": ["000905.SH"],
    "csi500": ["000905.SH"],
    "sse 50": ["000016.SH"],
    "sse50": ["000016.SH"],
    "szse comp": ["399001.SZ"],
    "sse comp": ["000001.SH"],
    "chinext": ["399006.SZ"],
    "chi next": ["399006.SZ"],
    "s&p 500": ["SPY.US"],
    "sp500": ["SPY.US"],
    "nasdaq": ["QQQ.US"],
    "dow jones": ["DIA.US"],
    "hang seng": ["^HSI.HK"],
    "nikkei": ["^N225.HK"],
}


def _lookup_codes(universe: str) -> list[str]:
    key = universe.strip().lower().replace("-", " ").replace("_", " ")
    return _UNIVERSE_CODES.get(key, [universe])


def _resolve_source(data_sources: list[str] | None) -> tuple[str, str | None]:
    """Pick a valid loader source from the hypothesis, else fall back to ``auto``.

    A hypothesis ``data_sources`` entry is free text, so an unrecognised value
    would otherwise only fail deep inside the backtest runner with a confusing
    message. Validate it up front and degrade to ``auto`` with a warning the
    agent can surface.

    Args:
        data_sources: The hypothesis ``data_sources`` list (may be empty/None).

    Returns:
        A ``(source, warning)`` tuple; ``warning`` is ``None`` when the source
        is valid or the source whitelist cannot be imported.
    """
    candidate = (data_sources or ["auto"])[0]
    try:
        from backtest.loaders.registry import VALID_SOURCES
    except Exception:  # pragma: no cover - registry import is environment-stable
        return candidate, None
    if candidate in VALID_SOURCES:
        return candidate, None
    return "auto", (
        f"hypothesis data_source {candidate!r} is not a known loader source; "
        "fell back to 'auto'"
    )


def _validate_backtest_dates(start_date: str, end_date: str) -> None:
    """Validate backtest dates before writing any run artifacts."""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("start_date must be YYYY-MM-DD") from exc
    try:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("end_date must be YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("start_date must be on or before end_date")


def _run_dir_for_hypothesis(hypothesis_id: str) -> Path:
    """Return a path-contained run directory for any persisted hypothesis id."""
    suffix = hashlib.sha256(hypothesis_id.encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".vibe-trading" / "runs" / f"autopilot_{suffix}"


class GenerateBacktestConfigTool(BaseTool):
    """Generate backtest config.json from a research hypothesis.

    Reads a hypothesis, derives config fields from its universe and
    data_sources, and writes a ready-to-run config.json to a run directory.
    The agent should then create signal_engine.py from the signal_definition
    and call the backtest tool.
    """

    name = "generate_backtest_config"
    description = (
        "Generate a backtest config.json from a saved hypothesis. "
        "Auto-populates codes from the hypothesis universe and source from "
        "data_sources. Writes config.json to a run directory. You must still "
        "create code/signal_engine.py from the signal_definition before calling "
        "the backtest tool."
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
            "start_date": {
                "type": "string",
                "description": "Backtest start date (YYYY-MM-DD)",
            },
            "end_date": {
                "type": "string",
                "description": "Backtest end date (YYYY-MM-DD)",
            },
            "session_id": {
                "type": "string",
                "description": "Current session id (host-injected)",
            },
        },
        "required": ["hypothesis_id", "start_date", "end_date"],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            hypothesis_id = str(kwargs.get("hypothesis_id", "")).strip()
            if not hypothesis_id:
                return json.dumps(
                    {"status": "error", "error": "hypothesis_id is required"},
                    ensure_ascii=False,
                )

            hypothesis = _get_hypothesis(hypothesis_id)
            if hypothesis is None:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"Hypothesis not found: {hypothesis_id}",
                        "hint": "Use search_hypotheses to list available hypotheses.",
                    },
                    ensure_ascii=False,
                )

            if not hypothesis.universe.strip():
                return json.dumps(
                    {
                        "status": "error",
                        "error": "Hypothesis has no universe set",
                        "hint": "Use update_hypothesis to set a universe (e.g. 'CSI 300').",
                    },
                    ensure_ascii=False,
                )

            start_date = str(kwargs.get("start_date", "")).strip()
            end_date = str(kwargs.get("end_date", "")).strip()
            _validate_backtest_dates(start_date, end_date)

            codes = _lookup_codes(hypothesis.universe)
            source, source_warning = _resolve_source(hypothesis.data_sources)

            config = {
                "codes": codes,
                "start_date": start_date,
                "end_date": end_date,
                "source": source,
                "interval": "1D",
            }

            run_dir = _run_dir_for_hypothesis(hypothesis_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "code").mkdir(parents=True, exist_ok=True)

            config_path = run_dir / "config.json"
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            payload: dict[str, Any] = {
                "run_dir": str(run_dir),
                "config": config,
                "config_path": str(config_path),
                "hypothesis": {
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "title": hypothesis.title,
                    "signal_definition": hypothesis.signal_definition,
                    "universe": hypothesis.universe,
                    "data_sources": hypothesis.data_sources,
                },
                "next_step": (
                    "Config written. Next: use write_file to create "
                    "code/signal_engine.py from the signal_definition above, "
                    "then call backtest(run_dir=...)."
                ),
            }
            if source_warning:
                payload["warning"] = source_warning
            return _ok(payload)

        except Exception as exc:
            return _error(exc)
