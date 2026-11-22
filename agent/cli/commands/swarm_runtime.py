"""CLI swarm runtime commands and their helpers."""
from __future__ import annotations

from cli.commands import common

def _truncate_swarm_vars_preview(value: str) -> str:
    """Return a compact preview for a CLI JSON token."""
    if len(value) <= common.SWARM_RUN_VARS_PREVIEW_CHARS:
        return value
    return value[: common.SWARM_RUN_VARS_PREVIEW_CHARS - 3] + "..."


def _print_swarm_vars_json_error(vars_json: str, exc: common.json.JSONDecodeError) -> None:
    """Print actionable JSON diagnostics for ``--swarm-run`` vars."""
    preview = common.rich_escape(_truncate_swarm_vars_preview(vars_json))
    common.console.print(
        "[red]Invalid JSON for --swarm-run VARS.[/red]\n"
        f"Offending string: {preview}\n"
        f"JSON parse error: {common.rich_escape(str(exc))}\n"
        f"Correct usage: {common.SWARM_RUN_USAGE}\n"
        "shell quoting is the usual culprit; wrap the JSON in single quotes."
    )


def _parse_swarm_run_args(values: list[str]) -> tuple[str, common.Optional[str]] | None:
    """Validate ``--swarm-run`` values before starting the swarm."""
    if len(values) > 2:
        extras = ", ".join(common.rich_escape(repr(token)) for token in values[2:])
        common.console.print(
            "[red]Invalid --swarm-run arguments:[/red] "
            f"unexpected extra token(s): {extras}\n"
            f"Correct usage: {common.SWARM_RUN_USAGE}"
        )
        return None

    preset = values[0]
    vars_json = values[1] if len(values) > 1 else None
    if vars_json:
        try:
            common.json.loads(vars_json)
        except common.json.JSONDecodeError as exc:
            _print_swarm_vars_json_error(vars_json, exc)
            return None
    return preset, vars_json


def _get_agent_style(agent_id: str) -> str:
    """Assign a consistent color to each agent."""
    if agent_id not in common._agent_color_map:
        idx = len(common._agent_color_map) % len(common._AGENT_STYLES)
        common._agent_color_map[agent_id] = common._AGENT_STYLES[idx]
    return common._agent_color_map[agent_id]


