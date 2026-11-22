"""CLI execution commands and their helpers."""
from __future__ import annotations

from cli.commands import common
from cli.commands import inspection
from cli.ui import rail

def _strip_rich_tags(text: str) -> str:
    """Remove Rich markup from plain-text output."""
    return common.RICH_TAG_PATTERN.sub("", text)


def _print_json_result(result: dict) -> None:
    """Print a machine-readable run summary."""
    payload = {
        "status": result.get("status", "unknown"),
        "run_id": result.get("run_id"),
        "run_dir": result.get("run_dir"),
        "reason": result.get("reason"),
    }
    if result.get("status") == "waiting_user":
        payload["content"] = result.get("content")
    print(common.json.dumps(payload, ensure_ascii=False))


def _result_exit_code(result: dict) -> int:
    """Map run results to stable exit codes."""
    return common.EXIT_SUCCESS if result.get("status") in {"success", "waiting_user"} else common.EXIT_RUN_FAILED


def _coerce_exit_code(value: common.Optional[int]) -> int:
    """Normalize command return values to an integer exit code."""
    return common.EXIT_SUCCESS if value is None else int(value)


def _read_prompt_source(
    prompt: common.Optional[str],
    prompt_file: common.Optional[common.Path],
    *,
    no_rich: bool,
    allow_interactive: bool = True,
) -> tuple[common.Optional[str], common.Optional[str]]:
    """Resolve prompt text from CLI args, file, stdin, or interactive input."""
    if prompt is not None:
        return prompt.strip(), None

    if prompt_file is not None:
        try:
            return prompt_file.read_text(encoding="utf-8").strip(), None
        except OSError as exc:
            return None, f"Failed to read prompt file: {exc}"

    if not common.sys.stdin.isatty():
        return common.sys.stdin.read().strip(), None

    if not allow_interactive:
        return None, "A prompt is required."

    try:
        if no_rich:
            return input("Enter strategy request: ").strip(), None
        return common.Prompt.ask("Enter strategy request").strip(), None
    except (EOFError, KeyboardInterrupt):
        return None, "Prompt input cancelled."


def _ensure_cli_env() -> None:
    """Load dotenv values before a CLI path reads configuration."""
    try:
        from src.providers.settings import _ensure_dotenv

        _ensure_dotenv()
    except Exception:
        pass


def _format_tool_call_args(tool: str, args: common.Dict[str, str]) -> str:
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
        sharpe = common.re.search(r'"sharpe":\s*([\d.eE+-]+)', preview)
        ret = common.re.search(r'"total_return":\s*([\d.eE+-]+)', preview)
        parts = []
        if sharpe:
            parts.append(f"sharpe={sharpe.group(1)}")
        if ret:
            parts.append(f"return={float(ret.group(1))*100:.1f}%")
        return ", ".join(parts) if parts else ""
    if tool == "render_shadow_report":
        url = common.re.search(r'"report_url":\s*"([^"]+)"', preview)
        if url:
            return f"[bold cyan]report:[/bold cyan] [link]{url.group(1)}[/link]"
        return ""
    if tool in ("extract_shadow_strategy", "run_shadow_backtest"):
        sid = common.re.search(r'"shadow_id":\s*"([^"]+)"', preview)
        return f"shadow_id={sid.group(1)}" if sid else ""
    if tool in ("bash", "background_run"):
        if "OK" in preview[:50]:
            return "OK"
        return preview[:60].replace("\n", " ")
    if tool in ("read_file", "load_skill", "compact"):
        return ""
    return ""


def _load_full_proposal(proposal_id: str) -> common.Optional[common.Dict[str, common.Any]]:
    """Reload a persisted ``mandate.proposal`` payload by id, broker-agnostic.

    The propose tool persists the full proposal under
    ``<runtime_root>/live/<broker>/proposals/<proposal_id>.json`` before
    returning. The ``tool_result`` preview is only the first 200 chars of the
    JSON body, far too short to carry the full proposal, so the relay reloads it
    from disk. The broker segment is unknown from the preview alone, so every
    broker's proposals directory is searched (mirrors api_server).

    Args:
        proposal_id: The ``mp_...`` id parsed from the tool_result preview.

    Returns:
        The full proposal dict, or ``None`` when not found / unreadable.
    """
    try:
        from src.live.paths import live_root

        for proposal_path in live_root().glob(f"*/proposals/{proposal_id}.json"):
            try:
                data = common.json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, common.json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("type") == "mandate.proposal":
                return data
    except Exception:  # noqa: BLE001 — relay must never break the turn
        pass
    return None


