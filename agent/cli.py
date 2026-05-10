#!/usr/bin/env python3
"""Vibe-Trading CLI for natural-language finance research and backtesting.

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
import threading
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
from rich import box
from rich.columns import Columns
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

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

_VERSION = "0.1.7"

# Agent color assignments for swarm display
_AGENT_STYLES = ["cyan", "magenta", "green", "yellow", "blue", "bright_red", "bright_cyan", "bright_magenta"]
_agent_color_map: dict[str, str] = {}

_HAS_PROMPT_TOOLKIT = False
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import InMemoryHistory

    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    pass


class _SessionStats:
    """Mutable container for interactive session statistics.

    Shared between the status bar renderer and the agent loop so that
    tool callbacks can update counters in-place.
    """

    __slots__ = ("session_start", "last_elapsed", "total_tool_ms", "tool_count")

    def __init__(self, session_start: float) -> None:
        self.session_start = session_start
        self.last_elapsed: Optional[float] = None
        self.total_tool_ms = 0
        self.tool_count = 0


def _build_status_parts(stats: _SessionStats) -> list[str]:
    """Build plain-text status bar segments.

    Args:
        stats: Session statistics.

    Returns:
        List of status text segments.
    """
    provider = os.getenv("LANGCHAIN_PROVIDER", "")
    model = os.getenv("LANGCHAIN_MODEL_NAME", "")
    model_short = model.split("/")[-1] if "/" in model else model
    label = f"{provider}/{model_short}" if provider else model_short or "unknown"

    session_s = int(time.monotonic() - stats.session_start)
    mins, secs = divmod(session_s, 60)
    session_str = f"{mins}m{secs:02d}s" if mins else f"{secs}s"

    parts = [label, session_str]

    if stats.last_elapsed is not None:
        parts.append(f"last {stats.last_elapsed:.1f}s")

    if stats.tool_count > 0:
        total_s = stats.total_tool_ms / 1000
        parts.append(f"{stats.tool_count} tools ({total_s:.1f}s)")

    return parts


def _ptk_toolbar(stats: _SessionStats) -> FormattedText:
    """prompt_toolkit bottom_toolbar callback — called on every render.

    Args:
        stats: Session statistics.

    Returns:
        FormattedText for the toolbar.
    """
    segments = _build_status_parts(stats)
    text = " │ ".join(segments)
    return FormattedText([("class:bottom-toolbar.text", f" {text} ")])


def _print_status_bar(stats: _SessionStats) -> None:
    """Print a static status bar using Rich (fallback without prompt_toolkit).

    Args:
        stats: Session statistics.
    """
    parts = _build_status_parts(stats)
    bar = "[dim] │ [/dim]".join(
        f"[bold]{parts[0]}[/bold]" if i == 0 else p for i, p in enumerate(parts)
    )
    console.print(bar)


def _create_prompt_session(stats: _SessionStats) -> Any:
    """Create a prompt_toolkit PromptSession with history and live toolbar.

    Args:
        stats: Session statistics for the live bottom toolbar.

    Returns:
        A PromptSession instance, or None if prompt_toolkit is not available.
    """
    if not _HAS_PROMPT_TOOLKIT:
        return None
    return PromptSession(
        history=InMemoryHistory(),
        bottom_toolbar=lambda: _ptk_toolbar(stats),
        refresh_interval=1.0,
    )


def _read_input(prompt_session: Any, prompt_str: str = "> ") -> str:
    """Read user input with arrow key support if prompt_toolkit is available.

    Falls back to Rich Prompt.ask() when prompt_toolkit is not installed or
    when stdin is not a tty.

    Args:
        prompt_session: A prompt_toolkit PromptSession, or None.
        prompt_str: Prompt text to display.

    Returns:
        User input string (not stripped).

    Raises:
        EOFError: When the user presses Ctrl-D.
        KeyboardInterrupt: When the user presses Ctrl-C.
    """
    if prompt_session is not None and sys.stdin.isatty():
        return prompt_session.prompt(prompt_str)
    return Prompt.ask(f"[bold]{prompt_str}[/bold]")


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


def _status_style(status: str) -> str:
    """Return a consistent Rich color for status labels."""
    return {
        "success": "green",
        "completed": "green",
        "ready": "green",
        "running": "cyan",
        "failed": "red",
        "error": "red",
        "cancelled": "yellow",
        "warning": "yellow",
    }.get((status or "").lower(), "dim")


def _format_seconds(seconds: float) -> str:
    """Format elapsed seconds for compact terminal display."""
    total = max(0, int(seconds))
    mins, secs = divmod(total, 60)
    if mins >= 60:
        hours, mins = divmod(mins, 60)
        return f"{hours:d}h {mins:02d}m"
    if mins:
        return f"{mins:d}m {secs:02d}s"
    return f"{secs:d}s"


def _configured_label(value: str | None) -> str:
    """Render a masked configuration state."""
    return "[green]configured[/green]" if value else "[yellow]not set[/yellow]"


def _state_badge(value: str | None, *, ready_label: str = "READY") -> str:
    """Render a compact terminal status badge."""
    return f"[black on green] {ready_label} [/]" if value else "[black on yellow] MISSING [/]"


def _terminal_width() -> int:
    """Return the active console width with a conservative fallback."""
    try:
        return max(40, int(console.size.width))
    except Exception:
        return 80


def _ensure_cli_env() -> None:
    """Load dotenv values before rendering CLI-only settings."""
    try:
        from src.providers.llm import _ensure_dotenv

        _ensure_dotenv()
    except Exception:
        pass


def _provider_key_env(provider: str | None) -> str | None:
    """Return the credential environment variable for a provider."""
    return {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "zhipu": "ZHIPU_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "mimo": "MIMO_API_KEY",
        "zai": "ZAI_API_KEY",
    }.get((provider or "").lower())


def _provider_base_env(provider: str | None) -> str | None:
    """Return the base URL environment variable for a provider."""
    return {
        "openrouter": "OPENROUTER_BASE_URL",
        "openai": "OPENAI_BASE_URL",
        "openai-codex": "OPENAI_CODEX_BASE_URL",
        "deepseek": "DEEPSEEK_BASE_URL",
        "gemini": "GEMINI_BASE_URL",
        "groq": "GROQ_BASE_URL",
        "dashscope": "DASHSCOPE_BASE_URL",
        "qwen": "DASHSCOPE_BASE_URL",
        "zhipu": "ZHIPU_BASE_URL",
        "moonshot": "MOONSHOT_BASE_URL",
        "minimax": "MINIMAX_BASE_URL",
        "mimo": "MIMO_BASE_URL",
        "zai": "ZAI_BASE_URL",
        "ollama": "OLLAMA_BASE_URL",
    }.get((provider or "").lower())


def _clip_inline(text: str, limit: int) -> str:
    """Collapse whitespace and clip text for single-line terminal cells."""
    clipped = " ".join(str(text or "").split())
    if len(clipped) <= limit:
        return clipped
    return clipped[: max(0, limit - 3)] + "..."


def _fit_cell(text: str, width: int) -> str:
    """Clip and pad text to an exact display cell width."""
    width = max(1, width)
    return _clip_inline(text, width).ljust(width)


def _styled_line(parts: list[tuple[str, int | None, str]]) -> Text:
    """Build one fixed-width line with per-cell styling."""
    line = Text()
    for value, width, style in parts:
        rendered = value if width is None else _fit_cell(value, width)
        line.append(rendered, style=style)
    return line


def _stack_text(lines: list[Text]) -> Text:
    """Join Text lines while preserving segment styles."""
    out = Text()
    for idx, line in enumerate(lines):
        if idx:
            out.append("\n")
        out.append_text(line)
    return out


def _welcome_widths(term_width: int) -> dict[str, int]:
    """Calculate welcome-screen column widths from the terminal width."""
    content_width = max(34, term_width - 8)
    label = 10
    right_label = 10
    right_value = 8
    gap = 2 if term_width < 86 else 4
    left_value = max(10, content_width - label - gap - right_label - right_value)

    command_gap = 2 if term_width < 86 else 6
    pair_width = max(20, (content_width - command_gap) // 2)
    action = min(16, max(12, pair_width // 2))
    use = max(7, pair_width - action - 1)

    return {
        "content": content_width,
        "label": label,
        "left_value": left_value,
        "gap": gap,
        "right_label": right_label,
        "right_value": right_value,
        "action": action,
        "use": use,
        "command_gap": command_gap,
    }


def _metric_value_style(key: str, value: str) -> str:
    """Return a compact color style for numeric metric values."""
    if key in {"total_return", "sharpe", "excess_return", "information_ratio"}:
        try:
            return "green" if float(value) >= 0 else "red"
        except (TypeError, ValueError):
            return "white"
    if key == "max_drawdown":
        return "yellow"
    return "white"


class _RunDashboard:
    """Render a compact live view for a single agent run."""

    def __init__(self, prompt: str, max_iter: int) -> None:
        self.prompt = prompt
        self.max_iter = max_iter
        self.start_time = time.monotonic()
        self.iterations = 0
        self.current_tool = "thinking"
        self.current_args = ""
        self.latest_text = ""
        self.timeline: list[tuple[str, str, str, float, str]] = []
        self.status = "running"
        self.live: Optional[Live] = None

    def refresh(self) -> None:
        """Refresh the live display when attached to a Rich Live context."""
        if self.live is not None:
            self.live.update(self.render())

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Update the dashboard from AgentLoop UI events."""
        if event_type == "text_delta":
            delta = data.get("delta", "")
            if delta:
                self.latest_text = (self.latest_text + delta).strip()[-260:]
                self.refresh()
            return

        if event_type == "thinking_done":
            self.current_tool = "thinking"
            self.current_args = ""
            self.refresh()
            return

        if event_type == "tool_call":
            tool = data.get("tool", "")
            args = data.get("arguments", {})
            self.iterations += 1
            self.current_tool = tool or "tool"
            self.current_args = _strip_rich_tags(_format_tool_call_args(tool, args)).strip()
            self.timeline.append(("running", self.current_tool, self.current_args, 0.0, ""))
            self.timeline = self.timeline[-8:]
            self.refresh()
            return

        if event_type == "tool_result":
            tool = data.get("tool", self.current_tool)
            status = data.get("status", "ok")
            elapsed_s = float(data.get("elapsed_ms", 0) or 0) / 1000
            preview = _strip_rich_tags(_format_tool_result_preview(tool, status, data.get("preview", "")))
            row_status = "success" if status == "ok" else "failed"
            if self.timeline and self.timeline[-1][0] == "running":
                self.timeline[-1] = (row_status, tool, self.timeline[-1][2], elapsed_s, preview)
            else:
                self.timeline.append((row_status, tool, "", elapsed_s, preview))
            self.timeline = self.timeline[-8:]
            self.current_tool = "thinking"
            self.current_args = ""
            self.refresh()
            return

        if event_type == "compact":
            tokens = data.get("tokens_before", "?")
            self.timeline.append(("warning", "context", "", 0.0, f"compressed after {tokens} tokens"))
            self.timeline = self.timeline[-8:]
            self.refresh()

    def render(self) -> Panel:
        """Build the Rich renderable shown while the run is active."""
        term_width = _terminal_width()
        compact = term_width < 86
        content_width = max(32, term_width - (6 if compact else 10))
        elapsed = _format_seconds(time.monotonic() - self.start_time)
        prompt_preview = _clip_inline(self.prompt, min(96, max(22, content_width - 12)))

        meta = Table.grid(expand=True)
        meta.add_column(ratio=1)
        progress = min(1.0, self.iterations / max(1, self.max_iter))
        bar_width = 12 if compact else 20
        filled = max(1, int(progress * bar_width)) if self.iterations else 0
        bar = "#" * filled + "-" * (bar_width - filled)
        progress_text = f"[cyan]{elapsed}[/cyan]  [dim]{bar} {self.iterations}/{self.max_iter}[/dim]"
        if compact:
            meta.add_row("[bold cyan]Running agent[/bold cyan]")
            meta.add_row(progress_text)
            meta.add_row(f"[dim]Request: {prompt_preview}[/dim]")
        else:
            meta.add_column(justify="right")
            meta.add_row("[bold cyan]Running agent[/bold cyan]", progress_text)
            meta.add_row(f"[dim]Request: {prompt_preview}[/dim]", "")

        current = Table.grid(expand=True)
        current.add_column(width=8 if compact else 9, style="dim")
        current.add_column(ratio=1)
        tool_label = self.current_tool
        if self.current_args:
            tool_label = f"{tool_label} [dim]{_clip_inline(self.current_args, max(20, content_width - 18))}[/dim]"
        current.add_row("Current", f"[cyan]{tool_label}[/cyan]")

        timeline = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="dim",
            padding=(0, 1),
            expand=True,
        )
        timeline.add_column("State", width=7 if compact else 8, no_wrap=True)
        timeline.add_column("Tool", width=12 if compact else 20, no_wrap=True)
        timeline.add_column("Time", width=6 if compact else 8, justify="right")
        timeline.add_column("Detail", ratio=1, overflow="fold")
        rows = self.timeline[-6:] or [("running", "waiting", "", 0.0, "starting")]
        for status, tool, args, elapsed_s, preview in rows:
            style = _status_style(status)
            label = "running" if status == "running" else ("ok" if status == "success" else "check")
            detail = _clip_inline(preview or args, max(18, content_width - (35 if compact else 48)))
            timeline.add_row(
                f"[{style}]{label}[/{style}]",
                _clip_inline(tool, 12 if compact else 20),
                f"{elapsed_s:.1f}s" if elapsed_s else "",
                detail,
            )

        latest = self.latest_text.replace("\n", " ").strip()
        latest = _clip_inline(latest[-220:], max(24, content_width - 4))
        body = Table.grid(expand=True)
        body.add_row(meta)
        body.add_row("")
        body.add_row(current)
        body.add_row("")
        body.add_row(timeline)
        if latest:
            body.add_row("")
            body.add_row(Panel(Text(latest, style="dim"), title="Latest answer", border_style="dim", padding=(0, 1)))

        return Panel(body, title="Vibe-Trading", border_style="cyan", padding=(1, 1 if compact else 2))


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
    if tool == "check_background":
        tid = args.get("task_id", "")
        return f' {tid}' if tid else ""
    if tool in ("backtest", "compact"):
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
    if tool == "render_shadow_report":
        url = re.search(r'"report_url":\s*"([^"]+)"', preview)
        if url:
            return f"[bold cyan]report:[/bold cyan] [link]{url.group(1)}[/link]"
        return ""
    if tool in ("extract_shadow_strategy", "run_shadow_backtest"):
        sid = re.search(r'"shadow_id":\s*"([^"]+)"', preview)
        return f"shadow_id={sid.group(1)}" if sid else ""
    if tool in ("bash", "background_run"):
        if "OK" in preview[:50]:
            return "OK"
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
    dashboard: Optional[_RunDashboard] = None,
) -> dict:
    """Build AgentLoop and execute, return result dict."""
    from src.tools import build_registry
    from src.providers.chat import ChatLLM
    from src.agent.loop import AgentLoop

    def on_event(event_type: str, data: Dict[str, Any]) -> None:
        if not stream_output:
            return
        if dashboard is not None and not no_rich:
            dashboard.handle_event(event_type, data)
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

    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory()
    agent = AgentLoop(
        registry=build_registry(persistent_memory=pm, include_shell_tools=True),
        llm=ChatLLM(),
        event_callback=on_event,
        max_iterations=max_iter,
        persistent_memory=pm,
    )
    if run_dir_override:
        agent.memory.run_dir = run_dir_override

    return agent.run(user_message=prompt, history=history)