class _SwarmDashboard:
    """Track swarm state and render a Rich Live panel."""

    def __init__(self, preset: str, run_id: str) -> None:
        self.preset = preset
        self.run_id = run_id
        self.start_time = common.time.monotonic()
        self.current_layer = 0
        self.total_layers = 0
        self.agents: common.Dict[str, common.Dict[str, common.Any]] = {}
        self.agent_order: common.List[str] = []
        self.completed_summaries: common.List[tuple[str, str]] = []
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
            agent["started_at"] = common.time.monotonic()
        elif etype == "item.started" and data.get("kind") == "tool.started":
            agent["tool"] = data["item"].get("name", "?")
            agent["iters"] += 1
        elif etype == "item.completed" and data.get("kind") in {"tool.completed", "tool.failed"}:
            agent["elapsed"] = (common.time.monotonic() - agent["started_at"]) if agent["started_at"] else 0
            tool_name = agent["tool"]
            status_char = "\u2713" if data["item"].get("status", "ok") == "ok" else "\u2717"
            agent["tool"] = f"{tool_name} {status_char}"
        elif etype == "task_completed":
            agent["status"] = "done"
            agent["elapsed"] = (common.time.monotonic() - agent["started_at"]) if agent["started_at"] else 0
            agent["iters"] = data.get("iterations", agent["iters"])
            summary = data.get("summary", "")
            if summary:
                self.completed_summaries.append((agent["name"], summary))
        elif etype == "task_resumed":
            agent["status"] = "resumed"
            agent["tool"] = "kept"
        elif etype == "task_failed":
            agent["status"] = "failed"
            agent["elapsed"] = (common.time.monotonic() - agent["started_at"]) if agent["started_at"] else 0
            error = data.get("error", "")[:80]
            self.completed_summaries.append((agent["name"], f"[red]FAILED: {error}[/red]"))
        elif etype == "task_cancelled":
            agent["status"] = "cancelled"
            agent["elapsed"] = (common.time.monotonic() - agent["started_at"]) if agent["started_at"] else 0
            agent["iters"] = data.get("iterations", agent["iters"])
            self.completed_summaries.append((agent["name"], "[yellow]CANCELLED[/yellow]"))
        elif etype == "task_blocked":
            agent["status"] = "blocked"
            blocked_by = ", ".join(data.get("blocked_by", []))
            self.completed_summaries.append(
                (agent["name"], f"[yellow]BLOCKED by: {blocked_by}[/yellow]")
            )
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

    def build_table(self) -> common.Table:
        """Build the Rich Table for the live panel."""
        elapsed_total = common.time.monotonic() - self.start_time
        mins, secs = divmod(int(elapsed_total), 60)

        if self.finished:
            color = "green" if self.final_status == "completed" else "red"
            title_status = f"[{color}]{self.final_status.upper()}[/{color}]"
        else:
            title_status = "[cyan]RUNNING[/cyan]"

        title = f"{self.preset}  {title_status}  {mins}:{secs:02d}"

        table = common.Table(
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
                elapsed = common.time.monotonic() - agent["started_at"] if agent["started_at"] else 0
            elif status == "done":
                status_str = "[green][\u2713 done  ][/green]"
                elapsed = agent["elapsed"]
            elif status == "resumed":
                status_str = "[green][\u2713 kept  ][/green]"
                elapsed = agent["elapsed"]
            elif status == "failed":
                status_str = "[red][\u2717 failed][/red]"
                elapsed = agent["elapsed"]
            elif status == "retry":
                status_str = "[yellow][\u21bb retry ][/yellow]"
                elapsed = common.time.monotonic() - agent["started_at"] if agent["started_at"] else 0
            elif status == "cancelled":
                status_str = "[yellow][\u2298 cancel][/yellow]"
                elapsed = agent["elapsed"]
            else:
                status_str = "[dim][\u25cb waiting][/dim]"
                elapsed = 0

            time_str = f"{elapsed:.1f}s" if elapsed > 0 else "\u2014"
            iter_str = str(agent["iters"]) if agent["iters"] > 0 else "\u2014"
            last_text = agent.get("last_text", "")

            table.add_row(styled_name, status_str, agent["tool"], time_str, iter_str, last_text)

        # Progress bar row
        done_count = sum(1 for a in self.agents.values() if a["status"] in ("done", "resumed", "failed", "cancelled"))
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


def _watch_swarm_run(store, runtime, run, dashboard: _SwarmDashboard) -> common.Optional[int]:
    """Keep the CLI alive while a swarm run streams to its dashboard."""
    from rich.live import Live
    from src.swarm.models import RunStatus

    dashboard.run_id = run.id

    with Live(dashboard.build_table(), console=common.console, refresh_per_second=4, transient=False) as live:
        try:
            while True:
                common.time.sleep(0.25)
                live.update(dashboard.build_table())
                current = store.load_run(run.id)
                if current is None:
                    common.console.print("[red]Run record lost[/red]")
                    return
                if current.status in (RunStatus.completed, RunStatus.failed, RunStatus.cancelled):
                    dashboard.finished = True
                    dashboard.final_status = current.status.value
                    live.update(dashboard.build_table())
                    break
        except KeyboardInterrupt:
            common.console.print("\n[yellow]Cancelling...[/yellow]")
            runtime.cancel_run(run.id)
            common.time.sleep(1)
            current = store.load_run(run.id)

    if current is None:
        return

    for agent_name, summary in dashboard.completed_summaries:
        style = _get_agent_style(agent_name)
        common.console.print(f"\n[{style}]\u2500\u2500 {agent_name} \u2500\u2500[/{style}]")
        lines = summary.strip().split("\n")
        preview = "\n".join(lines[:8])
        if len(lines) > 8:
            preview += "\n[dim]...[/dim]"
        common.console.print(preview)

    status_color = {
        RunStatus.completed: "green",
        RunStatus.failed: "red",
        RunStatus.cancelled: "yellow",
    }.get(current.status, "dim")

    elapsed_total = common.time.monotonic() - dashboard.start_time
    mins, secs = divmod(int(elapsed_total), 60)

    tokens_in = current.total_input_tokens
    tokens_out = current.total_output_tokens
    token_str = ""
    if tokens_in or tokens_out:
        token_str = f"\nTokens: ~{tokens_in + tokens_out:,} (in: {tokens_in:,} out: {tokens_out:,})"

    if current.final_report:
        label = "Partial results" if current.report_is_partial else "Final Report"
        common.console.print(f"\n[bold]── {label} ──[/bold]")
        common.console.print(current.final_report, markup=False)

    common.console.print(f"\n[{status_color}]{current.status.value.upper()}[/{status_color}]  Time: {mins}m {secs}s{token_str}")


def cmd_swarm_run_live(preset: str, vars_json: common.Optional[str] = None) -> common.Optional[int]:
    """Run a swarm preset with Rich Live dashboard."""
    from src.config import load_swarm_agent_config
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    user_vars: common.Dict[str, str] = {}
    if vars_json:
        try:
            user_vars = common.json.loads(vars_json)
        except common.json.JSONDecodeError as exc:
            _print_swarm_vars_json_error(vars_json, exc)
            return common.EXIT_USAGE_ERROR

    store = SwarmStore(base_dir=common.SWARM_DIR)
    agent_config = load_swarm_agent_config()
    runtime = SwarmRuntime(store=store, agent_config=agent_config)
    common._agent_color_map.clear()

    common.console.print(f"\n[dim]Starting swarm:[/dim] [cyan]{preset}[/cyan]")
    if user_vars:
        common.console.print(f"[dim]Variables:[/dim] {common.json.dumps(user_vars, ensure_ascii=False)}")

    dashboard = _SwarmDashboard(preset, "")

    try:
        run = runtime.start_run(
            preset,
            user_vars,
            live_callback=dashboard.handle_event,
            include_shell_tools=True,
        )
    except FileNotFoundError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return
    except ValueError as exc:
        common.console.print(f"[red]DAG validation failed: {exc}[/red]")
        return

    return _watch_swarm_run(store, runtime, run, dashboard)


def cmd_swarm_retry_live(run_id: str, resume: bool = False) -> common.Optional[int]:
    """Retry a prior swarm run, optionally keeping completed tasks."""
    from src.config import load_swarm_agent_config
    from src.swarm.models import RunStatus
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    store = SwarmStore(base_dir=common.SWARM_DIR)
    try:
        loaded = store.load_run(run_id)
    except ValueError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    if loaded is None:
        common.console.print(f"[red]Run {run_id} not found[/red]")
        return common.EXIT_USAGE_ERROR

    reconciled = store.reconcile_run(loaded, write=True)
    if reconciled.status == RunStatus.running:
        common.console.print("[red]Cannot retry a running run. Cancel or reap it first.[/red]")
        return common.EXIT_USAGE_ERROR
    if resume and reconciled.status not in (RunStatus.failed, RunStatus.cancelled):
        common.console.print(
            f"[red]Cannot resume a run in status '{reconciled.status.value}'; "
            "resume only applies to failed or cancelled runs.[/red]"
        )
        return common.EXIT_USAGE_ERROR

    runtime = SwarmRuntime(store=store, agent_config=load_swarm_agent_config())
    common._agent_color_map.clear()
    action = "Resuming swarm" if resume else "Retrying swarm"
    common.console.print(f"\n[dim]{action}:[/dim] [cyan]{reconciled.preset_name}[/cyan]")
    common.console.print(f"[dim]Source run:[/dim] {run_id}")

    dashboard = _SwarmDashboard(reconciled.preset_name, "")
    try:
        run = runtime.start_run(
            reconciled.preset_name,
            reconciled.user_vars or {},
            live_callback=dashboard.handle_event,
            include_shell_tools=True,
            resume_from=reconciled if resume else None,
        )
    except FileNotFoundError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    except ValueError as exc:
        common.console.print(f"[red]DAG validation failed: {exc}[/red]")
        return common.EXIT_USAGE_ERROR

    return _watch_swarm_run(store, runtime, run, dashboard)


def cmd_swarm_presets() -> None:
    """List available swarm presets."""
    from src.swarm.presets import list_presets

    presets = list_presets()
    if not presets:
        common.console.print("[dim]No presets available[/dim]")
        return

    table = common.Table(title="Swarm Presets", show_lines=False)
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

    common.console.print(table)


def cmd_swarm_inspect(preset: str) -> int:
    """Inspect a swarm preset without starting workers."""
    from src.swarm.presets import inspect_preset

    try:
        report = inspect_preset(preset)
    except FileNotFoundError as exc:
        common.console.print(f"[red]{exc}[/red]")
        return common.EXIT_USAGE_ERROR
    except Exception as exc:
        common.console.print(f"[red]Failed to inspect preset:[/red] {exc}")
        return common.EXIT_RUN_FAILED

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
    common.console.print(common.Panel("\n".join(lines), border_style=status_color, title="Swarm Preset Inspect"))

    agent_table = common.Table(title="Agents", show_lines=False)
    agent_table.add_column("ID", style="cyan", no_wrap=True)
    agent_table.add_column("Role")
    agent_table.add_column("Tools", max_width=40)
    for agent in report["agents"]:
        agent_table.add_row(
            agent["id"],
            agent.get("role", ""),
            ", ".join(agent.get("tools", [])),
        )
    common.console.print(agent_table)

    dag_table = common.Table(title="DAG Execution Plan", show_lines=False)
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
    common.console.print(dag_table)

    validation_table = common.Table(title="Validation", show_lines=False)
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
    common.console.print(validation_table)

    return common.EXIT_SUCCESS if report["valid"] else common.EXIT_RUN_FAILED


def cmd_swarm_list() -> None:
    """List swarm run history."""
    from src.swarm.store import SwarmStore

    store = SwarmStore(base_dir=common.SWARM_DIR)
    runs = store.list_runs()

    if not runs:
        common.console.print("[dim]No swarm runs yet[/dim]")
        return

    table = common.Table(title="Swarm Runs", show_lines=False)
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

    common.console.print(table)


def cmd_swarm_show(run_id: str) -> None:
    """Show swarm run details."""
    from src.swarm.store import SwarmStore
    from src.swarm.models import TaskStatus

    store = SwarmStore(base_dir=common.SWARM_DIR)
    run = store.load_run(run_id)

    if run is None:
        common.console.print(f"[red]Swarm run {run_id} not found[/red]")
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
        lines.append(f"[bold]Variables:[/bold] {common.json.dumps(run.user_vars, ensure_ascii=False)}")

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

    common.console.print(common.Panel("\n".join(lines), border_style=status_color, title=run_id))


def cmd_swarm_cancel(run_id: str) -> None:
    """Cancel a swarm run."""
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    store = SwarmStore(base_dir=common.SWARM_DIR)
    runtime = SwarmRuntime(store=store)

    if runtime.cancel_run(run_id):
        common.console.print(f"[yellow]Cancel signal sent: {run_id}[/yellow]")
    else:
        common.console.print(f"[red]Run {run_id} not found or already finished[/red]")