def _mandate_proposal_from_tool_result(data: common.Dict[str, common.Any]) -> common.Optional[common.Dict[str, common.Any]]:
    """Recover a full ``mandate.proposal`` payload from a propose-tool result.

    Detection mirrors the session SSE reader's ``_mandate_proposal_frame_from_tool_result``:
    the event must be a successful ``tool_result`` for ``propose_mandate_profiles``
    whose preview carries a ``proposal_id``. The full proposal is then reloaded
    from disk (the preview is truncated).

    Args:
        data: The ``tool_result`` event payload (``tool`` / ``status`` /
            ``preview``).

    Returns:
        The full proposal dict ready to feed ``proposal_sink`` (arming
        ``ctx.pending_proposal``), or ``None`` when this is not a recoverable
        propose-tool result.
    """
    if data.get("tool") != _PROPOSAL_TOOL_NAME or data.get("status") != "ok":
        return None
    match = _PROPOSAL_ID_RE.search(str(data.get("preview") or ""))
    if not match:
        return None
    return _load_full_proposal(match.group(1))


def _scheduled_proposal_from_tool_result(data: common.Dict[str, common.Any]) -> common.Optional[common.Dict[str, common.Any]]:
    """Recover the full scheduled-research proposal from a tool preview."""
    if data.get("tool") != _SCHEDULED_PROPOSAL_TOOL_NAME or data.get("status") != "ok":
        return None
    match = _SCHEDULED_PROPOSAL_ID_RE.search(str(data.get("preview") or ""))
    if not match:
        return None
    try:
        from src.scheduled_research.proposals import load_proposal

        return load_proposal(match.group(1))
    except Exception:  # noqa: BLE001 - relay must never break the turn
        return None


def _ensure_session_id(title: str, *, session_id: common.Optional[str] = None) -> str:
    """Return a host-owned session id, registering the session record if new.

    The research-goal tools are registered unconditionally and resolve their
    session from the host runtime, so any entry point that calls
    :func:`_run_agent` without an id makes every goal call fail validation with
    ``session_id is required`` while the run still reports success (#885).

    Persistence is best effort. ``Session`` populates ``session_id`` on
    construction, so a store or index failure still yields a usable id rather
    than falling back to the empty string that caused the bug.

    Args:
        title: Text used as the session title; truncated for display.
        session_id: Explicit id to register, for callers that need the same
            session across repeated invocations. Defaults to a fresh id.

    Returns:
        A non-empty session id.
    """
    from src.session.models import Session, SessionStatus
    from src.session.store import SessionStore

    session = Session(
        title=title.strip()[:60] or "untitled",
        status=SessionStatus.ACTIVE,
    )
    if session_id:
        session.session_id = session_id
    try:
        SessionStore(base_dir=common.SESSIONS_DIR).create_session(session)
    except Exception:  # noqa: BLE001 — an existing or unwritable session must not block the run
        return session.session_id

    # Index for FTS5 cross-session search, mirroring the interactive REPL.
    try:
        from src.session.search import get_shared_index

        get_shared_index().index_session(session.session_id, session.title)
    except Exception:  # noqa: BLE001 — search index is optional
        pass
    return session.session_id