def _build_benchmark_table(m: dict) -> Optional[Table]:
    """Build a benchmark comparison table from metrics dict.

    Args:
        m: Metrics dictionary (from _read_metrics or result dict).

    Returns:
        Rich Table, or None if no benchmark data is present.
    """
    bench_ticker  = m.get("benchmark_ticker")
    bench_ret_str = m.get("benchmark_return")
    bench_ret_raw = m.get("_benchmark_return_raw")

    # Fall back to equity.csv if benchmark cols not in metrics.csv yet
    if not bench_ticker:
        return None

    # Parse benchmark return
    if bench_ret_raw is not None:
        bench_ret = bench_ret_raw
    elif bench_ret_str is not None:
        try:
            bench_ret = float(bench_ret_str)
        except (ValueError, TypeError):
            bench_ret = None
    else:
        bench_ret = None

    strategy_ret_str = m.get("total_return")
    strategy_ret     = float(strategy_ret_str) if strategy_ret_str else None

    table = Table(show_header=False, padding=(0, 2))
    table.add_column("Label", style="dim", width=20)
    table.add_column("Value", style="white no_wrap")

    table.add_row("[dim]Benchmark[/dim]",  bench_ticker)

    if bench_ret is not None:
        table.add_row("[dim]Benchmark Return[/dim]", f"{bench_ret * 100:+.2f}%")

    if strategy_ret is not None and bench_ret is not None:
        excess = strategy_ret - bench_ret
        sign   = "+" if excess >= 0 else ""
        style  = "green" if excess >= 0 else "red"
        table.add_row(
            "[dim]vs Benchmark[/dim]",
            f"[{style}]{sign}{excess * 100:+.2f}%[/{style}]",
        )

    ir_str = m.get("information_ratio")
    if ir_str:
        table.add_row("[dim]Info Ratio[/dim]", ir_str)

    excess_str = m.get("excess_return")
    if excess_str and excess_str != "0" and excess_str != "0.0000":
        table.add_row("[dim]Excess Return[/dim]", f"{float(excess_str) * 100:+.2f}%")

    return table


