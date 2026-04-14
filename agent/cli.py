#!/usr/bin/env python3
"""Vibe-Trading CLI — natural-language finance research & backtesting.

Usage:
    vibe-trading                           Interactive mode (default)
    vibe-trading -p "Backtest AAPL MACD"   Single run
    vibe-trading serve --port 8899         Start API server
    vibe-trading chat                      Interactive mode
    vibe-trading list                      List runs
    vibe-trading show <run_id>             Show run details
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import warnings
warnings.filterwarnings("ignore", message=".*Importing verbose from langchain.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain")

for _s in ("stdout", "stderr"):
    _r = getattr(getattr(sys, _s, None), "reconfigure", None)
    if callable(_r):
        _r(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.syntax import Syntax
from rich.table import Table

console = Console()
AGENT_DIR = Path(__file__).resolve().parent
RUNS_DIR = AGENT_DIR / "runs"
SWARM_DIR = AGENT_DIR / ".swarm" / "runs"
SESSIONS_DIR = AGENT_DIR / "sessions"
UPLOADS_DIR = AGENT_DIR / "uploads"

EXIT_SUCCESS = 0
EXIT_RUN_FAILED = 1
EXIT_USAGE_ERROR = 2
RICH_TAG_PATTERN = re.compile(r"\[/?[^\]]+\]")

_VERSION = "0.1.0"

# Agent color assignments for swarm display
_AGENT_STYLES = ["cyan", "magenta", "green", "yellow", "blue", "bright_red", "bright_cyan", "bright_magenta"]
_agent_color_map: dict[str, str] = {}


def serve_main(argv: list[str] | None = None) -> int:
    """Delegate server startup to api_server."""
    from api_server import serve_main as api_serve_main

    return api_serve_main(argv)


def _strip_rich_tags(text: str) -> str:
    """Remove Rich markup from plain-text output."""
    return RICH_TAG_PATTERN.sub("", text)


def _print_json_result(result: dict) -> None:
    """Print a machine-readable run summary."""
    payload = {
        "status": result.get("status", "unknown"),
        "run_id": result.get("run_id"),
        "run_dir": result.get("run_dir"),
        "reason": result.get("reason"),
    }
    print(json.dumps(payload, ensure_ascii=False))


def _result_exit_code(result: dict) -> int:
    """Map run results to stable exit codes."""
    return EXIT_SUCCESS if result.get("status") == "success" else EXIT_RUN_FAILED


def _coerce_exit_code(value: Optional[int]) -> int:
    """Normalize command return values to an integer exit code."""
    return EXIT_SUCCESS if value is None else int(value)


def _read_prompt_source(
    prompt: Optional[str],
    prompt_file: Optional[Path],
    *,
    no_rich: bool,
    allow_interactive: bool = True,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve prompt text from CLI args, file, stdin, or interactive input."""
    if prompt is not None:
        return prompt.strip(), None

    if prompt_file is not None:
        try:
            return prompt_file.read_text(encoding="utf-8").strip(), None
        except OSError as exc:
            return None, f"Failed to read prompt file: {exc}"

    if not sys.stdin.isatty():
        return sys.stdin.read().strip(), None

    if not allow_interactive:
        return None, "A prompt is required."

    try:
        if no_rich:
            return input("Enter strategy request: ").strip(), None
        return Prompt.ask("Enter strategy request").strip(), None
    except (EOFError, KeyboardInterrupt):
        return None, "Prompt input cancelled."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    """Safely read JSON."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_metrics(path: Path) -> dict:
    """Read metrics from metrics.csv, return formatted string dict."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return {}
        out = {}
        for k, v in rows[0].items():
            if not v:
                continue
            try:
                fv = float(v)
                out[k] = f"{fv:.4f}" if abs(fv) < 100 else f"{fv:.0f}"
            except ValueError:
                out[k] = v
        return out
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Agent execution core
# ---------------------------------------------------------------------------

def _format_tool_call_args(tool: str, args: Dict[str, str]) -> str:
    """Smart-format tool argument summary."""
    if tool == "load_skill":
        return f'("{args.get("name", "")}")'
    if tool in ("write_file", "read_file", "edit_file"):
        return f' {args.get("path", args.get("file_path", ""))}'
    if tool in ("bash", "background_run"):
        cmd = args.get("command", "")[:80]
        return f' [yellow]{cmd}[/yellow]'
    if tool == "subagent":
        desc = args.get("description", args.get("prompt", "")[:60])
        return f' [magenta]{desc}[/magenta]'
    if tool == "task_create":
        return f' "{args.get("subject", "")}"'
    if tool == "task_update":
        return f' #{args.get("task_id", "")} -> {args.get("status", "")}'
    if tool == "check_background":
        tid = args.get("task_id", "")
        return f' {tid}' if tid else ""
    if tool in ("backtest", "compact", "task_list"):
        return ""
    for v in args.values():
        if v and v != "None":
            return f" {v[:60]}"
    return ""


def _format_tool_result_preview(tool: str, status: str, preview: str) -> str:
    """Smart-format tool result preview."""
    if status != "ok":
        return f"[red]{preview[:80]}[/red]"
    if tool == "backtest":
        sharpe = re.search(r'"sharpe":\s*([\d.eE+-]+)', preview)
        ret = re.search(r'"total_return":\s*([\d.eE+-]+)', preview)
        parts = []
        if sharpe:
            parts.append(f"sharpe={sharpe.group(1)}")
        if ret:
            parts.append(f"return={float(ret.group(1))*100:.1f}%")
        return ", ".join(parts) if parts else ""
    if tool in ("bash", "background_run"):
        if "OK" in preview[:50]:
            return "OK"
        return preview[:60].replace("\n", " ")
    if tool == "subagent":
        m = re.search(r'"summary":\s*"(.{0,80})', preview)
        return m.group(1).rstrip('"') if m else ""
    if tool in ("task_create", "task_update"):
        return preview[:60].replace("\n", " ")
    if tool in ("read_file", "load_skill", "compact"):
        return ""
    return ""