def _run_agent(
    prompt: str,
    run_dir_override: common.Optional[str] = None,
    max_iter: int = 50,
    *,
    no_rich: bool = False,
    stream_output: bool = True,
    dashboard: common.Optional[rail.RailRunDashboard] = None,
    session_id: str = "",
    proposal_sink: common.Optional[common.Any] = None,
) -> dict:
    """Build AgentRuntime and execute, return result dict.

    A turn with a ``session_id`` is recorded like a web turn
    (:mod:`cli.conversation`): the history the model sees is replayed from the
    session's thread log, never passed in by the caller, and the turn's items
    and reply row are written back to the session.

    Args:
        proposal_sink: Optional callable invoked with the payload of every
            ``mandate.proposal`` event the agent emits. The interactive REPL
            uses this to capture an outstanding live-trading mandate proposal so
            it can intercept the user's numeric pick *before* the model — a pick
            is a privileged surface action (commit), never a tool the model can
            call (SPEC.md Consent §2).
    """
    from src.tools import build_registry
    from src.providers.selection import ModelSelectionError
    from src.session.model_selection import (
        chat_llm_for_stored_session,
        unavailable_selection_result,
    )
    from src.agent.runtime import AgentRuntime

    # Closure-level state for the no-rich path so dots and progress lines
    # don't shoulder-bump each other (M3) and progress prints are throttled
    # to ≤1/0.5s per tool (M1).
    no_rich_state: dict[str, common.Any] = {
        "dot_pending": False,
        "last_progress_ts": {},  # type: ignore[var-annotated]
    }

    streamed_text: list[str] = []

    def on_event(event_type: str, data: common.Dict[str, common.Any]) -> None:
        kind = data.get("kind", event_type)
        heartbeat = bool(data.get("heartbeat"))
        envelope = data
        item = data.get("item") or {}
        if kind in {"tool.started", "tool.completed", "tool.failed"}:
            data = {**item, "tool": item.get("name"), "call_id": item.get("tool_call_id"), "preview": item.get("content")}
        elif kind == "tool.progress":
            data = data.get("progress") or {}
        # Text streamed so far, kept for the reply of a turn the user stops.
        if kind == "text.reset":
            streamed_text.clear()
        elif kind == "text.delta" and isinstance(data.get("delta"), str):
            streamed_text.append(data["delta"])
        # Live mandate proposals are surfaced to the REPL out-of-band so the
        # user's pick is intercepted before the model (SPEC.md Consent §2).
        # This fires regardless of stream_output / rich state — capturing the
        # proposal must not depend on rendering.
        if event_type == "mandate.proposal" and proposal_sink is not None:
            try:
                proposal_sink(data)
            except Exception:  # noqa: BLE001 — capture must never kill the turn
                pass
            return
        # The agent loop never emits a top-level ``mandate.proposal`` — it only
        # emits the propose tool's output as a generic ``tool_result``. Relay it
        # here (CLI mirror of api_server's SSE relay) so the REPL arms
        # ``ctx.pending_proposal`` and intercepts the pick before the model
        # (SPEC.md Consent §1/§2). Fires regardless of stream_output / rich
        # state — arming must not depend on rendering — and does NOT return:
        # the tool_result still flows on to the dashboard / no-rich printers.
        if kind == "tool.completed" and proposal_sink is not None:
            proposal = _mandate_proposal_from_tool_result(data)
            if proposal is None:
                proposal = _scheduled_proposal_from_tool_result(data)
            if proposal is not None:
                try:
                    proposal_sink(proposal)
                except Exception:  # noqa: BLE001 — relay must never kill the turn
                    pass
        if not stream_output:
            return
        if dashboard is not None and not no_rich:
            dashboard.handle_event(event_type, envelope)
            return
        if no_rich and kind == "item.completed":
            print()
            return
        if no_rich and kind == "tool.started":
            tool = data.get("tool", "")
            args = data.get("arguments", {})
            args_preview = _format_tool_call_args(tool, args)
            print(f"  - {tool}{_strip_rich_tags(args_preview)}", end="")
            no_rich_state["dot_pending"] = False
            return
        if no_rich and kind in {"tool.completed", "tool.failed"}:
            tool = data.get("tool", "")
            status = data.get("status", "ok")
            elapsed_ms = data.get("elapsed_ms", 0)
            elapsed_s = elapsed_ms / 1000
            preview = _format_tool_result_preview(tool, status, data.get("preview", ""))
            suffix = f"  {preview}" if preview else ""
            mark = "OK" if status == "ok" else "FAIL"
            # If a heartbeat dot is open on the line, break it cleanly.
            if no_rich_state["dot_pending"]:
                no_rich_state["dot_pending"] = False
            print(f"  {mark} {elapsed_s:.1f}s{_strip_rich_tags(suffix)}")
            no_rich_state["last_progress_ts"].pop(tool, None)
            return
        if no_rich and kind == "context.compacted":
            tokens = data.get("tokens_before", "?")
            if no_rich_state["dot_pending"]:
                no_rich_state["dot_pending"] = False
                print()
            print(f"\n  context compressed ({tokens} tokens -> summary)\n")
            return
        if no_rich and kind == "tool.progress" and heartbeat:
            # Print a dot per tick so the user sees the tool is alive.
            print(".", end="", flush=True)
            no_rich_state["dot_pending"] = True
            return
        if no_rich and kind == "tool.progress":
            tool = data.get("tool", "") or ""
            now = common.time.monotonic()
            last_ts = no_rich_state["last_progress_ts"].get(tool, 0.0)
            if now - last_ts < 0.5:
                # Throttle: max one progress line per 0.5s per tool (M1).
                return
            no_rich_state["last_progress_ts"][tool] = now
            stage = data.get("stage", "")
            current_idx = data.get("current")
            total = data.get("total")
            message = data.get("message", "")
            bits = [stage]
            if isinstance(current_idx, int) and isinstance(total, int) and total > 0:
                bits.append(f"{current_idx}/{total}")
            if message:
                bits.append(message)
            label = " · ".join(b for b in bits if b)
            if label:
                # Break a pending dot line before printing the progress detail.
                if no_rich_state["dot_pending"]:
                    no_rich_state["dot_pending"] = False
                    print()
                print(f"    {label}", flush=True)
            return
        if kind == "text.delta":
            if no_rich:
                print(data.get("delta", ""), end="")
            else:
                common.console.print(data.get("delta", ""), end="", style="dim")
        elif kind == "item.completed":
            common.console.print()
        elif kind == "tool.started":
            tool = data.get("tool", "")
            args = data.get("arguments", {})
            args_preview = _format_tool_call_args(tool, args)
            common.console.print(f"  [cyan]\u25b6 {tool}[/cyan]{args_preview}", end="")
        elif kind in {"tool.completed", "tool.failed"}:
            tool = data.get("tool", "")
            status = data.get("status", "ok")
            elapsed_ms = data.get("elapsed_ms", 0)
            elapsed_s = elapsed_ms / 1000
            ok = status == "ok"
            mark = "[green]\u2713[/green]" if ok else "[red]\u2717[/red]"
            preview = _format_tool_result_preview(tool, status, data.get("preview", ""))
            suffix = f"  {preview}" if preview else ""
            common.console.print(f"  {mark} [dim]{elapsed_s:.1f}s[/dim]{suffix}")
        elif kind == "context.compacted":
            tokens = data.get("tokens_before", "?")
            common.console.print(f"\n  [yellow]\u27f3 context compressed[/yellow] [dim]({tokens} tokens \u2192 summary)[/dim]\n")

    from src.memory.persistent import PersistentMemory

    pm = PersistentMemory()
    from src.config.loader import load_agent_config

    agent_config = load_agent_config()

    def _mcp_warn(msg: str) -> None:
        if no_rich:
            print(f"WARNING: {msg}", flush=True)
        else:
            common.console.print(f"[yellow]WARNING:[/yellow] {msg}")

    # One owner for the whole CLI run: background results stay with the
    # conversation that started them, and a bare run gets a private owner
    # instead of a view shared with every other run in the process.
    from src.tools.background_tools import BackgroundScope, get_background_manager

    background_scope = BackgroundScope(
        owner_id=f"session:{session_id}" if session_id else f"cli:{common.uuid.uuid4().hex}"
    )
    background = get_background_manager().for_scope(background_scope)
    cancel_event = common.threading.Event()

    try:
        llm = chat_llm_for_stored_session(common.SESSIONS_DIR, session_id)
    except ModelSelectionError as exc:
        return unavailable_selection_result(exc)

    registry = build_registry(
        persistent_memory=pm,
        include_shell_tools=True,
        agent_config=agent_config,
        session_id=session_id or None,
        warn_callback=_mcp_warn,
        background_manager=background,
        background_scope=background_scope,
        cancel_event=cancel_event,
    )

    # Opened only once the agent can run: it writes the user's message and
    # replays the session's history, and a turn left open would be replayed
    # as interrupted.
    turn = None
    if session_id:
        from cli.conversation import open_turn
        from src.session.store import SessionStore

        snapshot = getattr(llm, "runtime_snapshot", None)
        turn = open_turn(
            SessionStore(base_dir=common.SESSIONS_DIR), session_id, prompt,
            provider=getattr(snapshot, "provider", None),
            model=getattr(snapshot, "configured_model", None),
        )

    try:
        agent = AgentRuntime(
            registry=registry,
            llm=llm,
            event_callback=on_event,
            max_iterations=max_iter,
            persistent_memory=pm,
            background_manager=background,
            cancel_event=cancel_event,
            thread_recorder=turn.recorder if turn is not None else None,
        )
        agent.instruction_launch_dir = common.Path.cwd()
        if run_dir_override:
            agent.memory.run_dir = run_dir_override

        result = _run_with_graceful_cancel(
            agent,
            prompt,
            (turn.history or None) if turn is not None else None,
            no_rich=no_rich,
            session_id=session_id,
        )
    except BaseException as exc:
        # A forced quit (second Ctrl+C) or a crash: close the turn so the
        # next one replays it as stopped instead of finding it open.
        if turn is not None:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                turn.abort("cancelled", "Interrupted")
            else:
                turn.abort("failed", str(exc))
        raise
    if turn is not None:
        result = turn.finish(result, "".join(streamed_text))
    return result