def _print_result(result: dict, elapsed: float, *, no_rich: bool = False) -> None:
    """Print execution result panel."""
    status = result.get("status", "unknown")
    style = _status_style(status)
    run_dir = result.get("run_dir")
    m = _read_metrics(Path(run_dir) / "artifacts" / "metrics.csv") if run_dir else {}

    if no_rich:
        print(f"Status: {status.upper()}")
        print(f"Elapsed: {_format_seconds(elapsed)}")
        if result.get("run_id"):
            print(f"Run ID: {result['run_id']}")
        review = result.get("review")
        if review and review.get("overall_score") is not None:
            review_status = "PASS" if review.get("passed") else "FAIL"
            print(f"Review: {review_status} {review['overall_score']}pts")
        if run_dir:
            print(f"Run dir: {run_dir}")
        if result.get("reason"):
            print(f"Reason: {result['reason']}")
        metric_parts = [f"{label}={m[key]}" for key, label in (
            ("total_return", "return"),
            ("sharpe", "sharpe"),
            ("max_drawdown", "max_dd"),
            ("trade_count", "trades"),
        ) if key in m]
        if metric_parts:
            print(f"Metrics: {', '.join(metric_parts)}")
        content = result.get("content", "").strip()
        if content:
            print(f"\n{content}")
        return

    summary = Table.grid(expand=True)
    summary.add_column(width=12, style="dim")
    summary.add_column(ratio=1)
    summary.add_row("Status", f"[bold {style}]{status.upper()}[/bold {style}]")
    summary.add_row("Elapsed", _format_seconds(elapsed))
    if result.get("run_id"):
        summary.add_row("Run ID", f"[cyan]{result['run_id']}[/cyan]")
    review = result.get("review")
    if review and review.get("overall_score") is not None:
        review_status = "PASS" if review.get("passed") else "FAIL"
        review_style = "green" if review.get("passed") else "red"
        summary.add_row("Review", f"[{review_style}]{review_status}[/{review_style}] {review['overall_score']}pts")
    if run_dir:
        summary.add_row("Run dir", f"[dim]{run_dir}[/dim]")

    if result.get("reason"):
        summary.add_row("Reason", f"[red]{result['reason']}[/red]")

    panels = [Panel(summary, border_style=style, title="Summary", padding=(0, 1))]

    metric_table = Table.grid(expand=True)
    metric_table.add_column(width=12, style="dim")
    metric_table.add_column(ratio=1)
    has_metrics = False
    for key, label in (
        ("total_return", "Return"),
        ("sharpe", "Sharpe"),
        ("max_drawdown", "Max DD"),
        ("trade_count", "Trades"),
    ):
        if key not in m:
            continue
        value = m[key]
        value_style = _metric_value_style(key, value)
        metric_table.add_row(label, f"[{value_style}]{value}[/{value_style}]")
        has_metrics = True
    if has_metrics:
        panels.append(Panel(metric_table, border_style="cyan", title="Metrics", padding=(0, 1)))

    if result.get("run_id"):
        rid = result["run_id"]
        actions = Table(box=None, show_header=False, padding=(0, 1))
        actions.add_column(style="cyan", no_wrap=True)
        actions.add_column(style="dim")
        actions.add_row(f"vibe-trading show {rid}", "details")
        actions.add_row(f"vibe-trading code {rid}", "generated Python")
        actions.add_row(f"vibe-trading continue {rid} \"...\"", "refine this run")
        panels.append(Panel(actions, border_style="dim", title="Next", padding=(0, 1)))

    if _terminal_width() < 104:
        for panel in panels:
            console.print(panel)
    else:
        console.print(Columns(panels, expand=True, equal=True))

    # Benchmark comparison panel.
    bench_table = _build_benchmark_table(m)
    if bench_table:
        console.print(Panel(
            bench_table,
            border_style="cyan",
            title="Benchmark Comparison",
            padding=(0, 1),
        ))
    # End benchmark comparison panel.

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
        if json_mode or no_rich:
            result = _run_agent(prompt, max_iter=max_iter, no_rich=no_rich, stream_output=not json_mode)
        else:
            dashboard = _RunDashboard(prompt, max_iter)
            with Live(dashboard.render(), console=console, refresh_per_second=6, transient=True) as live:
                dashboard.live = live
                result = _run_agent(prompt, max_iter=max_iter, dashboard=dashboard)
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
        dashboard = _RunDashboard(prompt, max_iter)
        with Live(dashboard.render(), console=console, refresh_per_second=6, transient=True) as live:
            dashboard.live = live
            result = _run_agent(
                prompt,
                history=history,
                run_dir_override=str(run_dir),
                max_iter=max_iter,
                dashboard=dashboard,
            )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return EXIT_RUN_FAILED
    _print_result(result, time.perf_counter() - start)
    return _result_exit_code(result)