def _run_agent(
    prompt: str,
    history: Optional[List[Dict]] = None,
    run_dir_override: Optional[str] = None,
    max_iter: int = 50,
    *,
    no_rich: bool = False,
    stream_output: bool = True,
) -> dict:
    """Build AgentLoop and execute, return result dict."""
    from src.tools import build_registry
    from src.providers.chat import ChatLLM
    from src.agent.loop import AgentLoop

    def on_event(event_type: str, data: Dict[str, Any]) -> None:
        if not stream_output:
            return
        if no_rich and event_type == "thinking_done":
            print()
            return
        if no_rich and event_type == "tool_call":
            tool = data.get("tool", "")
            args = data.get("arguments", {})
            args_preview = _format_tool_call_args(tool, args)
            print(f"  - {tool}{_strip_rich_tags(args_preview)}", end="")
            return
        if no_rich and event_type == "tool_result":
            tool = data.get("tool", "")
            status = data.get("status", "ok")
            elapsed_ms = data.get("elapsed_ms", 0)
            elapsed_s = elapsed_ms / 1000
            preview = _format_tool_result_preview(tool, status, data.get("preview", ""))
            suffix = f"  {preview}" if preview else ""
            mark = "OK" if status == "ok" else "FAIL"
            print(f"  {mark} {elapsed_s:.1f}s{_strip_rich_tags(suffix)}")
            return
        if no_rich and event_type == "compact":
            tokens = data.get("tokens_before", "?")
            print(f"\n  context compressed ({tokens} tokens -> summary)\n")
            return
        if event_type == "text_delta":
            if no_rich:
                print(data.get("delta", ""), end="")
            else:
                console.print(data.get("delta", ""), end="", style="dim")
        elif event_type == "thinking_done":
            console.print()
        elif event_type == "tool_call":
            tool = data.get("tool", "")
            args = data.get("arguments", {})
            args_preview = _format_tool_call_args(tool, args)
            console.print(f"  [cyan]\u25b6 {tool}[/cyan]{args_preview}", end="")
        elif event_type == "tool_result":
            tool = data.get("tool", "")
            status = data.get("status", "ok")
            elapsed_ms = data.get("elapsed_ms", 0)
            elapsed_s = elapsed_ms / 1000
            ok = status == "ok"
            mark = "[green]\u2713[/green]" if ok else "[red]\u2717[/red]"
            preview = _format_tool_result_preview(tool, status, data.get("preview", ""))
            suffix = f"  {preview}" if preview else ""
            console.print(f"  {mark} [dim]{elapsed_s:.1f}s[/dim]{suffix}")
        elif event_type == "compact":
            tokens = data.get("tokens_before", "?")
            console.print(f"\n  [yellow]\u27f3 context compressed[/yellow] [dim]({tokens} tokens \u2192 summary)[/dim]\n")

    agent = AgentLoop(
        registry=build_registry(),
        llm=ChatLLM(),
        event_callback=on_event,
        max_iterations=max_iter,
    )
    if run_dir_override:
        agent.memory.run_dir = run_dir_override

    return agent.run(user_message=prompt, history=history)


def _print_result(result: dict, elapsed: float, *, no_rich: bool = False) -> None:
    """Print execution result panel."""
    status = result.get("status", "unknown")
    ok = status == "success"
    style = "green" if ok else "red"

    lines = [f"Status: [bold {style}]{status.upper()}[/bold {style}]  Time: {elapsed:.1f}s"]

    if result.get("run_id"):
        lines.append(f"ID: {result['run_id']}")

    review = result.get("review")
    if review and review.get("overall_score") is not None:
        check = "\u2713" if review.get("passed") else "\u2717"
        lines.append(f"Review: {review['overall_score']}pts {check}")

    run_dir = result.get("run_dir")
    if run_dir:
        m = _read_metrics(Path(run_dir) / "artifacts" / "metrics.csv")
        parts = [f"{k}={m[k]}" for k in ("total_return", "sharpe", "max_drawdown", "trade_count") if k in m]
        if parts:
            lines.append(f"Metrics: {', '.join(parts)}")

    if result.get("reason"):
        lines.append(f"Reason: {result['reason']}")

    console.print(Panel("\n".join(lines), border_style=style, title="Result"))

    content = result.get("content", "").strip()
    if content:
        console.print(f"\n{content}")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_run(prompt: str, max_iter: int, *, json_mode: bool = False, no_rich: bool = False) -> int:
    """Single run."""
    if not json_mode:
        from src.preflight import run_preflight
        results = run_preflight(console)
        if any(r.critical and r.status != "ready" for r in results):
            return EXIT_RUN_FAILED

    if not json_mode:
        preview = prompt[:120]
        suffix = "..." if len(prompt) > 120 else ""
        if no_rich:
            print(f"Prompt: {preview}{suffix}\n")
        else:
            console.print(f"[dim]Prompt:[/dim] {preview}{suffix}\n")
    start = time.perf_counter()
    try:
        result = _run_agent(prompt, max_iter=max_iter, no_rich=no_rich, stream_output=not json_mode)
    except KeyboardInterrupt:
        if json_mode:
            _print_json_result({"status": "cancelled", "run_id": None, "run_dir": None, "reason": "Interrupted"})
            return EXIT_RUN_FAILED
        if no_rich:
            print("\nInterrupted")
            return EXIT_RUN_FAILED
        console.print("\n[yellow]Interrupted[/yellow]")
        return EXIT_RUN_FAILED
    if json_mode:
        _print_json_result(result)
        return _result_exit_code(result)
    _print_result(result, time.perf_counter() - start, no_rich=no_rich)
    if result.get("run_id"):
        tip = f"--show {result['run_id']}  |  --continue {result['run_id']} \"...\"  |  --code {result['run_id']}  |  --pine {result['run_id']}"
        if no_rich:
            print(tip)
        else:
            console.print(f"[dim]{tip}[/dim]")
    return _result_exit_code(result)


def _build_history_from_trace(run_dir: Path) -> List[Dict[str, str]]:
    """Build conversation history from trace.jsonl."""
    from src.agent.trace import TraceWriter
    entries = TraceWriter.read(run_dir)
    history: List[Dict[str, str]] = []
    for e in entries:
        if e.get("type") == "start" and e.get("prompt"):
            history.append({"role": "user", "content": e["prompt"]})
        elif e.get("type") == "answer" and e.get("content"):
            history.append({"role": "assistant", "content": e["content"]})
    return history


