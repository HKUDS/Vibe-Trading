"""CLI inspection commands and their helpers."""
from __future__ import annotations

from cli.commands import common

def _read_json(path: common.Path) -> dict:
    """Safely read JSON."""
    if not path.exists():
        return {}
    try:
        return common.json.loads(path.read_text(encoding="utf-8"))
    except (common.json.JSONDecodeError, OSError):
        return {}


def _read_metrics(path: common.Path) -> dict:
    """Read metrics from metrics.csv, return formatted string dict."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            rows = list(common.csv.DictReader(f))
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


def _read_metric_values(path: common.Path) -> dict[str, float]:
    """Read metrics.csv as raw floats, for callers that must do arithmetic."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            row = next(common.csv.DictReader(handle), None) or {}
    except (OSError, common.csv.Error):
        return {}
    values: dict[str, float] = {}
    for key, value in row.items():
        try:
            values[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return values


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


def _state_badge(value: str | None, *, ready_label: str = "READY") -> str:
    """Render a compact terminal status badge."""
    return f"[black on green] {ready_label} [/]" if value else "[black on yellow] MISSING [/]"


def _terminal_width() -> int:
    """Return the active console width with a conservative fallback."""
    try:
        return max(40, int(common.console.size.width))
    except Exception:
        return 80


def _clip_inline(text: str, limit: int) -> str:
    """Collapse whitespace and clip text for single-line terminal cells."""
    clipped = " ".join(str(text or "").split())
    if len(clipped) <= limit:
        return clipped
    return clipped[: max(0, limit - 3)] + "..."


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


def cmd_list(limit: int = 20) -> None:
    """List recent runs with their status and available metrics.

    Args:
        limit: Maximum number of recent run directories to show.
    """
    if not common.RUNS_DIR.exists():
        common.console.print("[dim]No runs yet[/dim]")
        return
    dirs = sorted([d for d in common.RUNS_DIR.iterdir() if d.is_dir()], key=lambda d: d.name, reverse=True)[:limit]
    if not dirs:
        common.console.print("[dim]No runs yet[/dim]")
        return

    table = common.Table(title="Recent Runs", show_lines=False, border_style="dim", box=common.box.SIMPLE_HEAVY)
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

    common.console.print(table)
    common.console.print("[dim]Use /show <run_id>, /code <run_id>, or /continue <run_id> <prompt>.[/dim]")


def cmd_show(run_id: str) -> None:
    """Show a run's status, prompt, metrics, and available answer preview.

    Args:
        run_id: ID of the run directory under the runs root.
    """
    run_dir = common.RUNS_DIR / run_id
    if not run_dir.exists():
        common.console.print(f"[red]{run_id} not found[/red]")
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

    entries = _thread_entries_for_run(run_id)
    answers = [e["content"] for e in entries if e.get("type") == "answer" and e.get("content")]
    if answers:
        summary = answers[-1][:200]
        lines.append(f"\n[bold]Answer:[/bold] {summary}{'...' if len(answers[-1]) > 200 else ''}")

    if state.get("reason"):
        lines.append(f"\n[bold]Reason:[/bold] {state['reason']}")

    common.console.print(common.Panel("\n".join(lines), border_style=c, title=run_id))
    common.console.print(f"[dim]{run_dir}[/dim]")


def cmd_code(run_id: str) -> None:
    """Show the run's generated signal engine code when present.

    Args:
        run_id: ID of the run directory containing the generated code.
    """
    code_dir = common.RUNS_DIR / run_id / "code"
    if not code_dir.exists():
        common.console.print(f"[red]{run_id}/code not found[/red]")
        return
    for name in ("signal_engine.py",):
        path = code_dir / name
        if path.exists():
            code = path.read_text(encoding="utf-8")
            common.console.print(common.Syntax(code, "python", theme="monokai", line_numbers=True), width=120)
            common.console.print()


def cmd_pine(run_id: str) -> None:
    """Show Pine Script for a run.

    Args:
        run_id: ID of the run whose strategy.pine artifact should be printed.
    """
    pine_path = common.RUNS_DIR / run_id / "artifacts" / "strategy.pine"
    if not pine_path.exists():
        common.console.print(f"[red]{run_id}/artifacts/strategy.pine not found[/red]")
        common.console.print("[dim]Ask the agent: \"export this strategy to Pine Script\"[/dim]")
        return
    code = pine_path.read_text(encoding="utf-8")
    common.console.print(common.Syntax(code, "javascript", theme="monokai", line_numbers=True), width=120)
    common.console.print()
    common.console.print("[dim]Copy and paste into TradingView Pine Editor, then Add to Chart[/dim]")


def cmd_skills() -> None:
    """List available skills."""
    from src.product.resources.skills import SkillsLoader
    loader = SkillsLoader()

    table = common.Table(title="Skills", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for s in loader.skills:
        table.add_row(s.name, s.description)

    common.console.print(table)


def cmd_trace(run_id: str) -> None:
    """Replay a run's recorded execution events in the terminal.

    Args:
        run_id: ID of the run whose thread should be displayed.
    """
    entries = _thread_entries_for_run(run_id)
    if not entries:
        common.console.print(f"[red]{run_id}/thread.jsonl is empty or missing[/red]")
        return

    common.console.print(common.Panel(f"[bold]Thread replay: {run_id}[/bold]  ({len(entries)} entries)", border_style="cyan"))

    for entry in entries:
        etype = entry.get("type", "?")
        ts = entry.get("ts", 0)
        ts_str = common.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
        it = entry.get("iter", "")
        iter_tag = f"[dim]#{it}[/dim] " if it else ""

        if etype == "start":
            common.console.print(f"\n[bold cyan]{ts_str}[/bold cyan] {iter_tag}[bold]START[/bold]  {entry.get('prompt', '')[:120]}")
        elif etype == "thinking":
            content = entry.get("content", "")
            common.console.print(f"[dim]{ts_str}[/dim] {iter_tag}[dim italic]{content[:200]}[/dim italic]")
        elif etype == "tool_call":
            tool = entry.get("tool", "")
            args = entry.get("args", {})
            args_str = ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items()) if args else ""
            common.console.print(f"[dim]{ts_str}[/dim] {iter_tag}[cyan]\u25b6 {tool}[/cyan]({args_str})")
        elif etype == "tool_result":
            tool = entry.get("tool", "")
            status = entry.get("status", "ok")
            elapsed = entry.get("elapsed_ms", 0)
            ok = status == "ok"
            mark = "\u2713" if ok else "\u2717"
            color = "green" if ok else "red"
            preview = (entry.get("preview") or entry.get("result_preview") or entry.get("result") or "")[:80]
            size_hint = ""
            if entry.get("result_path"):
                size_hint = f" [{int(entry.get('result_size') or 0) // 1024}K offloaded]"
            common.console.print(f"[dim]{ts_str}[/dim] {iter_tag}[{color}]{mark} {tool}[/{color}] [dim]{elapsed}ms[/dim]  {preview}{size_hint}")
        elif etype == "tool_skipped":
            common.console.print(f"[dim]{ts_str}[/dim] {iter_tag}[yellow]\u2298 {entry.get('tool', '')} (skipped)[/yellow]")
        elif etype == "message":
            role = entry.get("role", "?")
            content = entry.get("content") or entry.get("content_preview") or ""
            role_color = "cyan" if role == "user" else "green"
            common.console.print(f"\n[dim]{ts_str}[/dim] {iter_tag}[bold {role_color}]{role.upper()}[/bold {role_color}] {content[:120]}")
        elif etype == "answer":
            content = entry.get("content", "")
            common.console.print(f"\n[dim]{ts_str}[/dim] {iter_tag}[bold green]ANSWER[/bold green]\n{content}")
        elif etype == "end":
            status = entry.get("status", "?")
            iters = entry.get("iterations", "?")
            color = "green" if status == "success" else "red"
            common.console.print(f"\n[bold {color}]{ts_str} END[/bold {color}]  status={status}  iterations={iters}")

    common.console.print()


def _thread_entries_for_run(run_id: str) -> list[dict[str, common.Any]]:
    """Project thread items into the CLI's diagnostic display vocabulary."""
    from src.session.thread import ThreadLog

    candidates = [common.SESSIONS_DIR / run_id / "thread.jsonl", common.RUNS_DIR / run_id / "thread.jsonl"]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return []
    from src.session.replay import diagnostic_records

    return diagnostic_records(ThreadLog(path).read())