# ---------------------------------------------------------------------------
# Interactive mode (Welcome + Slash commands + Swarm streaming)
# ---------------------------------------------------------------------------

def _build_welcome_panel(term_width: Optional[int] = None) -> Panel:
    """Build the welcome screen for the given terminal width."""
    _ensure_cli_env()
    term_width = term_width or _terminal_width()
    compact = term_width < 64
    widths = _welcome_widths(term_width)
    provider = os.getenv("LANGCHAIN_PROVIDER", "(not set)")
    model = os.getenv("LANGCHAIN_MODEL_NAME", "(not set)")
    key_env = _provider_key_env(provider)
    key_value = os.getenv(key_env or "")
    credential_ready = provider in {"ollama", "openai-codex"} or bool(key_value)
    key_state = "READY" if credential_ready else "MISSING"
    recent_runs = len([d for d in RUNS_DIR.iterdir() if d.is_dir()]) if RUNS_DIR.exists() else 0
    recent_swarms = len([d for d in SWARM_DIR.iterdir() if d.is_dir()]) if SWARM_DIR.exists() else 0
    content_width = widths["content"]

    header_lines: list[Text] = []
    title = f"Vibe-Trading v{_VERSION}"
    subtitle = "finance agent CLI"
    if term_width < 78:
        header_lines.append(Text(title, style="bold cyan"))
        header_lines.append(Text(subtitle, style="dim"))
    else:
        header_lines.append(
            _styled_line(
                [
                    (title, content_width - len(subtitle), "bold cyan"),
                    (subtitle, None, "dim"),
                ]
            )
        )
    header_lines.append(Text(_clip_inline("Research, backtest, inspect runs, and coordinate swarm presets.", content_width), style="dim"))

    config_lines: list[Text] = []
    if compact:
        value_width = max(10, content_width - widths["label"] - 1)
        rows = [
            ("Provider", str(provider), "bold cyan"),
            ("Model", str(model), "white"),
            ("Credential", key_state, "bold green" if credential_ready else "bold yellow"),
            ("Runs", str(recent_runs), "cyan"),
            ("Swarms", str(recent_swarms), "cyan"),
            ("Workspace", str(AGENT_DIR), "dim"),
        ]
        for label, value, value_style in rows:
            config_lines.append(
                _styled_line(
                    [
                        (label, widths["label"], "dim"),
                        (" ", None, ""),
                        (value, value_width, value_style),
                    ]
                )
            )
    else:
        gap = " " * widths["gap"]
        rows = [
            ("Provider", str(provider), "bold cyan", "Credential", key_state, "bold green" if credential_ready else "bold yellow"),
            ("Model", str(model), "white", "Runs", str(recent_runs), "cyan"),
            ("Workspace", str(AGENT_DIR), "dim", "Swarms", str(recent_swarms), "cyan"),
        ]
        for left_label, left_value, left_style, right_label, right_value, right_style in rows:
            config_lines.append(
                _styled_line(
                    [
                        (left_label, widths["label"], "dim"),
                        (" ", None, ""),
                        (left_value, widths["left_value"], left_style),
                        (gap, None, ""),
                        (right_label, widths["right_label"], "dim"),
                        (" ", None, ""),
                        (right_value, widths["right_value"], right_style),
                    ]
                )
            )

    action_lines: list[Text] = []
    if compact:
        actions = [
            ("type a request", "start a run"),
            ("/settings", "check config"),
            ("/list", "recent runs"),
            ("/swarm", "team presets"),
            ("/help", "all commands"),
            ("/quit", "exit"),
        ]
        action_width = min(16, max(12, content_width // 2 - 1))
        use_width = max(8, content_width - action_width - 1)
        for action, use in actions:
            action_lines.append(
                _styled_line(
                    [
                        (action, action_width, "bold cyan"),
                        (" ", None, ""),
                        (use, use_width, "white"),
                    ]
                )
            )
    else:
        gap = " " * widths["command_gap"]
        rows = [
            ("type a request", "start a run", "/settings", "check config"),
            ("/list", "recent runs", "/swarm", "team presets"),
            ("/help", "all commands", "/quit", "exit"),
        ]
        for left_action, left_use, right_action, right_use in rows:
            action_lines.append(
                _styled_line(
                    [
                        (left_action, widths["action"], "bold cyan"),
                        (" ", None, ""),
                        (left_use, widths["use"], "white"),
                        (gap, None, ""),
                        (right_action, widths["action"], "bold cyan"),
                        (" ", None, ""),
                        (right_use, widths["use"], "white"),
                    ]
                )
            )

    body = Table.grid(expand=True)
    body.add_row(_stack_text(header_lines))
    body.add_row("")
    body.add_row(
        Panel(
            _stack_text(config_lines),
            title="[bold green]Current Config[/bold green]",
            border_style="green" if credential_ready else "yellow",
            padding=(0, 1),
        )
    )
    body.add_row("")
    body.add_row(
        Panel(
            _stack_text(action_lines),
            title="[bold magenta]Actions[/bold magenta]",
            border_style="magenta",
            padding=(0, 1),
        )
    )
    body.add_row("")
    body.add_row(Text(_clip_inline("Example: analyze AAPL momentum with risk controls", content_width), style="dim"))

    return Panel(body, title="[bold cyan]Vibe-Trading[/bold cyan]", border_style="cyan", padding=(1, 1))


def _print_welcome() -> None:
    """Print the welcome screen."""
    console.print(_build_welcome_panel())


def _print_help() -> None:
    """Print all available slash commands."""
    table = Table(title="Commands", show_lines=False, border_style="dim", box=box.SIMPLE_HEAVY)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description")

    cmds = [
        ("/help", "Show this command list"),
        ("/skills", "List available trading skills"),
        ("/list", "List recent backtest and research runs"),
        ("/show <run_id>", "Open a compact run summary"),
        ("/code <run_id>", "Show generated Python"),
        ("/pine <run_id>", "Show exported Pine Script"),
        ("/trace <run_id>", "Replay tool calls and answer events"),
        ("/continue <run_id> <prompt>", "Refine an existing run"),
        ("/swarm", "List multi-agent team presets"),
        ("/swarm run <preset> {vars}", "Run a team preset"),
        ("/swarm inspect <preset>", "Inspect preset DAG and validation"),
        ("/swarm list", "List team run history"),
        ("/swarm show <run_id>", "Show a team run"),
        ("/swarm cancel <run_id>", "Cancel a team run"),
        ("/sessions", "List chat sessions"),
        ("/settings", "Show provider, model, timeout, and credentials"),
        ("/clear", "Clear the terminal"),
        ("/quit", "Exit"),
        ("", ""),
        ("[dim]Natural language[/dim]", ""),
        ('"analyze journal.csv"', "Parse a broker export and diagnose trading behavior"),
        ('"train my shadow"', "Extract a strategy, backtest it, and create a report"),
    ]
    for cmd, desc in cmds:
        table.add_row(cmd, desc)

    console.print(table)


def _show_settings() -> None:
    """Show current runtime settings."""
    _ensure_cli_env()
    term_width = _terminal_width()
    compact = term_width < 104
    value_limit = max(18, min(56, term_width - 28))
    provider = os.getenv("LANGCHAIN_PROVIDER", "(not set)")
    model = os.getenv("LANGCHAIN_MODEL_NAME", "(not set)")
    provider_key_env = _provider_key_env(provider)
    provider_base_env = _provider_base_env(provider)
    provider_key = os.getenv(provider_key_env or "")
    provider_base_url = os.getenv(provider_base_env or "") or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "(not set)"

    provider_table = Table.grid(expand=True)
    provider_table.add_column(width=12, style="dim")
    provider_table.add_column(ratio=1)
    provider_table.add_row("Provider", f"[bold]{provider}[/bold]")
    provider_table.add_row("Model", _clip_inline(model, value_limit))
    provider_table.add_row("Base URL", _clip_inline(provider_base_url, value_limit))

    runtime_table = Table.grid(expand=True)
    runtime_table.add_column(width=13, style="dim")
    runtime_table.add_column(ratio=1)
    runtime_table.add_row("Temperature", os.getenv("LANGCHAIN_TEMPERATURE", "0.0"))
    runtime_table.add_row("Timeout", os.getenv("TIMEOUT_SECONDS", "2400") + "s")
    runtime_table.add_row("Retries", os.getenv("MAX_RETRIES", "(not set)"))

    credential_table = Table.grid(expand=True)
    credential_table.add_column(width=21, style="dim")
    credential_table.add_column(ratio=1)

    if provider in {"ollama", "openai-codex"}:
        credential_table.add_row("Provider key", "[green]not required[/green]")
        credential_ready = True
    elif provider_key_env:
        credential_table.add_row(provider_key_env, "***" if provider_key else "(not set)")
        credential_ready = bool(provider_key)
    else:
        credential_table.add_row("Provider key", "(unknown provider)")
        credential_ready = False
    credential_table.add_row("TUSHARE_TOKEN", "***" if os.getenv("TUSHARE_TOKEN") else "(optional)")

    panels = [
        Panel(provider_table, title=f"Provider {_state_badge(provider if provider != '(not set)' else None)}", border_style="cyan", padding=(0, 1)),
        Panel(runtime_table, title="Runtime", border_style="dim", padding=(0, 1)),
        Panel(credential_table, title=f"Credentials {_state_badge('ok' if credential_ready else None)}", border_style="green" if credential_ready else "yellow", padding=(0, 1)),
    ]
    if compact:
        for panel in panels:
            console.print(panel)
    else:
        console.print(Columns(panels, expand=True, equal=True))
    console.print("[dim]Edit configuration in agent/.env, or run vibe-trading init.[/dim]")


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
        console.print(f"[red]Unknown command: {cmd}[/red] - type [cyan]/help[/cyan] for available commands")


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
    elif sub == "inspect":
        if sub_arg:
            cmd_swarm_inspect(sub_arg)
        else:
            console.print("[red]Usage: /swarm inspect <preset>[/red]")
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
    stats = _SessionStats(session_start=time.monotonic())
    prompt_session = _create_prompt_session(stats)

    while True:
        if prompt_session is None:
            _print_status_bar(stats)
        try:
            user_input = _read_input(prompt_session).strip()
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
            dashboard = _RunDashboard(user_input, max_iter)
            with Live(dashboard.render(), console=console, refresh_per_second=6, transient=True) as live:
                dashboard.live = live
                result = _run_agent(user_input, history=history[-6:], max_iter=max_iter, dashboard=dashboard)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted[/yellow]")
            continue

        stats.last_elapsed = time.perf_counter() - start
        stats.tool_count += dashboard.iterations
        _print_result(result, stats.last_elapsed)
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
        run = runtime.start_run(
            preset,
            user_vars,
            live_callback=dashboard.handle_event,
            include_shell_tools=True,
        )
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

    table = Table(title="Recent Runs", show_lines=False, border_style="dim", box=box.SIMPLE_HEAVY)
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Status", width=10)
    table.add_column("Return", width=10)
    table.add_column("Sharpe", width=8)
    table.add_column("Prompt", max_width=58)

    for d in dirs:
        st = _read_json(d / "state.json").get("status", "?")
        m = _read_metrics(d / "artifacts" / "metrics.csv")
        c = _status_style(st)
        prompt = (_read_json(d / "req.json").get("prompt") or "").replace("\n", " ")
        if len(prompt) > 58:
            prompt = prompt[:55] + "..."
        table.add_row(
            d.name,
            f"[{c}]{st.upper()}[/{c}]",
            m.get("total_return", ""),
            m.get("sharpe", ""),
            prompt,
        )

    console.print(table)
    console.print("[dim]Use /show <run_id>, /code <run_id>, or /continue <run_id> <prompt>.[/dim]")


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
    c = _status_style(st)
    lines = [f"[bold]Status:[/bold] [{c}]{st.upper()}[/{c}]"]
    if req.get("prompt"):
        lines.append(f"[bold]Prompt:[/bold] {req['prompt'][:500]}{'...' if len(req['prompt']) > 500 else ''}")
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
    console.print("[dim]Copy and paste into TradingView Pine Editor, then Add to Chart[/dim]")


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


def cmd_swarm_inspect(preset: str) -> int:
    """Inspect a swarm preset without starting workers."""
    from src.swarm.presets import inspect_preset

    try:
        report = inspect_preset(preset)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return EXIT_USAGE_ERROR
    except Exception as exc:
        console.print(f"[red]Failed to inspect preset:[/red] {exc}")
        return EXIT_RUN_FAILED

    status = "OK" if report["valid"] else "INVALID"
    status_color = "green" if report["valid"] else "red"
    lines = [
        f"[bold]Preset:[/bold] {report['name']}",
        f"[bold]Title:[/bold] {report.get('title') or '-'}",
        f"[bold]Status:[/bold] [{status_color}]{status}[/{status_color}]",
        f"[bold]Agents:[/bold] {len(report['agents'])}",
        f"[bold]Tasks:[/bold] {len(report['tasks'])}",
        f"[bold]Variables:[/bold] {', '.join(report['variables']) or '-'}",
    ]
    if report.get("description"):
        lines.append(f"[bold]Description:[/bold] {report['description']}")
    console.print(Panel("\n".join(lines), border_style=status_color, title="Swarm Preset Inspect"))

    agent_table = Table(title="Agents", show_lines=False)
    agent_table.add_column("ID", style="cyan", no_wrap=True)
    agent_table.add_column("Role")
    agent_table.add_column("Tools", max_width=40)
    for agent in report["agents"]:
        agent_table.add_row(
            agent["id"],
            agent.get("role", ""),
            ", ".join(agent.get("tools", [])),
        )
    console.print(agent_table)

    dag_table = Table(title="DAG Execution Plan", show_lines=False)
    dag_table.add_column("Layer", justify="right", width=6)
    dag_table.add_column("Task", style="cyan")
    dag_table.add_column("Agent")
    dag_table.add_column("Depends On")
    task_details = {task["id"]: task for task in report["tasks"]}
    for idx, layer in enumerate(report["layers"], start=1):
        for item in layer:
            task = task_details[item["task_id"]]
            dag_table.add_row(
                str(idx),
                item["task_id"],
                item["agent_id"],
                ", ".join(task.get("depends_on", [])) or "-",
            )
    console.print(dag_table)

    validation_table = Table(title="Validation", show_lines=False)
    validation_table.add_column("Level", width=8)
    validation_table.add_column("Message")
    if report["errors"]:
        for error in report["errors"]:
            validation_table.add_row("[red]ERROR[/red]", error)
    if report["warnings"]:
        for warning in report["warnings"]:
            validation_table.add_row("[yellow]WARN[/yellow]", warning)
    if not report["errors"] and not report["warnings"]:
        validation_table.add_row("[green]OK[/green]", "No issues found")
    console.print(validation_table)

    return EXIT_SUCCESS if report["valid"] else EXIT_RUN_FAILED


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

    stats = _SessionStats(session_start=time.monotonic())
    prompt_session = _create_prompt_session(stats)

    while True:
        if prompt_session is None:
            _print_status_bar(stats)
        try:
            prompt = _read_input(prompt_session).strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not prompt or prompt.lower() in ("q", "quit", "exit"):
            break

        run_start = time.perf_counter()
        _run_state = {"label": "running"}
        _stop_timer = threading.Event()

        def _session_event_timer(status_ref: Any) -> None:
            while not _stop_timer.is_set():
                elapsed = time.perf_counter() - run_start
                label = _run_state["label"]
                try:
                    status_ref.update(f"[bold cyan]\u23f3 {label}... {elapsed:.1f}s[/bold cyan]")
                except Exception:
                    pass
                _stop_timer.wait(1.0)

        with console.status("[bold cyan]\u23f3 Running...[/bold cyan]") as spinner:
            _timer = threading.Thread(target=_session_event_timer, args=(spinner,), daemon=True)
            _timer.start()
            try:
                result = _run_agent(prompt, history=history[-6:], max_iter=max_iter)
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted[/yellow]")
                continue
            finally:
                _stop_timer.set()
                _timer.join(timeout=1)

        stats.last_elapsed = time.perf_counter() - run_start
        _print_result(result, stats.last_elapsed)
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


def cmd_provider_login(provider: str) -> int:
    """Authenticate OAuth-backed LLM providers."""
    normalized = provider.strip().lower().replace("_", "-")
    if normalized != "openai-codex":
        console.print("[red]Unknown OAuth provider.[/red] Supported: openai-codex")
        return EXIT_USAGE_ERROR
    try:
        from src.providers.openai_codex import login_openai_codex

        console.print("[cyan]Starting OpenAI Codex OAuth login...[/cyan]\n")
        token = login_openai_codex(
            print_fn=lambda text: console.print(text),
            prompt_fn=lambda text: Prompt.ask(text),
        )
        account = getattr(token, "account_id", None) or "ChatGPT"
        console.print(f"[green]Authenticated with OpenAI Codex[/green]  [dim]{account}[/dim]")
        return EXIT_SUCCESS
    except Exception as exc:
        console.print(f"[red]Authentication error:[/red] {exc}")
        return EXIT_RUN_FAILED


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser with subcommands and compatibility flags."""
    parser = argparse.ArgumentParser(description="Vibe-Trading CLI")
    parser.add_argument("--version", action="version", version=f"vibe-trading {_VERSION}")
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
    parser.add_argument("--swarm-inspect", metavar="PRESET", help="Inspect a swarm preset without running it")
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

    provider_parser = subparsers.add_parser("provider", help="Manage OAuth providers")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_command")
    login_parser = provider_subparsers.add_parser("login", help="Authenticate with an OAuth provider")
    login_parser.add_argument("provider", help="OAuth provider name, e.g. openai-codex")

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
    {
        "label": "OpenAI Codex (ChatGPT OAuth)",
        "provider": "openai-codex",
        "key_env": None,
        "base_env": "OPENAI_CODEX_BASE_URL",
        "base_url": "https://chatgpt.com/backend-api/codex/responses",
        "model": "openai-codex/gpt-5.3-codex",
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
        "OPENAI_CODEX_BASE_URL",
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
    console.print(Panel("[bold cyan]Vibe-Trading setup[/bold cyan]\n[dim]Configure the default LLM provider and data tokens.[/dim]", border_style="cyan"))

    if _INIT_ENV_PATH.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {_INIT_ENV_PATH}")
        if not Confirm.ask("Overwrite it?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return 0

    provider_table = Table(title="LLM Providers", box=box.SIMPLE_HEAVY, show_lines=False, border_style="dim")
    provider_table.add_column("#", justify="right", style="dim", width=3)
    provider_table.add_column("Provider", style="cyan")
    provider_table.add_column("Default model", style="dim")
    provider_table.add_column("Credential", style="dim")
    for idx, option in enumerate(_PROVIDER_CHOICES, start=1):
        credential = "OAuth" if option["provider"] == "openai-codex" else "none" if option["key_env"] is None else str(option["key_env"])
        provider_table.add_row(str(idx), str(option["label"]), str(option["model"]), credential)
    console.print(provider_table)

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
    elif provider == "openai-codex":
        console.print("[dim]OpenAI Codex uses ChatGPT OAuth, not an API key.[/dim]")
        console.print("[dim]After setup, run: vibe-trading provider login openai-codex[/dim]")
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

    next_steps = Table.grid(expand=True)
    next_steps.add_column(width=10, style="dim")
    next_steps.add_column(ratio=1)
    next_steps.add_row("Config", f"[cyan]{_INIT_ENV_PATH}[/cyan]")
    next_steps.add_row("Run", "[bold]vibe-trading[/bold]")
    if provider == "openai-codex":
        next_steps.add_row("OAuth", "[bold]vibe-trading provider login openai-codex[/bold]")
    console.print(Panel(next_steps, title="Setup complete", border_style="green", padding=(0, 1)))
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
    if args.command == "provider":
        if args.provider_command == "login":
            return cmd_provider_login(args.provider)
        console.print("[red]provider requires a subcommand.[/red] Try: vibe-trading provider login openai-codex")
        return EXIT_USAGE_ERROR
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
        return _coerce_exit_code(cmd_show(args.show))
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
    if args.swarm_inspect:
        return _coerce_exit_code(cmd_swarm_inspect(args.swarm_inspect))
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
        return _coerce_exit_code(cmd_continue(args.cont[0], args.cont[1], args.max_iter, json_mode=args.json, no_rich=args.no_rich))

    # No flags and no subcommand: check for a prompt, otherwise enter interactive mode.
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
