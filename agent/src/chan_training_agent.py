"""Read-only Agent runner for Chan-training review reports."""

from __future__ import annotations

import json
from typing import Any, Callable

from src.chan_training_analysis import CHAN_ANALYSIS_VERSION, build_chan_analysis, calculate_analysis_window, match_trade_structures
from src.chan_training_store import ChanTrainingStore


READ_ONLY_TOOLS = ("get_market_data", "load_skill")


def _snapshot_summary(session: dict[str, Any], bars: list[dict[str, Any]], window: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "training_session_snapshot",
        "immutable": True,
        "symbol": session.get("symbol"),
        "period": session.get("period"),
        "bar_count": len(bars),
        "window_bar_count": window.get("bar_count", 0),
        "first_available": bars[0].get("time") if bars else None,
        "last_available": bars[-1].get("time") if bars else None,
        "missing": bool(window.get("missing")),
    }


def _deterministic_report(session: dict[str, Any], window: dict[str, Any], matches: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    aligned = sum(1 for item in matches if item["trend_aligned"])
    return {
        "title": "缠论交易复盘报告",
        "performance": {
            "trade_count": len(matches), "realized_pnl": session.get("realized_pnl", "0"),
            "total_fees": session.get("total_fees", "0"), "aligned_trade_count": aligned,
        },
        "trades": matches,
        "structure_summary": {"fractals": 0, "strokes": 0, "segments": 0, "centers": 0, "signals": 0},
        "execution_correct": [],
        "rule_violations": [],
        "timing_and_exit": [],
        "follow_up_rules": ["只在结构已确认后记录买卖点，不用事后形成的形态解释当时决策。"],
        "limitations": ["报告只使用训练会话保存的不可变行情快照。"],
        "confidence": "低" if snapshot["missing"] or not matches else "中",
        "data": {"window": window, "snapshot": snapshot, "analysis_version": CHAN_ANALYSIS_VERSION},
    }


def _agent_text(context: dict[str, Any]) -> str:
    """Ask AgentLoop for prose while keeping its registry strictly read-only."""
    from src.agent.loop import AgentLoop
    from src.agent.memory import WorkspaceMemory
    from src.providers.chat import ChatLLM
    from src.tools import build_filtered_registry

    registry = build_filtered_registry(list(READ_ONLY_TOOLS))
    skill_result = registry.execute("load_skill", {"name": "chanlun"})
    try:
        skill_payload = json.loads(skill_result)
    except json.JSONDecodeError as exc:
        raise RuntimeError("chanlun skill could not be loaded") from exc
    if skill_payload.get("status") == "error":
        raise RuntimeError(str(skill_payload.get("content") or "chanlun skill could not be loaded"))
    prompt = (
        "你是只读的缠论复盘 Agent。已通过 load_skill 读取 chanlun；如需补充行情只能使用 get_market_data。"
        "禁止交易、写文件、下单，禁止使用未来才确认的结构。请基于下面已计算并按交易时刻过滤的数据，"
        "输出中文复盘补充，覆盖趋势顺应、中枢位置、已确认买卖点、执行正确项、违反规则项、时机/持仓/退出、"
        "后续规则、数据不足和置信度。只报告数据中实际存在的信号，不虚构 B1/S1。\n\n"
        + "\n\n已加载的 chanlun Skill 摘要：\n"
        + json.dumps(skill_payload, ensure_ascii=False)
        + "\n\n复盘数据：\n"
        + json.dumps(context, ensure_ascii=False)
    )
    result = AgentLoop(registry=registry, llm=ChatLLM(), memory=WorkspaceMemory(), max_iterations=8).run(prompt, session_id="chan-training-analysis")
    if result.get("status") != "success" or not result.get("content"):
        raise RuntimeError(str(result.get("reason") or "Agent returned no report"))
    return str(result["content"])


def run_chan_analysis(store: ChanTrainingStore, scope: str, run_id: str, *, agent_runner: Callable[[dict[str, Any]], str] | None = None) -> dict[str, Any]:
    """Execute one queued run and persist both success and failure."""
    store.update_analysis_run(scope, run_id, status="running", started=True)
    try:
        run = store.get_analysis_run_by_id(scope, run_id)
        session = store.get_session(scope, run["session_id"], include_hidden=True)
        bars = session.get("bars") or []
        trades = session.get("trades") or []
        window = calculate_analysis_window(bars, trades, session.get("current_cursor"))
        snapshot = _snapshot_summary(session, bars, window)
        analysis = session.get("chan_analysis") or build_chan_analysis(bars)
        matches = match_trade_structures(trades, analysis)
        report = _deterministic_report(session, window, matches, snapshot)
        report["structure_summary"] = {key: len(analysis.get(key, [])) for key in ("fractals", "strokes", "segments", "centers", "signals")}
        report["agent_report"] = (agent_runner or _agent_text)({"report": report, "bars": bars, "trades": trades})
        return store.update_analysis_run(scope, run_id, status="completed", report=report, finished=True)
    except Exception as exc:  # preserve a retryable failed run
        return store.update_analysis_run(scope, run_id, status="failed", error=f"{type(exc).__name__}: {exc}", finished=True)