def _run_with_graceful_cancel(
    agent: "common.AgentRuntime",
    prompt: str,
    history: common.Optional[common.List[common.Dict]],
    *,
    no_rich: bool,
    session_id: str = "",
) -> dict:
    """Run an agent loop with first-Ctrl+C = graceful cancel.

    First SIGINT during the run sets ``agent._cancelled`` so the loop exits
    cleanly after the current LLM/tool step finishes. A second SIGINT within
    two seconds restores the default handler and re-raises ``KeyboardInterrupt``
    for hard quit. Outside of a run the parent CLI's normal SIGINT handling
    (exit on input prompt) is unaffected — the handler is restored in
    ``finally``.

    Args:
        agent: AgentRuntime instance ready to ``run()``.
        prompt: User prompt.
        history: Recent message history.
        no_rich: Whether the parent caller is rendering with Rich Live.

    Returns:
        AgentRuntime result dict.
    """
    import signal as _signal

    state = {"requested": False, "last_ts": 0.0}
    try:
        original = _signal.getsignal(_signal.SIGINT)
    except (ValueError, AttributeError):
        # Not on a thread that can receive signals — skip the handler swap.
        return agent.run(user_message=prompt, history=history, session_id=session_id)

    def _on_sigint(_signum, _frame) -> None:
        now = common.time.time()
        if state["requested"] and (now - state["last_ts"]) < 2.0:
            # Second Ctrl+C within 2s — hand control back to the default handler.
            _signal.signal(_signal.SIGINT, original)
            raise KeyboardInterrupt
        state["requested"] = True
        state["last_ts"] = now
        agent.cancel()
        notice = "Cancelling… current step will finish, then exit. Ctrl+C again to force quit."
        if no_rich:
            print(f"\n[{notice}]", flush=True)
        else:
            common.console.print(f"\n[yellow]{notice}[/yellow]")

    try:
        _signal.signal(_signal.SIGINT, _on_sigint)
    except (ValueError, OSError):
        # signal.signal only works on the main thread of the main interpreter.
        return agent.run(user_message=prompt, history=history, session_id=session_id)

    try:
        return agent.run(user_message=prompt, history=history, session_id=session_id)
    finally:
        try:
            _signal.signal(_signal.SIGINT, original)
        except (ValueError, OSError):
            pass


