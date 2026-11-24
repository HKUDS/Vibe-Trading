"""CLI setup memory commands and their helpers."""
from __future__ import annotations

from cli.commands import common

def _validate_api_key(api_key: str, expected_prefix: str | None) -> bool:
    """Basic API-key format validation used during interactive setup."""
    if expected_prefix is None:
        return True
    return api_key.startswith(expected_prefix)


def cmd_memory_list(memory_type: common.Optional[str] = None, *, memory_dir: common.Optional[common.Path] = None) -> int:
    """List persisted memory entries.

    Args:
        memory_type: Optional memory type filter.
        memory_dir: Optional override for the persistent memory directory.

    Returns:
        Success after listing matching entries or reporting an empty result.
    """
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    entries = pm.list_entries()
    if memory_type:
        entries = [e for e in entries if e.memory_type == memory_type]

    if not entries:
        scope = f" type={memory_type}" if memory_type else ""
        common.console.print(f"[dim]No memory entries found{scope}.[/dim]")
        return common.EXIT_SUCCESS

    entries.sort(key=lambda e: -e.modified_at)
    table = common.Table(title="Persistent Memory", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Title", style="bold")
    table.add_column("Type")
    table.add_column("Description", overflow="fold")
    table.add_column("Modified", style="dim")

    for e in entries:
        style = common._MEMORY_TYPE_STYLES.get(e.memory_type, "white")
        modified = common.datetime.fromtimestamp(e.modified_at).strftime("%Y-%m-%d %H:%M")
        table.add_row(
            common.rich_escape(e.title),
            f"[{style}]{e.memory_type}[/{style}]",
            common.rich_escape(e.description) or "—",
            modified,
        )

    common.console.print(table)
    common.console.print(f"[dim]{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}[/dim]")
    return common.EXIT_SUCCESS


def cmd_memory_show(name: str, *, memory_dir: common.Optional[common.Path] = None) -> int:
    """Show full content of a single memory entry.

    Args:
        name: Entry title or filename stem.
        memory_dir: Optional override for the persistent memory directory.

    Returns:
        Success after printing the entry, or a usage error if it is missing.
    """
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    entry = pm.find(name)
    if entry is None:
        common.console.print(f"[red]Memory not found:[/red] {common.rich_escape(name)}")
        common.console.print("[dim]Run `vibe-trading memory list` to see available titles.[/dim]")
        return common.EXIT_USAGE_ERROR

    style = common._MEMORY_TYPE_STYLES.get(entry.memory_type, "white")
    header = (
        f"[bold]{common.rich_escape(entry.title)}[/bold]\n"
        f"[{style}]{entry.memory_type}[/{style}]  •  [dim]{common.rich_escape(entry.path.name)}[/dim]\n"
        f"[dim]{common.rich_escape(entry.description)}[/dim]"
    )
    common.console.print(common.Panel(header, border_style="cyan"))
    common.console.print(common.rich_escape(entry.body.rstrip()) or "[dim](empty body)[/dim]")
    return common.EXIT_SUCCESS


def cmd_memory_search(query: str, max_results: int = 5, *, memory_dir: common.Optional[common.Path] = None) -> int:
    """Run keyword recall and display the top matches.

    Args:
        query: Search text used for keyword recall.
        max_results: Maximum number of matches to display.
        memory_dir: Optional override for the persistent memory directory.

    Returns:
        Success after printing matches or reporting an empty result.
    """
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    results = pm.find_relevant(query, max_results=max_results)
    if not results:
        common.console.print(f"[dim]No matches for[/dim] [bold]{common.rich_escape(query)}[/bold]")
        return common.EXIT_SUCCESS

    table = common.Table(title=f"Recall: {common.rich_escape(query)}", box=common.box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Rank", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Type")
    table.add_column("Description", overflow="fold")

    for rank, e in enumerate(results, start=1):
        style = common._MEMORY_TYPE_STYLES.get(e.memory_type, "white")
        table.add_row(
            str(rank),
            common.rich_escape(e.title),
            f"[{style}]{e.memory_type}[/{style}]",
            common.rich_escape(e.description) or "—",
        )

    common.console.print(table)
    return common.EXIT_SUCCESS


def cmd_memory_forget(name: str, *, yes: bool = False, memory_dir: common.Optional[common.Path] = None) -> int:
    """Remove a memory entry by name.

    Args:
        name: Title or filename stem of the entry to remove.
        yes: Whether to remove the entry without prompting.
        memory_dir: Optional override for the persistent memory directory.

    Returns:
        Success after removal or a declined confirmation, a usage error for an unknown entry or
        unavailable confirmation input, or failure if removal fails.
    """
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    entry = pm.find(name)
    if entry is None:
        common.console.print(f"[red]Memory not found:[/red] {common.rich_escape(name)}")
        return common.EXIT_USAGE_ERROR

    if not yes:
        style = common._MEMORY_TYPE_STYLES.get(entry.memory_type, "white")
        common.console.print(
            f"About to forget [bold]{common.rich_escape(entry.title)}[/bold] "
            f"([{style}]{entry.memory_type}[/{style}], {common.rich_escape(entry.path.name)})."
        )
        try:
            proceed = common.Confirm.ask("Proceed?", default=False)
        except EOFError:
            common.console.print("[dim]No input available; use --yes for non-interactive deletes.[/dim]")
            return common.EXIT_USAGE_ERROR
        if not proceed:
            common.console.print("[dim]Aborted.[/dim]")
            return common.EXIT_SUCCESS

    if pm.remove_entry(entry):
        common.console.print(f"[green]Forgot[/green] {common.rich_escape(entry.title)}")
        return common.EXIT_SUCCESS
    common.console.print(f"[red]Failed to remove[/red] {common.rich_escape(entry.title)}")
    return common.EXIT_RUN_FAILED


def cmd_init() -> int:
    """Configure the default provider and optional data credentials interactively.

    Returns:
        Zero after saving the settings or declining to overwrite an existing configuration.
    """
    common.console.print(common.Panel("[bold cyan]Vibe-Trading setup[/bold cyan]\n[dim]Configure the default LLM provider and data tokens.[/dim]", border_style="cyan"))

    if common._INIT_ENV_PATH.exists():
        common.console.print(f"[yellow]Config already exists:[/yellow] {common._INIT_ENV_PATH}")
        if not common.Confirm.ask("Overwrite it?", default=False):
            common.console.print("[dim]Aborted.[/dim]")
            return 0

    provider_table = common.Table(title="LLM Providers", box=common.box.SIMPLE_HEAVY, show_lines=False, border_style="dim")
    provider_table.add_column("#", justify="right", style="dim", width=3)
    provider_table.add_column("Provider", style="cyan")
    provider_table.add_column("Default model", style="dim")
    provider_table.add_column("Credential", style="dim")
    for idx, option in enumerate(common._PROVIDER_CHOICES, start=1):
        credential = "OAuth" if option["provider"] == "openai-codex" else "none" if option["key_env"] is None else str(option["key_env"])
        provider_table.add_row(str(idx), str(option["label"]), str(option["model"]), credential)
    common.console.print(provider_table)

    choice = common.IntPrompt.ask(
        "Provider",
        choices=[str(i) for i in range(1, len(common._PROVIDER_CHOICES) + 1)],
        default=1,
        show_choices=False,
    )
    selected = common._PROVIDER_CHOICES[choice - 1]

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
            api_key = common.Prompt.ask(
                f"Enter your {provider.capitalize()} API key",
                default=str(key_placeholder),
                password=True,
                show_default=False,
            ).strip()
            if _validate_api_key(api_key, str(key_prefix) if key_prefix is not None else None):
                env_values[str(key_env)] = api_key
                break
            common.console.print(
                f"[red]That key doesn't look right.[/red] Expected it to start with [bold]{key_prefix}[/bold]."
            )
    elif provider == "openai-codex":
        common.console.print("[dim]OpenAI Codex uses ChatGPT OAuth, not an API key.[/dim]")
        common.console.print("[dim]After setup, run: vibe-trading provider login openai-codex[/dim]")
    else:
        common.console.print("[dim]Ollama does not require an API key.[/dim]")

    env_values[base_env] = common.Prompt.ask(
        "Base URL",
        default=default_base_url,
        show_default=True,
    ).strip()

    env_values["LANGCHAIN_MODEL_NAME"] = common.Prompt.ask(
        "Select default model",
        default=default_model,
        show_default=True,
    ).strip()

    tushare_token = common.Prompt.ask(
        "(Optional) Enter Tushare token for China A-share data",
        default="",
        show_default=False,
    ).strip()
    if tushare_token:
        env_values["TUSHARE_TOKEN"] = tushare_token

    from src.providers.settings import SettingsStore

    SettingsStore(path=common._INIT_ENV_PATH).persist(env_values, replace=True)

    next_steps = common.Table.grid(expand=True)
    next_steps.add_column(width=10, style="dim")
    next_steps.add_column(ratio=1)
    next_steps.add_row("Config", f"[cyan]{common._INIT_ENV_PATH}[/cyan]")
    next_steps.add_row("Run", "[bold]vibe-trading[/bold]")
    if provider == "openai-codex":
        next_steps.add_row("OAuth", "[bold]vibe-trading provider login openai-codex[/bold]")
    common.console.print(common.Panel(next_steps, title="Setup complete", border_style="green", padding=(0, 1)))
    return 0


def _is_windows() -> bool:
    """True when running on a Windows-like platform (win32, including Cygwin/MSYS)."""
    return common.sys.platform == "win32"


def _resolve_node_and_npm() -> tuple[common.Optional[str], common.Optional[str]]:
    """Return ``(node_path, npm_path)`` if both are on PATH, else ``(None, None)``."""
    node = common.shutil.which("node")
    npm = common.shutil.which("npm")
    return node, npm


def _build_frontend_cmd(frontend_dir: common.Path) -> list[list[str]]:
    """Return the ordered list of subprocess invocations needed to build the frontend."""
    is_win = _is_windows()
    if is_win:
        # `npm exec --package=typescript tsc -b` is the safe form on Windows;
        # plain `npx tsc` will fetch the abandoned `tsc@2.0.4` package.
        return [
            ["npm", "install", "--no-audit", "--no-fund"],
            ["npm", "exec", "--package=typescript", "--", "tsc", "-b"],
            ["npm", "exec", "--package=vite", "--", "vite", "build"],
        ]
    return [
        ["npm", "install", "--no-audit", "--no-fund"],
        ["npm", "run", "build"],
    ]


def _run_step(
    description: str,
    cmd: list[str],
    cwd: common.Path,
) -> bool:
    """Run one subprocess step, returning True on success."""
    common.console.print(f"[dim]  {description} …[/dim]")
    try:
        result = common.subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        common.console.print(f"[red]  failed:[/red] {exc}")
        return False
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        # Show the last 20 lines to keep noise manageable.
        tail = "\n".join(err.splitlines()[-20:]) if err else "(no output)"
        common.console.print(f"[red]  {description} failed:[/red]\n{tail}")
        return False
    return True


def cmd_setup(frontend_dir: common.Path) -> int:
    """Install frontend dependencies and build the production bundle.

    Args:
        frontend_dir: Frontend project directory in which to install dependencies and run the build.

    Returns:
        Success after building, a usage error for a missing directory or tools, or failure if a
        setup step fails.
    """
    common.console.print(
        common.Panel(
            f"[bold cyan]Vibe-Trading frontend setup[/bold cyan]\n"
            f"[dim]{frontend_dir}[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )
    )

    if not frontend_dir.exists():
        common.console.print(
            f"[red]Frontend directory not found:[/red] {frontend_dir}\n"
            "[dim]Pass --frontend-dir to point at a different location.[/dim]"
        )
        return common.EXIT_USAGE_ERROR

    node, npm = _resolve_node_and_npm()
    if not node or not npm:
        missing = [name for name, path_ in (("node", node), ("npm", npm)) if not path_]
        common.console.print(
            f"[red]Required tool not on PATH:[/red] {', '.join(missing)}\n"
            "[dim]Install Node.js (>= 18) from https://nodejs.org and retry.[/dim]"
        )
        return common.EXIT_USAGE_ERROR

    # Resolve npm explicitly because Windows subprocess lookup skips PATHEXT.
    npm_path = npm
    if _is_windows():
        steps = [
            [npm_path, *step[1:]] if step and step[0] == "npm" else step
            for step in _build_frontend_cmd(frontend_dir)
        ]
    else:
        steps = _build_frontend_cmd(frontend_dir)
    for step in steps:
        description = " ".join(step[:3])  # e.g. "npm install --no-audit"
        if not _run_step(description, step, frontend_dir):
            return common.EXIT_RUN_FAILED

    common.console.print(
        common.Panel(
            "[green]Frontend built.[/green]\n"
            f"  Artifacts: [cyan]{frontend_dir / 'dist'}[/cyan]\n"
            "[dim]Run [bold]vibe-trading serve[/bold] to serve everything on one port.[/dim]",
            border_style="green",
            padding=(0, 1),
        )
    )
    return common.EXIT_SUCCESS


def cmd_dev(
    backend_port: int = 8899,
    frontend_port: int = 5899,
    frontend_dir: common.Optional[common.Path] = None,
) -> int:
    """Run the API and Vite development servers under one foreground command.

    Args:
        backend_port: Port on which to start the API server.
        frontend_port: Port on which to start Vite.
        frontend_dir: Optional frontend directory, defaulting to the checkout's frontend directory.

    Returns:
        Child exit code if a child exits with an error, a usage error for missing prerequisites,
        failure on a launch error, or success on normal exit.
    """
    frontend_dir = frontend_dir or (common.AGENT_DIR.parent / "frontend")
    if not frontend_dir.exists():
        common.console.print(
            f"[red]Frontend directory not found:[/red] {frontend_dir}\n"
            "[dim]Pass --frontend-dir to point at a different location.[/dim]"
        )
        return common.EXIT_USAGE_ERROR

    # Check for local Vite so missing dependencies lead to setup instructions.
    vite_bin = frontend_dir / "node_modules" / ".bin" / ("vite.cmd" if _is_windows() else "vite")
    if not vite_bin.exists():
        common.console.print(
            common.Panel(
                f"[red]Frontend dependencies not installed.[/red]\n"
                f"  Missing: [dim]{frontend_dir / 'node_modules'}[/dim]\n\n"
                "Run this first:\n"
                "  [cyan]vibe-trading setup[/cyan]\n\n"
                "[dim]Or, to start the dev mode anyway and install on the fly,\n"
                "run [bold]vibe-trading setup[/bold] in another terminal.[/dim]",
                title="vibe-trading dev",
                border_style="red",
                padding=(0, 1),
            )
        )
        return common.EXIT_USAGE_ERROR

    node, npm = _resolve_node_and_npm()
    if not node or not npm:
        missing = [name for name, path_ in (("node", node), ("npm", npm)) if not path_]
        common.console.print(
            f"[red]Required tool not on PATH:[/red] {', '.join(missing)}\n"
            "[dim]Install Node.js (>= 18) from https://nodejs.org and retry.[/dim]"
        )
        return common.EXIT_USAGE_ERROR

    backend_cmd = [common.sys.executable, "-m", "cli", "serve", "--port", str(backend_port)]
    # Resolve npm explicitly so Windows can launch npm.cmd.
    npm_executable = npm if _is_windows() else "npm"
    frontend_cmd = [npm_executable, "run", "dev", "--", "--port", str(frontend_port)]

    common.console.print(
        common.Panel(
            f"[bold cyan]Vibe-Trading dev[/bold cyan]\n"
            f"  Backend  → [cyan]http://127.0.0.1:{backend_port}[/cyan]  "
            f"(cwd: {common.AGENT_DIR})\n"
            f"  Frontend → [cyan]http://localhost:{frontend_port}[/cyan]  "
            f"(cwd: {frontend_dir})",
            border_style="cyan",
            padding=(0, 1),
        )
    )
    common.console.print("[dim]Press Ctrl+C to stop both servers.[/dim]\n")

    children: common.List[common.subprocess.Popen] = []
    exit_code = common.EXIT_SUCCESS

    def _terminate_all() -> None:
        for child in children:
            if child.poll() is None:
                try:
                    child.terminate()
                except OSError:
                    pass

    try:
        backend = common.subprocess.Popen(backend_cmd, cwd=str(common.AGENT_DIR))
        children.append(backend)
        frontend = common.subprocess.Popen(frontend_cmd, cwd=str(frontend_dir))
        children.append(frontend)

        # Install signal handlers after tracking both children so shutdown can reach them.
        if common.threading.current_thread() is common.threading.main_thread():
            try:
                common.signal.signal(common.signal.SIGINT, lambda *_: _terminate_all())
            except (ValueError, OSError):
                pass
            try:
                common.signal.signal(common.signal.SIGTERM, lambda *_: _terminate_all())
            except (AttributeError, ValueError, OSError):
                pass

        # Wait for whichever process exits first; if it's the backend we
        # bring the frontend down too, and vice versa.
        while True:
            common.time.sleep(0.5)
            return_codes = [backend.poll(), frontend.poll()]
            if any(code is not None for code in return_codes):
                exit_code = next(
                    (code for code in return_codes if code not in (None, common.EXIT_SUCCESS)),
                    common.EXIT_SUCCESS,
                )
                break
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        common.console.print(f"[red]Failed to start development server:[/red] {exc}")
        exit_code = common.EXIT_RUN_FAILED
    finally:
        _terminate_all()
        # Give the children a brief grace period, then force-kill.
        deadline = common.time.time() + 5
        for child in children:
            remaining = max(0.0, deadline - common.time.time())
            try:
                child.wait(timeout=remaining)
            except common.subprocess.TimeoutExpired:
                try:
                    child.kill()
                except OSError:
                    pass
                try:
                    child.wait(timeout=1.0)
                except (OSError, common.subprocess.TimeoutExpired):
                    pass

    return exit_code