def cmd_continue(
    run_id: str,
    prompt: str,
    max_iter: int,
    *,
    json_mode: bool = False,
    no_rich: bool = False,
) -> int:
    """Continue an existing run."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        if no_rich:
            print(f"Run {run_id} not found")
            return EXIT_USAGE_ERROR
        console.print(f"[red]Run {run_id} not found[/red]")
        return EXIT_USAGE_ERROR

    history = _build_history_from_trace(run_dir)
    if not json_mode and no_rich:
        print(f"Continue {run_id}: {prompt[:120]}\n")
    if json_mode or no_rich:
        start = time.perf_counter()
        try:
            result = _run_agent(
                prompt,
                history=history,
                run_dir_override=str(run_dir),
                max_iter=max_iter,
                no_rich=no_rich,
                stream_output=not json_mode,
            )
        except KeyboardInterrupt:
            if json_mode:
                _print_json_result(
                    {"status": "cancelled", "run_id": run_id, "run_dir": str(run_dir), "reason": "Interrupted"}
                )
            else:
                print("\nInterrupted")
            return EXIT_RUN_FAILED
        if json_mode:
            _print_json_result(result)
            return _result_exit_code(result)
        _print_result(result, time.perf_counter() - start, no_rich=True)
        return _result_exit_code(result)

    console.print(f"[dim]Continue {run_id}:[/dim] {prompt[:120]}\n")
    start = time.perf_counter()
    try:
        result = _run_agent(prompt, history=history, run_dir_override=str(run_dir), max_iter=max_iter)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return EXIT_RUN_FAILED
    _print_result(result, time.perf_counter() - start)
    return _result_exit_code(result)


# ---------------------------------------------------------------------------
# Interactive mode (Welcome + Slash commands + Swarm streaming)
# ---------------------------------------------------------------------------

def _print_welcome() -> None:
    """Print the welcome screen."""
    welcome = (
        f"[bold cyan]Vibe-Trading[/bold cyan] [dim]v{_VERSION}[/dim]\n"
        "[dim]Vibe trading with your professional financial agent team[/dim]\n"
        "\n"
        "Type a natural-language request to start, or use [bold]/commands[/bold]:\n"
        "\n"
        "  [cyan]/skills[/cyan]    List available skills       [cyan]/swarm[/cyan]     Agent team presets\n"
        "  [cyan]/list[/cyan]      Recent runs                 [cyan]/settings[/cyan]  Runtime config\n"
        "  [cyan]/help[/cyan]      All commands                [cyan]/quit[/cyan]      Exit"
    )
    console.print(Panel(welcome, border_style="cyan", padding=(1, 2)))


def _print_help() -> None:
    """Print all available slash commands."""
    table = Table(title="Commands", show_lines=False, border_style="dim")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description")

    cmds = [
        ("/help", "Show this help"),
        ("/skills", "List all skills"),
        ("/list", "List recent runs"),
        ("/show <run_id>", "Show run details"),
        ("/code <run_id>", "Show generated code"),
        ("/pine <run_id>", "Show Pine Script for TradingView"),
        ("/trace <run_id>", "Replay run trace"),
        ("/continue <run_id> <prompt>", "Continue an existing run"),
        ("/swarm", "List swarm team presets"),
        ("/swarm run <preset> {vars}", "Run a swarm team"),
        ("/swarm list", "List swarm run history"),
        ("/swarm show <run_id>", "Show swarm run details"),
        ("/swarm cancel <run_id>", "Cancel a swarm run"),
        ("/sessions", "List chat sessions"),
        ("/settings", "Show runtime settings"),
        ("/clear", "Clear screen"),
        ("/quit", "Exit"),
    ]
    for cmd, desc in cmds:
        table.add_row(cmd, desc)

    console.print(table)


def _show_settings() -> None:
    """Show current runtime settings."""
    table = Table(title="Settings", show_lines=False, border_style="dim")
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    settings = {
        "Provider": os.getenv("LANGCHAIN_PROVIDER", "(not set)"),
        "Model": os.getenv("LANGCHAIN_MODEL_NAME", "(not set)"),
        "Temperature": os.getenv("LANGCHAIN_TEMPERATURE", "0.0"),
        "Timeout": os.getenv("TIMEOUT_SECONDS", "2400") + "s",
        "Tushare Token": "***" if os.getenv("TUSHARE_TOKEN") else "(not set)",
    }
    for k, v in settings.items():
        table.add_row(k, v)

    console.print(table)


def _handle_slash_command(input_str: str, *, max_iter: int) -> None:
    """Parse and route a slash command."""
    parts = input_str.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/help":
        _print_help()
    elif cmd == "/skills":
        cmd_skills()
    elif cmd == "/list":
        cmd_list()
    elif cmd == "/show":
        if arg:
            cmd_show(arg)
        else:
            console.print("[red]Usage: /show <run_id>[/red]")
    elif cmd == "/code":
        if arg:
            cmd_code(arg)
        else:
            console.print("[red]Usage: /code <run_id>[/red]")
    elif cmd == "/pine":
        if arg:
            cmd_pine(arg)
        else:
            console.print("[red]Usage: /pine <run_id>[/red]")
    elif cmd == "/trace":
        if arg:
            cmd_trace(arg)
        else:
            console.print("[red]Usage: /trace <run_id>[/red]")
    elif cmd == "/continue":
        cont_parts = arg.split(maxsplit=1)
        if len(cont_parts) >= 2:
            cmd_continue(cont_parts[0], cont_parts[1], max_iter)
        else:
            console.print("[red]Usage: /continue <run_id> <prompt>[/red]")
    elif cmd == "/swarm":
        _handle_swarm_command(arg)
    elif cmd == "/sessions":
        cmd_sessions()
    elif cmd == "/settings":
        _show_settings()
    elif cmd == "/clear":
        console.clear()
        _print_welcome()
    elif cmd in ("/quit", "/exit"):
        raise EOFError
    else:
        console.print(f"[red]Unknown command: {cmd}[/red] — type [cyan]/help[/cyan] for available commands")


def _handle_swarm_command(arg: str) -> None:
    """Route swarm sub-commands."""
    if not arg:
        cmd_swarm_presets()
        return

    parts = arg.split(maxsplit=1)
    sub = parts[0].lower()
    sub_arg = parts[1].strip() if len(parts) > 1 else ""

    if sub == "run":
        run_parts = sub_arg.split(maxsplit=1)
        if not run_parts:
            console.print("[red]Usage: /swarm run <preset> [vars_json][/red]")
            return
        preset = run_parts[0]
        vars_json = run_parts[1] if len(run_parts) > 1 else None
        cmd_swarm_run_live(preset, vars_json)
    elif sub == "list":
        cmd_swarm_list()
    elif sub == "show":
        if sub_arg:
            cmd_swarm_show(sub_arg)
        else:
            console.print("[red]Usage: /swarm show <run_id>[/red]")
    elif sub == "cancel":
        if sub_arg:
            cmd_swarm_cancel(sub_arg)
        else:
            console.print("[red]Usage: /swarm cancel <run_id>[/red]")
    else:
        console.print(f"[red]Unknown swarm command: {sub}[/red]")


def cmd_interactive(max_iter: int) -> None:
    """Interactive mode with welcome screen, slash commands, and agent conversation."""
    _print_welcome()

    from src.preflight import run_preflight
    results = run_preflight(console)
    if any(r.critical and r.status != "ready" for r in results):
        return

    history: List[Dict[str, str]] = []

    while True:
        try:
            user_input = Prompt.ask("\n[bold]>[/bold]").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            break

        # Slash commands
        if user_input.startswith("/"):
            try:
                _handle_slash_command(user_input, max_iter=max_iter)
            except EOFError:
                break
            continue

        # Natural language -> agent
        start = time.perf_counter()
        try:
            result = _run_agent(user_input, history=history[-6:], max_iter=max_iter)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted[/yellow]")
            continue

        _print_result(result, time.perf_counter() - start)
        history.append({"role": "user", "content": user_input})
        if result.get("content"):
            history.append({"role": "assistant", "content": result["content"]})

    console.print("[dim]Goodbye[/dim]")


# ---------------------------------------------------------------------------
# Swarm live streaming (Rich Live panel)
# ---------------------------------------------------------------------------

def _get_agent_style(agent_id: str) -> str:
    """Assign a consistent color to each agent."""
    if agent_id not in _agent_color_map:
        idx = len(_agent_color_map) % len(_AGENT_STYLES)
        _agent_color_map[agent_id] = _AGENT_STYLES[idx]
    return _agent_color_map[agent_id]


class _SwarmDashboard:
    """Track swarm state and render a Rich Live panel."""

    def __init__(self, preset: str, run_id: str) -> None:
        self.preset = preset
        self.run_id = run_id
        self.start_time = time.monotonic()
        self.current_layer = 0
        self.total_layers = 0
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.agent_order: List[str] = []
        self.completed_summaries: List[tuple[str, str]] = []
        self.finished = False
        self.final_status = ""

    def _ensure_agent(self, agent_id: str) -> str:
        """Register an agent by its ID if not already tracked. Return its key."""
        if agent_id in self.agents:
            return agent_id
        self.agents[agent_id] = {
            "name": agent_id, "status": "waiting",
            "tool": "\u2014", "elapsed": 0.0, "iters": 0,
            "started_at": 0.0, "layer": self.current_layer,
            "last_text": "",
        }
        self.agent_order.append(agent_id)
        return agent_id

    def handle_event(self, event) -> None:
        """Process a swarm event and update internal state."""
        agent_id = event.agent_id or ""
        etype = event.type
        data = event.data

        if etype == "layer_started":
            self.current_layer = data.get("layer", 0)
            self.total_layers = max(self.total_layers, self.current_layer + 1)
            return

        if etype == "run_completed":
            self.finished = True
            self.final_status = data.get("status", "unknown")
            return

        if not agent_id:
            return

        key = self._ensure_agent(agent_id)
        agent = self.agents[key]

        if etype == "task_started":
            agent["status"] = "running"
            agent["started_at"] = time.monotonic()
        elif etype == "tool_call":
            agent["tool"] = data.get("tool", "?")
            agent["iters"] += 1
        elif etype == "tool_result":
            agent["elapsed"] = (time.monotonic() - agent["started_at"]) if agent["started_at"] else 0
            tool_name = agent["tool"]
            status_char = "\u2713" if data.get("status", "ok") == "ok" else "\u2717"
            agent["tool"] = f"{tool_name} {status_char}"
        elif etype == "task_completed":
            agent["status"] = "done"
            agent["elapsed"] = (time.monotonic() - agent["started_at"]) if agent["started_at"] else 0
            agent["iters"] = data.get("iterations", agent["iters"])
            summary = data.get("summary", "")
            if summary:
                self.completed_summaries.append((agent["name"], summary))
        elif etype == "task_failed":
            agent["status"] = "failed"
            agent["elapsed"] = (time.monotonic() - agent["started_at"]) if agent["started_at"] else 0
            error = data.get("error", "")[:80]
            self.completed_summaries.append((agent["name"], f"[red]FAILED: {error}[/red]"))
        elif etype == "task_retry":
            attempt = data.get("attempt", "?")
            agent["status"] = "retry"
            agent["tool"] = f"retry {attempt}"
        elif etype == "worker_text":
            content = data.get("content", "").strip()
            if content:
                # Keep last non-empty line for display
                last_line = content.split("\n")[-1].strip()
                if last_line:
                    agent["last_text"] = last_line[:60]

    def build_table(self) -> Table:
        """Build the Rich Table for the live panel."""
        elapsed_total = time.monotonic() - self.start_time
        mins, secs = divmod(int(elapsed_total), 60)

        if self.finished:
            color = "green" if self.final_status == "completed" else "red"
            title_status = f"[{color}]{self.final_status.upper()}[/{color}]"
        else:
            title_status = f"[cyan]RUNNING[/cyan]"

        title = f"{self.preset}  {title_status}  {mins}:{secs:02d}"

        table = Table(
            title=title,
            border_style="cyan" if not self.finished else ("green" if self.final_status == "completed" else "red"),
            show_lines=False,
            pad_edge=True,
            expand=True,
        )
        table.add_column("Agent", style="bold", width=20, no_wrap=True)
        table.add_column("Status", width=12, justify="center")
        table.add_column("Tool", width=14, no_wrap=True)
        table.add_column("Time", width=7, justify="right")
        table.add_column("Iters", width=5, justify="right")
        table.add_column("Output", no_wrap=True, style="dim")

        for agent_key in self.agent_order:
            agent = self.agents[agent_key]
            name = agent["name"]
            style = _get_agent_style(name)
            styled_name = f"[{style}]{name}[/{style}]"

            status = agent["status"]
            if status == "running":
                status_str = "[\u25b6 running]"
                elapsed = time.monotonic() - agent["started_at"] if agent["started_at"] else 0
            elif status == "done":
                status_str = "[green][\u2713 done  ][/green]"
                elapsed = agent["elapsed"]
            elif status == "failed":
                status_str = "[red][\u2717 failed][/red]"
                elapsed = agent["elapsed"]
            elif status == "retry":
                status_str = "[yellow][\u21bb retry ][/yellow]"
                elapsed = time.monotonic() - agent["started_at"] if agent["started_at"] else 0
            else:
                status_str = "[dim][\u25cb waiting][/dim]"
                elapsed = 0

            time_str = f"{elapsed:.1f}s" if elapsed > 0 else "\u2014"
            iter_str = str(agent["iters"]) if agent["iters"] > 0 else "\u2014"
            last_text = agent.get("last_text", "")

            table.add_row(styled_name, status_str, agent["tool"], time_str, iter_str, last_text)

        # Progress bar row
        done_count = sum(1 for a in self.agents.values() if a["status"] in ("done", "failed"))
        total_count = len(self.agents) or 1
        pct = int(done_count / total_count * 100)
        bar_width = 40
        filled = int(bar_width * pct / 100)
        bar = "\u2501" * filled + "[dim]" + "\u2501" * (bar_width - filled) + "[/dim]"

        if self.finished:
            bar_color = "green" if self.final_status == "completed" else "red"
            progress_label = f"[{bar_color}]{self.final_status.upper()}[/{bar_color}]"
        else:
            progress_label = f"Layer {self.current_layer}"

        table.add_section()
        table.add_row(
            progress_label,
            f"{bar}",
            f"[bold]{pct}%[/bold]",
            f"{mins}:{secs:02d}",
            "",
            "",
        )

        return table


def cmd_swarm_run_live(preset: str, vars_json: Optional[str] = None) -> None:
    """Run a swarm preset with Rich Live dashboard."""
    from rich.live import Live
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore
    from src.swarm.models import RunStatus

    user_vars: Dict[str, str] = {}
    if vars_json:
        try:
            user_vars = json.loads(vars_json)
        except json.JSONDecodeError as exc:
            console.print(f"[red]Invalid JSON: {exc}[/red]")
            return

    store = SwarmStore(base_dir=SWARM_DIR)
    runtime = SwarmRuntime(store=store)
    _agent_color_map.clear()

    console.print(f"\n[dim]Starting swarm:[/dim] [cyan]{preset}[/cyan]")
    if user_vars:
        console.print(f"[dim]Variables:[/dim] {json.dumps(user_vars, ensure_ascii=False)}")

    dashboard = _SwarmDashboard(preset, "")

    try:
        run = runtime.start_run(preset, user_vars, live_callback=dashboard.handle_event)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    except ValueError as exc:
        console.print(f"[red]DAG validation failed: {exc}[/red]")
        return

    dashboard.run_id = run.id

    with Live(dashboard.build_table(), console=console, refresh_per_second=4, transient=False) as live:
        try:
            while True:
                time.sleep(0.25)
                live.update(dashboard.build_table())
                current = store.load_run(run.id)
                if current is None:
                    console.print("[red]Run record lost[/red]")
                    return
                if current.status in (RunStatus.completed, RunStatus.failed, RunStatus.cancelled):
                    dashboard.finished = True
                    dashboard.final_status = current.status.value
                    live.update(dashboard.build_table())
                    break
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelling...[/yellow]")
            runtime.cancel_run(run.id)
            time.sleep(1)
            current = store.load_run(run.id)

    if current is None:
        return

    # Print completed agent summaries
    for agent_name, summary in dashboard.completed_summaries:
        style = _get_agent_style(agent_name)
        console.print(f"\n[{style}]\u2500\u2500 {agent_name} \u2500\u2500[/{style}]")
        # Truncate to first meaningful chunk
        lines = summary.strip().split("\n")
        preview = "\n".join(lines[:8])
        if len(lines) > 8:
            preview += "\n[dim]...[/dim]"
        console.print(preview)

    # Final report
    status_color = {
        RunStatus.completed: "green",
        RunStatus.failed: "red",
        RunStatus.cancelled: "yellow",
    }.get(current.status, "dim")

    elapsed_total = time.monotonic() - dashboard.start_time
    mins, secs = divmod(int(elapsed_total), 60)

    tokens_in = current.total_input_tokens
    tokens_out = current.total_output_tokens
    token_str = ""
    if tokens_in or tokens_out:
        token_str = f"\nTokens: ~{tokens_in + tokens_out:,} (in: {tokens_in:,} out: {tokens_out:,})"

    if current.final_report:
        console.print(f"\n[bold]\u2500\u2500 Final Report \u2500\u2500[/bold]")
        console.print(current.final_report[:2000])

    console.print(f"\n[{status_color}]{current.status.value.upper()}[/{status_color}]  Time: {mins}m {secs}s{token_str}")


# ---------------------------------------------------------------------------
# Legacy subcommands (used by flags and slash commands)
# ---------------------------------------------------------------------------

def cmd_chat(max_iter: int) -> None:
    """Interactive mode (delegates to cmd_interactive)."""
    cmd_interactive(max_iter)


def cmd_list(limit: int = 20) -> None:
    """List run history."""
    if not RUNS_DIR.exists():
        console.print("[dim]No runs yet[/dim]")
        return
    dirs = sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()], key=lambda d: d.name, reverse=True)[:limit]
    if not dirs:
        console.print("[dim]No runs yet[/dim]")
        return

    table = Table(show_lines=False)
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Status", width=8)
    table.add_column("Return", width=10)
    table.add_column("Sharpe", width=8)
    table.add_column("Prompt", max_width=40)

    for d in dirs:
        st = _read_json(d / "state.json").get("status", "?")
        m = _read_metrics(d / "artifacts" / "metrics.csv")
        c = "green" if st == "success" else "red" if st == "failed" else "dim"
        table.add_row(d.name, f"[{c}]{st}[/{c}]", m.get("total_return", ""), m.get("sharpe", ""), (_read_json(d / "req.json").get("prompt") or "")[:40])

    console.print(table)


def cmd_show(run_id: str) -> None:
    """Show run details."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        console.print(f"[red]{run_id} not found[/red]")
        return

    state = _read_json(run_dir / "state.json")
    req = _read_json(run_dir / "req.json")
    metrics = _read_metrics(run_dir / "artifacts" / "metrics.csv")

    st = state.get("status", "unknown")
    c = "green" if st == "success" else "red"
    lines = [f"[bold]Status:[/bold] [{c}]{st.upper()}[/{c}]", f"[bold]Prompt:[/bold] {req.get('prompt', '?')}"]

    if metrics:
        lines.append("\n[bold]Metrics:[/bold]")
        lines.extend(f"  {k}: {v}" for k, v in metrics.items())

    from src.agent.trace import TraceWriter
    entries = TraceWriter.read(run_dir)
    answers = [e["content"] for e in entries if e.get("type") == "answer" and e.get("content")]
    if answers:
        summary = answers[-1][:200]
        lines.append(f"\n[bold]Answer:[/bold] {summary}{'...' if len(answers[-1]) > 200 else ''}")

    if state.get("reason"):
        lines.append(f"\n[bold]Reason:[/bold] {state['reason']}")

    console.print(Panel("\n".join(lines), border_style=c, title=run_id))
    console.print(f"[dim]{run_dir}[/dim]")