def _build_benchmark_table(m: dict) -> common.Optional[common.Table]:
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

    table = common.Table(show_header=False, padding=(0, 2))
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
    style = inspection._status_style(status)
    run_dir = result.get("run_dir")
    m = inspection._read_metrics(common.Path(run_dir) / "artifacts" / "metrics.csv") if run_dir else {}

    if no_rich:
        print(f"Status: {status.upper()}")
        print(f"Elapsed: {inspection._format_seconds(elapsed)}")
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

    summary = common.Table.grid(expand=True)
    summary.add_column(width=12, style="dim")
    summary.add_column(ratio=1)
    summary.add_row("Status", f"[bold {style}]{status.upper()}[/bold {style}]")
    summary.add_row("Elapsed", inspection._format_seconds(elapsed))
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

    panels = [common.Panel(summary, border_style=style, title="Summary", padding=(0, 1))]

    metric_table = common.Table.grid(expand=True)
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
        value_style = inspection._metric_value_style(key, value)
        metric_table.add_row(label, f"[{value_style}]{value}[/{value_style}]")
        has_metrics = True
    if has_metrics:
        panels.append(common.Panel(metric_table, border_style="cyan", title="Metrics", padding=(0, 1)))

    if result.get("run_id"):
        rid = result["run_id"]
        actions = common.Table(box=None, show_header=False, padding=(0, 1))
        actions.add_column(style="cyan", no_wrap=True)
        actions.add_column(style="dim")
        actions.add_row(f"vibe-trading show {rid}", "details")
        actions.add_row(f"vibe-trading code {rid}", "generated Python")
        actions.add_row(f"vibe-trading continue {rid} \"...\"", "refine this run")
        panels.append(common.Panel(actions, border_style="dim", title="Next", padding=(0, 1)))

    if inspection._terminal_width() < 104:
        for panel in panels:
            common.console.print(panel)
    else:
        common.console.print(common.Columns(panels, expand=True, equal=True))

    # Benchmark comparison panel.
    bench_table = _build_benchmark_table(m)
    if bench_table:
        common.console.print(common.Panel(
            bench_table,
            border_style="cyan",
            title="Benchmark Comparison",
            padding=(0, 1),
        ))
    # End benchmark comparison panel.

    content = result.get("content", "").strip()
    if content:
        common.console.print(f"\n{content}")


