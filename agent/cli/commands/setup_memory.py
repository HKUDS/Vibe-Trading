"""Non-interactive setup and persistent-memory commands."""
from __future__ import annotations

from cli.commands import runtime as _runtime

# The runtime owns shared constants, console objects, and service imports.
globals().update({k: v for k, v in vars(_runtime).items() if not k.startswith("__")})

def _validate_api_key(api_key: str, expected_prefix: str | None) -> bool:
    """Basic API-key format validation used during interactive setup."""
    if expected_prefix is None:
        return True
    return api_key.startswith(expected_prefix)

def cmd_memory_list(memory_type: Optional[str] = None, *, memory_dir: Optional[Path] = None) -> int:
    """List persisted memory entries."""
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    entries = pm.list_entries()
    if memory_type:
        entries = [e for e in entries if e.memory_type == memory_type]

    if not entries:
        scope = f" type={memory_type}" if memory_type else ""
        console.print(f"[dim]No memory entries found{scope}.[/dim]")
        return EXIT_SUCCESS

    entries.sort(key=lambda e: -e.modified_at)
    table = Table(title="Persistent Memory", box=box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Title", style="bold")
    table.add_column("Type")
    table.add_column("Description", overflow="fold")
    table.add_column("Modified", style="dim")

    for e in entries:
        style = _MEMORY_TYPE_STYLES.get(e.memory_type, "white")
        modified = datetime.fromtimestamp(e.modified_at).strftime("%Y-%m-%d %H:%M")
        table.add_row(
            rich_escape(e.title),
            f"[{style}]{e.memory_type}[/{style}]",
            rich_escape(e.description) or "—",
            modified,
        )

    console.print(table)
    console.print(f"[dim]{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}[/dim]")
    return EXIT_SUCCESS

def cmd_memory_show(name: str, *, memory_dir: Optional[Path] = None) -> int:
    """Show full content of a single memory entry."""
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    entry = pm.find(name)
    if entry is None:
        console.print(f"[red]Memory not found:[/red] {rich_escape(name)}")
        console.print("[dim]Run `vibe-trading memory list` to see available titles.[/dim]")
        return EXIT_USAGE_ERROR

    style = _MEMORY_TYPE_STYLES.get(entry.memory_type, "white")
    header = (
        f"[bold]{rich_escape(entry.title)}[/bold]\n"
        f"[{style}]{entry.memory_type}[/{style}]  •  [dim]{rich_escape(entry.path.name)}[/dim]\n"
        f"[dim]{rich_escape(entry.description)}[/dim]"
    )
    console.print(Panel(header, border_style="cyan"))
    console.print(rich_escape(entry.body.rstrip()) or "[dim](empty body)[/dim]")
    return EXIT_SUCCESS

def cmd_memory_search(query: str, max_results: int = 5, *, memory_dir: Optional[Path] = None) -> int:
    """Run keyword recall and display the top matches."""
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    results = pm.find_relevant(query, max_results=max_results)
    if not results:
        console.print(f"[dim]No matches for[/dim] [bold]{rich_escape(query)}[/bold]")
        return EXIT_SUCCESS

    table = Table(title=f"Recall: {rich_escape(query)}", box=box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Rank", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Type")
    table.add_column("Description", overflow="fold")

    for rank, e in enumerate(results, start=1):
        style = _MEMORY_TYPE_STYLES.get(e.memory_type, "white")
        table.add_row(
            str(rank),
            rich_escape(e.title),
            f"[{style}]{e.memory_type}[/{style}]",
            rich_escape(e.description) or "—",
        )

    console.print(table)
    return EXIT_SUCCESS

def cmd_memory_forget(name: str, *, yes: bool = False, memory_dir: Optional[Path] = None) -> int:
    """Remove a memory entry by name."""
    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory(memory_dir=memory_dir)
    entry = pm.find(name)
    if entry is None:
        console.print(f"[red]Memory not found:[/red] {rich_escape(name)}")
        return EXIT_USAGE_ERROR

    if not yes:
        style = _MEMORY_TYPE_STYLES.get(entry.memory_type, "white")
        console.print(
            f"About to forget [bold]{rich_escape(entry.title)}[/bold] "
            f"([{style}]{entry.memory_type}[/{style}], {rich_escape(entry.path.name)})."
        )
        try:
            proceed = Confirm.ask("Proceed?", default=False)
        except EOFError:
            console.print("[dim]No input available; use --yes for non-interactive deletes.[/dim]")
            return EXIT_USAGE_ERROR
        if not proceed:
            console.print("[dim]Aborted.[/dim]")
            return EXIT_SUCCESS

    if pm.remove_entry(entry):
        console.print(f"[green]Forgot[/green] {rich_escape(entry.title)}")
        return EXIT_SUCCESS
    console.print(f"[red]Failed to remove[/red] {rich_escape(entry.title)}")
    return EXIT_RUN_FAILED

def cmd_init() -> int:
    """Interactive setup: create ~/.vibe-trading/.env."""
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

    from src.providers.settings import SettingsStore

    SettingsStore(path=_INIT_ENV_PATH).persist(env_values, replace=True)

    next_steps = Table.grid(expand=True)
    next_steps.add_column(width=10, style="dim")
    next_steps.add_column(ratio=1)
    next_steps.add_row("Config", f"[cyan]{_INIT_ENV_PATH}[/cyan]")
    next_steps.add_row("Run", "[bold]vibe-trading[/bold]")
    if provider == "openai-codex":
        next_steps.add_row("OAuth", "[bold]vibe-trading provider login openai-codex[/bold]")
    console.print(Panel(next_steps, title="Setup complete", border_style="green", padding=(0, 1)))
    return 0

def _is_windows() -> bool:
    """True when running on a Windows-like platform (win32, including Cygwin/MSYS)."""
    return sys.platform == "win32"

def _resolve_node_and_npm() -> tuple[Optional[str], Optional[str]]:
    """Return ``(node_path, npm_path)`` if both are on PATH, else ``(None, None)``.

    Used by ``cmd_setup`` to fail fast with a clear message instead of
    surfacing a cryptic ENOENT from npm itself.
    """
    node = shutil.which("node")
    npm = shutil.which("npm")
    return node, npm

def _build_frontend_cmd(frontend_dir: Path) -> list[list[str]]:
    """Return the ordered list of subprocess invocations needed to build the frontend.

    On Windows we explicitly pin ``--package=typescript`` / ``--package=vite``
    so npm cannot accidentally fetch the abandoned ``tsc`` package from the
    registry. On POSIX systems, ``npm run build`` is sufficient because npm
    prepends ``./node_modules/.bin`` to ``PATH`` for local scripts.

    Each inner list is a single ``subprocess.run`` invocation. Returned as a
    list of steps so the caller can stream progress.
    """
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
    cwd: Path,
) -> bool:
    """Run one subprocess step, returning True on success.

    Decodes subprocess output as UTF-8 with ``errors="replace"`` so that
    non-ASCII bytes emitted by tools like Vite do not raise
    ``UnicodeDecodeError`` on platforms whose default codec is GBK/CP936
    (notably Windows). The captured text is only used to surface a
    friendly error message; lossy decoding is acceptable here.
    """
    console.print(f"[dim]  {description} …[/dim]")
    try:
        result = subprocess.run(
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
        console.print(f"[red]  failed:[/red] {exc}")
        return False
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        # Show the last 20 lines to keep noise manageable.
        tail = "\n".join(err.splitlines()[-20:]) if err else "(no output)"
        console.print(f"[red]  {description} failed:[/red]\n{tail}")
        return False
    return True

def cmd_setup(frontend_dir: Path) -> int:
    """Install frontend dependencies and build the production bundle.

    Cross-platform wrapper that hides the ``npx tsc`` / ``npm exec tsc``
    Windows footgun. Equivalent to running ``cd frontend && npm install
    && npm run build`` from a POSIX shell, but works on Windows without
    the user having to know about the abandoned ``tsc`` package on the
    npm registry.
    """
    console.print(
        Panel(
            f"[bold cyan]Vibe-Trading frontend setup[/bold cyan]\n"
            f"[dim]{frontend_dir}[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )
    )

    if not frontend_dir.exists():
        console.print(
            f"[red]Frontend directory not found:[/red] {frontend_dir}\n"
            "[dim]Pass --frontend-dir to point at a different location.[/dim]"
        )
        return EXIT_USAGE_ERROR

    node, npm = _resolve_node_and_npm()
    if not node or not npm:
        missing = [name for name, path_ in (("node", node), ("npm", npm)) if not path_]
        console.print(
            f"[red]Required tool not on PATH:[/red] {', '.join(missing)}\n"
            "[dim]Install Node.js (>= 18) from https://nodejs.org and retry.[/dim]"
        )
        return EXIT_USAGE_ERROR

    # On Windows, ``npm`` is shipped as ``npm.cmd``; ``subprocess.run`` does
    # not consult ``PATHEXT`` for bare command names, so it would raise
    # ``FileNotFoundError`` even though ``shutil.which("npm")`` returned a
    # valid path. Resolve to the full path before invoking.
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
            return EXIT_RUN_FAILED

    console.print(
        Panel(
            "[green]Frontend built.[/green]\n"
            f"  Artifacts: [cyan]{frontend_dir / 'dist'}[/cyan]\n"
            "[dim]Run [bold]vibe-trading serve[/bold] to serve everything on one port.[/dim]",
            border_style="green",
            padding=(0, 1),
        )
    )
    return EXIT_SUCCESS

def cmd_dev(
    backend_port: int = 8899,
    frontend_port: int = 5899,
    frontend_dir: Optional[Path] = None,
) -> int:
    """Start backend + Vite dev server in one foreground process.

    Spawns two child processes:

    * The FastAPI backend, launched from ``AGENT_DIR`` so that
      ``python -m cli._legacy serve`` resolves the in-repo ``cli`` package
      (launching it from the repo root would fail with
      ``ModuleNotFoundError: No module named 'cli'``).
    * The Vite dev server, launched from ``frontend_dir`` with the port
      from ``vite.config.ts`` (currently 5899). We do NOT hardcode
      ``5173`` — that would be wrong for this project.

    Both children inherit stdout/stderr so their logs are interleaved
    with the dev banner. ``Ctrl+C`` (SIGINT) and ``SIGTERM`` cleanly
    terminate both children.
    """
    frontend_dir = frontend_dir or (AGENT_DIR.parent / "frontend")
    if not frontend_dir.exists():
        console.print(
            f"[red]Frontend directory not found:[/red] {frontend_dir}\n"
            "[dim]Pass --frontend-dir to point at a different location.[/dim]"
        )
        return EXIT_USAGE_ERROR

    # `npm run dev` invokes the local Vite binary at
    # ``frontend/node_modules/.bin/vite``. If ``node_modules`` does not
    # exist (or is missing the Vite package), npm's bare-script
    # resolution will print a confusing "vite is not a command" error
    # and exit. Detect this case up front and point the user at
    # ``vibe-trading setup`` instead.
    vite_bin = frontend_dir / "node_modules" / ".bin" / ("vite.cmd" if _is_windows() else "vite")
    if not vite_bin.exists():
        console.print(
            Panel(
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
        return EXIT_USAGE_ERROR

    node, npm = _resolve_node_and_npm()
    if not node or not npm:
        missing = [name for name, path_ in (("node", node), ("npm", npm)) if not path_]
        console.print(
            f"[red]Required tool not on PATH:[/red] {', '.join(missing)}\n"
            "[dim]Install Node.js (>= 18) from https://nodejs.org and retry.[/dim]"
        )
        return EXIT_USAGE_ERROR

    backend_cmd = [sys.executable, "-m", "cli._legacy", "serve", "--port", str(backend_port)]
    # On Windows, ``npm`` is typically ``npm.cmd``. ``subprocess.Popen`` does
    # not consult ``PATHEXT`` for bare command names, so the call would fail
    # with ``FileNotFoundError`` even though ``shutil.which("npm")`` returned
    # a path. Use the resolved executable path directly.
    npm_executable = npm if _is_windows() else "npm"
    frontend_cmd = [npm_executable, "run", "dev", "--", "--port", str(frontend_port)]

    console.print(
        Panel(
            f"[bold cyan]Vibe-Trading dev[/bold cyan]\n"
            f"  Backend  → [cyan]http://127.0.0.1:{backend_port}[/cyan]  "
            f"(cwd: {AGENT_DIR})\n"
            f"  Frontend → [cyan]http://localhost:{frontend_port}[/cyan]  "
            f"(cwd: {frontend_dir})",
            border_style="cyan",
            padding=(0, 1),
        )
    )
    console.print("[dim]Press Ctrl+C to stop both servers.[/dim]\n")

    children: List[subprocess.Popen] = []
    exit_code = EXIT_SUCCESS

    def _terminate_all() -> None:
        for child in children:
            if child.poll() is None:
                try:
                    child.terminate()
                except OSError:
                    pass

    try:
        backend = subprocess.Popen(backend_cmd, cwd=str(AGENT_DIR))
        children.append(backend)
        frontend = subprocess.Popen(frontend_cmd, cwd=str(frontend_dir))
        children.append(frontend)

        # Wire signal handlers only after both children are tracked. On
        # Windows, SIGTERM may not exist and handlers must be installed from
        # the main thread; KeyboardInterrupt remains the portable Ctrl+C path.
        if threading.current_thread() is threading.main_thread():
            try:
                signal.signal(signal.SIGINT, lambda *_: _terminate_all())
            except (ValueError, OSError):
                pass
            try:
                signal.signal(signal.SIGTERM, lambda *_: _terminate_all())
            except (AttributeError, ValueError, OSError):
                pass

        # Wait for whichever process exits first; if it's the backend we
        # bring the frontend down too, and vice versa.
        while True:
            time.sleep(0.5)
            return_codes = [backend.poll(), frontend.poll()]
            if any(code is not None for code in return_codes):
                exit_code = next(
                    (code for code in return_codes if code not in (None, EXIT_SUCCESS)),
                    EXIT_SUCCESS,
                )
                break
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        console.print(f"[red]Failed to start development server:[/red] {exc}")
        exit_code = EXIT_RUN_FAILED
    finally:
        _terminate_all()
        # Give the children a brief grace period, then force-kill.
        deadline = time.time() + 5
        for child in children:
            remaining = max(0.0, deadline - time.time())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    child.kill()
                except OSError:
                    pass
                try:
                    child.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass

    return exit_code