def cmd_code(run_id: str) -> None:
    """Show generated code."""
    code_dir = RUNS_DIR / run_id / "code"
    if not code_dir.exists():
        console.print(f"[red]{run_id}/code not found[/red]")
        return
    for name in ("signal_engine.py",):
        path = code_dir / name
        if path.exists():
            code = path.read_text(encoding="utf-8")
            console.print(Syntax(code, "python", theme="monokai", line_numbers=True), width=120)
            console.print()


def cmd_pine(run_id: str) -> None:
    """Show Pine Script for a run."""
    pine_path = RUNS_DIR / run_id / "artifacts" / "strategy.pine"
    if not pine_path.exists():
        console.print(f"[red]{run_id}/artifacts/strategy.pine not found[/red]")
        console.print("[dim]Ask the agent: \"export this strategy to Pine Script\"[/dim]")
        return
    code = pine_path.read_text(encoding="utf-8")
    console.print(Syntax(code, "javascript", theme="monokai", line_numbers=True), width=120)
    console.print()
    console.print("[dim]Copy and paste into TradingView Pine Editor → Add to Chart[/dim]")


def cmd_skills() -> None:
    """List available skills."""
    from src.agent.skills import SkillsLoader
    loader = SkillsLoader()

    table = Table(title="Skills", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for s in loader.skills:
        table.add_row(s.name, s.description)

    console.print(table)


def cmd_trace(run_id: str) -> None:
    """Replay trace.jsonl to show full execution."""
    from datetime import datetime
    from src.agent.trace import TraceWriter

    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        console.print(f"[red]{run_id} not found[/red]")
        return

    entries = TraceWriter.read(run_dir)
    if not entries:
        console.print(f"[red]{run_id}/trace.jsonl is empty or missing[/red]")
        return

    console.print(Panel(f"[bold]Trace replay: {run_id}[/bold]  ({len(entries)} entries)", border_style="cyan"))

    for entry in entries:
        etype = entry.get("type", "?")
        ts = entry.get("ts", 0)
        ts_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
        it = entry.get("iter", "")
        iter_tag = f"[dim]#{it}[/dim] " if it else ""

        if etype == "start":
            console.print(f"\n[bold cyan]{ts_str}[/bold cyan] {iter_tag}[bold]START[/bold]  {entry.get('prompt', '')[:120]}")
        elif etype == "thinking":
            content = entry.get("content", "")
            console.print(f"[dim]{ts_str}[/dim] {iter_tag}[dim italic]{content[:200]}[/dim italic]")
        elif etype == "tool_call":
            tool = entry.get("tool", "")
            args = entry.get("args", {})
            args_str = ", ".join(f"{k}={v[:40]}" for k, v in args.items()) if args else ""
            console.print(f"[dim]{ts_str}[/dim] {iter_tag}[cyan]\u25b6 {tool}[/cyan]({args_str})")
        elif etype == "tool_result":
            tool = entry.get("tool", "")
            status = entry.get("status", "ok")
            elapsed = entry.get("elapsed_ms", 0)
            ok = status == "ok"
            mark = "\u2713" if ok else "\u2717"
            color = "green" if ok else "red"
            preview = entry.get("preview", "")[:80]
            console.print(f"[dim]{ts_str}[/dim] {iter_tag}[{color}]{mark} {tool}[/{color}] [dim]{elapsed}ms[/dim]  {preview}")
        elif etype == "tool_skipped":
            console.print(f"[dim]{ts_str}[/dim] {iter_tag}[yellow]\u2298 {entry.get('tool', '')} (skipped)[/yellow]")
        elif etype == "answer":
            content = entry.get("content", "")
            console.print(f"\n[dim]{ts_str}[/dim] {iter_tag}[bold green]ANSWER[/bold green]\n{content[:500]}")
        elif etype == "end":
            status = entry.get("status", "?")
            iters = entry.get("iterations", "?")
            color = "green" if status == "success" else "red"
            console.print(f"\n[bold {color}]{ts_str} END[/bold {color}]  status={status}  iterations={iters}")

    console.print()


# ---------------------------------------------------------------------------
# Swarm subcommands
# ---------------------------------------------------------------------------

def cmd_swarm_presets() -> None:
    """List available swarm presets."""
    from src.swarm.presets import list_presets

    presets = list_presets()
    if not presets:
        console.print("[dim]No presets available[/dim]")
        return

    table = Table(title="Swarm Presets", show_lines=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Agents", width=8, justify="right")
    table.add_column("Variables")
    table.add_column("Description", max_width=40)

    for p in presets:
        raw_vars = p.get("variables", [])
        var_names = [
            v["name"] if isinstance(v, dict) else str(v) for v in raw_vars
        ]
        vars_str = ", ".join(var_names)
        table.add_row(
            p["name"],
            p.get("title", ""),
            str(p.get("agent_count", 0)),
            vars_str,
            p.get("description", "")[:40],
        )

    console.print(table)


def cmd_swarm_run(preset: str, vars_json: Optional[str] = None) -> None:
    """Run swarm preset (legacy polling mode, use cmd_swarm_run_live for streaming)."""
    cmd_swarm_run_live(preset, vars_json)


def cmd_swarm_list() -> None:
    """List swarm run history."""
    from src.swarm.store import SwarmStore

    store = SwarmStore(base_dir=SWARM_DIR)
    runs = store.list_runs()

    if not runs:
        console.print("[dim]No swarm runs yet[/dim]")
        return

    table = Table(title="Swarm Runs", show_lines=False)
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Preset")
    table.add_column("Status", width=12)
    table.add_column("Tasks", width=6, justify="right")
    table.add_column("Created", width=20)

    for run in runs:
        sc = {
            "completed": "green",
            "failed": "red",
            "cancelled": "yellow",
            "running": "blue",
        }.get(run.status.value, "dim")
        table.add_row(
            run.id,
            run.preset_name,
            f"[{sc}]{run.status.value}[/{sc}]",
            str(len(run.tasks)),
            run.created_at[:19],
        )

    console.print(table)


def cmd_swarm_show(run_id: str) -> None:
    """Show swarm run details."""
    from src.swarm.store import SwarmStore
    from src.swarm.models import TaskStatus

    store = SwarmStore(base_dir=SWARM_DIR)
    run = store.load_run(run_id)

    if run is None:
        console.print(f"[red]Swarm run {run_id} not found[/red]")
        return

    status_color = {
        "completed": "green",
        "failed": "red",
        "cancelled": "yellow",
        "running": "blue",
    }.get(run.status.value, "dim")

    lines = [
        f"[bold]Status:[/bold] [{status_color}]{run.status.value.upper()}[/{status_color}]",
        f"[bold]Preset:[/bold] {run.preset_name}",
        f"[bold]Created:[/bold] {run.created_at}",
    ]
    if run.completed_at:
        lines.append(f"[bold]Completed:[/bold] {run.completed_at}")
    if run.user_vars:
        lines.append(f"[bold]Variables:[/bold] {json.dumps(run.user_vars, ensure_ascii=False)}")

    tokens_in = run.total_input_tokens
    tokens_out = run.total_output_tokens
    if tokens_in or tokens_out:
        lines.append(f"[bold]Tokens:[/bold] ~{tokens_in + tokens_out:,} (in: {tokens_in:,} out: {tokens_out:,})")

    lines.append(f"\n[bold]Tasks ({len(run.tasks)}):[/bold]")
    for task in run.tasks:
        tc = "green" if task.status == TaskStatus.completed else "red" if task.status == TaskStatus.failed else "dim"
        dep_str = f" (deps: {', '.join(task.depends_on)})" if task.depends_on else ""
        task_line = f"  [{tc}]{task.id}[/{tc}] -> {task.agent_id}{dep_str} [{task.status.value}]"
        lines.append(task_line)
        if task.summary:
            lines.append(f"    {task.summary[:100]}")
        if task.error:
            lines.append(f"    [red]{task.error[:100]}[/red]")

    if run.final_report:
        lines.append(f"\n[bold]Final Report:[/bold]\n{run.final_report[:800]}")

    console.print(Panel("\n".join(lines), border_style=status_color, title=run_id))


def cmd_swarm_cancel(run_id: str) -> None:
    """Cancel a swarm run."""
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    store = SwarmStore(base_dir=SWARM_DIR)
    runtime = SwarmRuntime(store=store)

    if runtime.cancel_run(run_id):
        console.print(f"[yellow]Cancel signal sent: {run_id}[/yellow]")
    else:
        console.print(f"[red]Run {run_id} not found or already finished[/red]")


# ---------------------------------------------------------------------------
# Session subcommands
# ---------------------------------------------------------------------------

def cmd_sessions() -> None:
    """List chat sessions."""
    from src.session.store import SessionStore

    store = SessionStore(base_dir=SESSIONS_DIR)
    sessions = store.list_sessions()

    if not sessions:
        console.print("[dim]No sessions yet[/dim]")
        return

    table = Table(title="Sessions", show_lines=False)
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Title", max_width=30)
    table.add_column("Status", width=10)
    table.add_column("Messages", width=8, justify="right")
    table.add_column("Updated", width=20)

    for s in sessions:
        messages = store.get_messages(s.session_id)
        sc = "green" if s.status.value == "active" else "dim"
        table.add_row(
            s.session_id,
            s.title or "[dim]untitled[/dim]",
            f"[{sc}]{s.status.value}[/{sc}]",
            str(len(messages)),
            s.updated_at[:19],
        )

    console.print(table)


def cmd_session_chat(session_id: str, max_iter: int) -> None:
    """Continue a session chat."""
    from src.session.store import SessionStore

    store = SessionStore(base_dir=SESSIONS_DIR)
    session = store.get_session(session_id)

    if session is None:
        console.print(f"[red]Session {session_id} not found[/red]")
        return

    messages = store.get_messages(session_id)
    history: List[Dict[str, str]] = []
    for msg in messages:
        if msg.role in ("user", "assistant") and msg.content.strip():
            history.append({"role": msg.role, "content": msg.content})

    console.print(Panel(
        f"[bold cyan]Session: {session.title or session_id}[/bold cyan]\n"
        f"[dim]History: {len(messages)} messages | Type q to exit[/dim]",
        border_style="cyan",
    ))

    while True:
        try:
            prompt = Prompt.ask("\n[bold]>[/bold]").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not prompt or prompt.lower() in ("q", "quit", "exit"):
            break

        start = time.perf_counter()
        try:
            result = _run_agent(prompt, history=history[-6:], max_iter=max_iter)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted[/yellow]")
            continue

        _print_result(result, time.perf_counter() - start)
        history.append({"role": "user", "content": prompt})
        if result.get("content"):
            history.append({"role": "assistant", "content": result["content"]})

    console.print("[dim]Goodbye[/dim]")


# ---------------------------------------------------------------------------
# Upload subcommand
# ---------------------------------------------------------------------------

def cmd_upload(file_path: str) -> None:
    """Upload a file to the server."""
    src = Path(file_path)
    if not src.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return
    if not src.is_file():
        console.print(f"[red]Not a file: {file_path}[/red]")
        return

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ext = src.suffix
    dest_name = f"{uuid.uuid4().hex[:12]}{ext}"
    dest = UPLOADS_DIR / dest_name

    shutil.copy2(str(src), str(dest))
    console.print(f"[green]Uploaded:[/green] {dest}")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser with subcommands and compatibility flags."""
    parser = argparse.ArgumentParser(description="Vibe-Trading CLI")
    parser.add_argument("-p", "--prompt", type=str, help="Prompt text")
    parser.add_argument("-f", "--prompt-file", type=Path, help="Read prompt text from a file")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument("--no-rich", action="store_true", help="Disable Rich formatting")
    parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    parser.add_argument("--continue", dest="cont", nargs=2, metavar=("RUN_ID", "PROMPT"), help="Continue a run")
    parser.add_argument("--list", action="store_true", help="List runs")
    parser.add_argument("--show", metavar="RUN_ID", help="Show run details")
    parser.add_argument("--code", metavar="RUN_ID", help="Show generated code")
    parser.add_argument("--pine", metavar="RUN_ID", help="Show Pine Script for TradingView")
    parser.add_argument("--trace", metavar="RUN_ID", help="Replay a run trace")
    parser.add_argument("--skills", action="store_true", help="List skills")
    parser.add_argument("--max-iter", type=int, default=50, help="Maximum agent iterations")

    parser.add_argument("--swarm-presets", action="store_true", help="List swarm presets")
    parser.add_argument("--swarm-run", nargs="+", metavar=("PRESET", "VARS"), help="Run a swarm preset")
    parser.add_argument("--swarm-list", action="store_true", help="List swarm runs")
    parser.add_argument("--swarm-show", metavar="RUN_ID", help="Show a swarm run")
    parser.add_argument("--swarm-cancel", metavar="RUN_ID", help="Cancel a swarm run")

    parser.add_argument("--sessions", action="store_true", help="List sessions")
    parser.add_argument("--session-chat", metavar="SESSION_ID", help="Continue a session chat")
    parser.add_argument("--upload", metavar="FILE_PATH", help="Upload a file")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a prompt")
    run_parser.add_argument("-p", "--prompt", dest="run_prompt", type=str, help="Prompt text")
    run_parser.add_argument("-f", "--prompt-file", dest="run_prompt_file", type=Path, help="Read prompt text from a file")
    run_parser.add_argument("--json", dest="run_json", action="store_true", help="Print machine-readable JSON output")
    run_parser.add_argument("--no-rich", dest="run_no_rich", action="store_true", help="Disable Rich formatting")
    run_parser.add_argument("--max-iter", dest="run_max_iter", type=int, default=50, help="Maximum agent iterations")

    serve_parser = subparsers.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    serve_parser.add_argument("--port", type=int, default=8000, help="Listen port")
    serve_parser.add_argument("--dev", action="store_true", help="Start the Vite dev server")

    list_parser = subparsers.add_parser("list", help="List runs")
    list_parser.add_argument("--limit", dest="list_limit", type=int, default=20, help="Maximum number of runs")

    show_parser = subparsers.add_parser("show", help="Show run details")
    show_parser.add_argument("run_id", help="Run identifier")

    chat_parser = subparsers.add_parser("chat", help="Interactive chat mode")
    chat_parser.add_argument("--max-iter", dest="chat_max_iter", type=int, default=50, help="Maximum agent iterations")

    subparsers.add_parser("init", help="Interactive setup: create ~/.vibe-trading/.env")

    return parser


def _handle_prompt_command(
    prompt: Optional[str],
    prompt_file: Optional[Path],
    *,
    max_iter: int,
    json_mode: bool,
    no_rich: bool,
) -> int:
    """Resolve a prompt and execute it."""
    resolved_prompt, error_message = _read_prompt_source(prompt, prompt_file, no_rich=no_rich)
    if error_message:
        if json_mode:
            _print_json_result({"status": "failed", "run_id": None, "run_dir": None, "reason": error_message})
        else:
            message = error_message if no_rich else f"[red]{error_message}[/red]"
            print(error_message) if no_rich else console.print(message)
        return EXIT_USAGE_ERROR
    if not resolved_prompt:
        if json_mode:
            _print_json_result({"status": "failed", "run_id": None, "run_dir": None, "reason": "Prompt cannot be empty"})
        else:
            print("Prompt cannot be empty") if no_rich else console.print("[red]Prompt cannot be empty[/red]")
        return EXIT_USAGE_ERROR
    return cmd_run(resolved_prompt, max_iter, json_mode=json_mode, no_rich=no_rich)


_INIT_ENV_PATH = AGENT_DIR / ".env"

_PROVIDER_CHOICES: list[dict[str, str | None]] = [
    {
        "label": "OpenRouter (recommended - multiple models)",
        "provider": "openrouter",
        "key_env": "OPENROUTER_API_KEY",
        "base_env": "OPENROUTER_BASE_URL",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-v3.2",
        "key_prefix": "sk-or-",
        "key_placeholder": "sk-or-v1-...",
    },
    {
        "label": "DeepSeek",
        "provider": "deepseek",
        "key_env": "DEEPSEEK_API_KEY",
        "base_env": "DEEPSEEK_BASE_URL",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "key_prefix": "sk-",
        "key_placeholder": "sk-...",
    },
    {
        "label": "OpenAI",
        "provider": "openai",
        "key_env": "OPENAI_API_KEY",
        "base_env": "OPENAI_BASE_URL",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "key_prefix": "sk-",
        "key_placeholder": "sk-...",
    },
    {
        "label": "Gemini",
        "provider": "gemini",
        "key_env": "GEMINI_API_KEY",
        "base_env": "GEMINI_BASE_URL",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_prefix": None,
        "key_placeholder": "api-key...",
    },
    {
        "label": "Groq",
        "provider": "groq",
        "key_env": "GROQ_API_KEY",
        "base_env": "GROQ_BASE_URL",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_prefix": "gsk_",
        "key_placeholder": "gsk_...",
    },
    {
        "label": "DashScope / Qwen",
        "provider": "dashscope",
        "key_env": "DASHSCOPE_API_KEY",
        "base_env": "DASHSCOPE_BASE_URL",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "key_prefix": "sk-",
        "key_placeholder": "sk-...",
    },
    {
        "label": "Zhipu",
        "provider": "zhipu",
        "key_env": "ZHIPU_API_KEY",
        "base_env": "ZHIPU_BASE_URL",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "key_prefix": None,
        "key_placeholder": "api-key...",
    },
    {
        "label": "Moonshot / Kimi",
        "provider": "moonshot",
        "key_env": "MOONSHOT_API_KEY",
        "base_env": "MOONSHOT_BASE_URL",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "kimi-k2.5",
        "key_prefix": "sk-",
        "key_placeholder": "sk-...",
    },
    {
        "label": "MiniMax",
        "provider": "minimax",
        "key_env": "MINIMAX_API_KEY",
        "base_env": "MINIMAX_BASE_URL",
        "base_url": "https://api.minimax.io/v1",
        "model": "MiniMax-Text-01",
        "key_prefix": None,
        "key_placeholder": "api-key...",
    },
    {
        "label": "Xiaomi MIMO",
        "provider": "mimo",
        "key_env": "MIMO_API_KEY",
        "base_env": "MIMO_BASE_URL",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "MiMo-72B-A27B",
        "key_prefix": None,
        "key_placeholder": "api-key...",
    },
    {
        "label": "Z.ai (Coding platform)",
        "provider": "zai",
        "key_env": "ZAI_API_KEY",
        "base_env": "ZAI_BASE_URL",
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "model": "glm-5.1",
        "key_prefix": None,
        "key_placeholder": "api-key...",
    },
    {
        "label": "Ollama (local, free)",
        "provider": "ollama",
        "key_env": None,
        "base_env": "OLLAMA_BASE_URL",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:32b",
        "key_prefix": None,
        "key_placeholder": None,
    },
]


def _validate_api_key(api_key: str, expected_prefix: str | None) -> bool:
    """Basic API-key format validation used during interactive setup."""
    if expected_prefix is None:
        return True
    return api_key.startswith(expected_prefix)


def _render_env_content(config: dict[str, str]) -> str:
    """Render .env content with stable ordering."""
    ordered_keys = [
        "LANGCHAIN_TEMPERATURE",
        "LANGCHAIN_PROVIDER",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        "GROQ_API_KEY",
        "GROQ_BASE_URL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "ZHIPU_API_KEY",
        "ZHIPU_BASE_URL",
        "MOONSHOT_API_KEY",
        "MOONSHOT_BASE_URL",
        "MINIMAX_API_KEY",
        "MINIMAX_BASE_URL",
        "MIMO_API_KEY",
        "MIMO_BASE_URL",
        "ZAI_API_KEY",
        "ZAI_BASE_URL",
        "OLLAMA_BASE_URL",
        "LANGCHAIN_MODEL_NAME",
        "TUSHARE_TOKEN",
        "TIMEOUT_SECONDS",
        "MAX_RETRIES",
    ]
    lines: list[str] = []
    for key in ordered_keys:
        value = config.get(key)
        if value:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def cmd_init() -> int:
    """Interactive setup: create agent/.env."""
    console.print("[bold cyan]Welcome to Vibe-Trading setup![/bold cyan]\n")

    if _INIT_ENV_PATH.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {_INIT_ENV_PATH}")
        if not Confirm.ask("Overwrite it?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return 0

    console.print("Select your LLM provider:")
    for idx, option in enumerate(_PROVIDER_CHOICES, start=1):
        console.print(f"  {idx}. {option['label']}")

    choice = IntPrompt.ask(
        "Provider",
        choices=[str(i) for i in range(1, len(_PROVIDER_CHOICES) + 1)],
        default=1,
        show_choices=False,
    )
    selected = _PROVIDER_CHOICES[choice - 1]

    provider = str(selected["provider"])
    key_env = selected["key_env"]
    base_env = str(selected["base_env"])
    default_base_url = str(selected["base_url"])
    default_model = str(selected["model"])
    key_prefix = selected["key_prefix"]
    key_placeholder = selected["key_placeholder"]

    env_values: dict[str, str] = {
        "LANGCHAIN_TEMPERATURE": "0.0",
        "LANGCHAIN_PROVIDER": provider,
        "LANGCHAIN_MODEL_NAME": default_model,
        "TIMEOUT_SECONDS": "120",
        "MAX_RETRIES": "2",
    }

    if key_env is not None:
        while True:
            api_key = Prompt.ask(
                f"Enter your {provider.capitalize()} API key",
                default=str(key_placeholder),
                password=True,
                show_default=False,
            ).strip()
            if _validate_api_key(api_key, str(key_prefix) if key_prefix is not None else None):
                env_values[str(key_env)] = api_key
                break
            console.print(
                f"[red]That key doesn't look right.[/red] Expected it to start with [bold]{key_prefix}[/bold]."
            )
    else:
        console.print("[dim]Ollama does not require an API key.[/dim]")

    env_values[base_env] = Prompt.ask(
        "Base URL",
        default=default_base_url,
        show_default=True,
    ).strip()

    env_values["LANGCHAIN_MODEL_NAME"] = Prompt.ask(
        "Select default model",
        default=default_model,
        show_default=True,
    ).strip()

    tushare_token = Prompt.ask(
        "(Optional) Enter Tushare token for China A-share data",
        default="",
        show_default=False,
    ).strip()
    if tushare_token:
        env_values["TUSHARE_TOKEN"] = tushare_token

    _INIT_ENV_PATH.write_text(_render_env_content(env_values), encoding="utf-8")

    console.print(f"\n[green]✅ Created {_INIT_ENV_PATH} — you're ready to go![/green]")
    console.print("[dim]Run:[/dim] [bold]vibe-trading[/bold]")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint returning a process exit code."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    try:
        args = parser.parse_args(raw_argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE_ERROR

    if args.command == "init":
        return cmd_init()
    if args.command == "serve":
        return serve_main(raw_argv[1:])
    if args.command == "run":
        return _handle_prompt_command(
            args.run_prompt,
            args.run_prompt_file,
            max_iter=args.run_max_iter,
            json_mode=args.run_json,
            no_rich=args.run_no_rich,
        )
    if args.command == "list":
        return _coerce_exit_code(cmd_list(args.list_limit))
    if args.command == "show":
        return _coerce_exit_code(cmd_show(args.run_id))
    if args.command == "chat":
        return _coerce_exit_code(cmd_interactive(args.chat_max_iter))

    if args.list:
        return _coerce_exit_code(cmd_list())
    if args.show:
        return _coerce_exit_code(cmd_show(args.show))
    if args.code:
        return _coerce_exit_code(cmd_code(args.code))
    if args.pine:
        return _coerce_exit_code(cmd_pine(args.pine))
    if args.trace:
        return _coerce_exit_code(cmd_trace(args.trace))
    if args.skills:
        return _coerce_exit_code(cmd_skills())

    if args.swarm_presets:
        return _coerce_exit_code(cmd_swarm_presets())
    if args.swarm_run:
        preset_name = args.swarm_run[0]
        vars_json = args.swarm_run[1] if len(args.swarm_run) > 1 else None
        return _coerce_exit_code(cmd_swarm_run_live(preset_name, vars_json))
    if args.swarm_list:
        return _coerce_exit_code(cmd_swarm_list())
    if args.swarm_show:
        return _coerce_exit_code(cmd_swarm_show(args.swarm_show))
    if args.swarm_cancel:
        return _coerce_exit_code(cmd_swarm_cancel(args.swarm_cancel))

    if args.sessions:
        return _coerce_exit_code(cmd_sessions())
    if args.session_chat:
        return _coerce_exit_code(cmd_session_chat(args.session_chat, args.max_iter))
    if args.upload:
        return _coerce_exit_code(cmd_upload(args.upload))
    if args.chat:
        return _coerce_exit_code(cmd_interactive(args.max_iter))
    if args.cont:
        return cmd_continue(args.cont[0], args.cont[1], args.max_iter, json_mode=args.json, no_rich=args.no_rich)

    # No flags, no subcommand → check if prompt provided, otherwise interactive mode
    if args.prompt or args.prompt_file or not sys.stdin.isatty():
        return _handle_prompt_command(
            args.prompt,
            args.prompt_file,
            max_iter=args.max_iter,
            json_mode=args.json,
            no_rich=args.no_rich,
        )

    # Default: interactive mode
    return _coerce_exit_code(cmd_interactive(args.max_iter))


if __name__ == "__main__":
    raise SystemExit(main())