def cmd_run(prompt: str, max_iter: int, *, json_mode: bool = False, no_rich: bool = False) -> int:
    """Single run."""
    if not json_mode:
        from src.preflight import run_preflight
        results = run_preflight(common.console)
        if any(r.critical and r.status != "ready" for r in results):
            return common.EXIT_RUN_FAILED

    if not json_mode:
        preview = prompt[:120]
        suffix = "..." if len(prompt) > 120 else ""
        if no_rich:
            print(f"Prompt: {preview}{suffix}\n")
        else:
            common.console.print(f"[dim]Prompt:[/dim] {preview}{suffix}\n")
    start = common.time.perf_counter()
    session_id = _ensure_session_id(prompt)
    try:
        if json_mode or no_rich:
            result = _run_agent(
                prompt,
                max_iter=max_iter,
                no_rich=no_rich,
                stream_output=not json_mode,
                session_id=session_id,
            )
        else:
            dashboard = rail.RailRunDashboard(prompt, max_iter)
            with common.Live(dashboard.render(), console=common.console, refresh_per_second=6, transient=True) as live:
                dashboard.live = live
                result = _run_agent(
                    prompt, max_iter=max_iter, dashboard=dashboard, session_id=session_id
                )
                dashboard.finish(result, common.time.perf_counter() - start)
    except KeyboardInterrupt:
        if json_mode:
            _print_json_result({"status": "cancelled", "run_id": None, "run_dir": None, "reason": "Interrupted"})
            return common.EXIT_RUN_FAILED
        if no_rich:
            print("\nInterrupted")
            return common.EXIT_RUN_FAILED
        common.console.print("\n[yellow]Interrupted[/yellow]")
        return common.EXIT_RUN_FAILED
    if json_mode:
        _print_json_result(result)
        return _result_exit_code(result)
    _print_result(result, common.time.perf_counter() - start, no_rich=no_rich)
    if result.get("run_id") and result.get("run_dir"):
        # Point at the dashboard without starting anything. Spawning a server
        # from a result-printing path would leave an unsupervised process behind
        # after the command exits.
        if inspection._read_metric_values(common.Path(result["run_dir"]) / "artifacts" / "metrics.csv"):
            hint = (
                f"Dashboard: run `vibe-trading serve`, then open "
                f"/runs/{result['run_id']}?view=dashboard"
            )
            if no_rich:
                print(hint)
            else:
                common.console.print(f"[dim]{hint}[/dim]")
    if result.get("run_id"):
        tip = f"--show {result['run_id']}  |  --continue {result['run_id']} \"...\"  |  --code {result['run_id']}  |  --pine {result['run_id']}"
        if no_rich:
            print(tip)
        else:
            common.console.print(f"[dim]{tip}[/dim]")
    return _result_exit_code(result)


def cmd_continue(
    run_id: str,
    prompt: str,
    max_iter: int,
    *,
    json_mode: bool = False,
    no_rich: bool = False,
) -> int:
    """Continue an existing run."""
    run_dir = common.RUNS_DIR / run_id
    session_trace_dir = common.SESSIONS_DIR / run_id
    if not run_dir.exists() and not session_trace_dir.exists():
        if no_rich:
            print(f"Run {run_id} not found")
            return common.EXIT_USAGE_ERROR
        common.console.print(f"[red]Run {run_id} not found[/red]")
        return common.EXIT_USAGE_ERROR
    trace_dir = session_trace_dir if session_trace_dir.exists() else run_dir
    trace_dir.mkdir(parents=True, exist_ok=True)

    # Continuations of one run share a session so goals and evidence accumulate
    # across them, and so does the history the model sees: ``_run_agent``
    # replays it from that session's thread log. A session-backed run_id
    # already *is* a session id (sessions and their traces share
    # ``SESSIONS_DIR``); a plain run gets a derived id.
    session_id = _ensure_session_id(
        prompt,
        session_id=run_id if session_trace_dir.exists() else f"run-{run_id}",
    )
    if not json_mode and no_rich:
        print(f"Continue {run_id}: {prompt[:120]}\n")
    if json_mode or no_rich:
        start = common.time.perf_counter()
        try:
            result = _run_agent(
                prompt,
                run_dir_override=str(trace_dir),
                max_iter=max_iter,
                no_rich=no_rich,
                stream_output=not json_mode,
                session_id=session_id,
            )
        except KeyboardInterrupt:
            if json_mode:
                _print_json_result(
                    {
                        "status": "cancelled",
                        "run_id": run_id,
                        "run_dir": str(trace_dir),
                        "reason": "Interrupted",
                    }
                )
            else:
                print("\nInterrupted")
            return common.EXIT_RUN_FAILED
        if json_mode:
            _print_json_result(result)
            return _result_exit_code(result)
        _print_result(result, common.time.perf_counter() - start, no_rich=True)
        return _result_exit_code(result)

    common.console.print(f"[dim]Continue {run_id}:[/dim] {prompt[:120]}\n")
    start = common.time.perf_counter()
    try:
        dashboard = rail.RailRunDashboard(prompt, max_iter)
        with common.Live(dashboard.render(), console=common.console, refresh_per_second=6, transient=True) as live:
            dashboard.live = live
            result = _run_agent(
                prompt,
                run_dir_override=str(trace_dir),
                max_iter=max_iter,
                dashboard=dashboard,
                session_id=session_id,
            )
            dashboard.finish(result, common.time.perf_counter() - start)
    except KeyboardInterrupt:
        common.console.print("\n[yellow]Interrupted[/yellow]")
        return common.EXIT_RUN_FAILED
    _print_result(result, common.time.perf_counter() - start)
    return _result_exit_code(result)


def _handle_prompt_command(
    prompt: common.Optional[str],
    prompt_file: common.Optional[common.Path],
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
            print(error_message) if no_rich else common.console.print(message)
        return common.EXIT_USAGE_ERROR
    if not resolved_prompt:
        if json_mode:
            _print_json_result({"status": "failed", "run_id": None, "run_dir": None, "reason": "Prompt cannot be empty"})
        else:
            print("Prompt cannot be empty") if no_rich else common.console.print("[red]Prompt cannot be empty[/red]")
        return common.EXIT_USAGE_ERROR
    return cmd_run(resolved_prompt, max_iter, json_mode=json_mode, no_rich=no_rich)

_PROPOSAL_TOOL_NAME = "propose_mandate_profiles"
_PROPOSAL_ID_RE = common.re.compile(r'"proposal_id"\s*:\s*"(mp_[0-9a-f]{32})"')
_SCHEDULED_PROPOSAL_TOOL_NAME = "scheduled_research"
_SCHEDULED_PROPOSAL_ID_RE = common.re.compile(
    r'"proposal_id"\s*:\s*"(srp_[0-9a-f]{32})"'
)
