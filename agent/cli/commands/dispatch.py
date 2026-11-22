"""CLI dispatch commands and their helpers."""
from __future__ import annotations

from cli.commands import channels
from cli.commands import common
from cli.commands import connectors
from cli.commands import data
from cli.commands import execution
from cli.commands import inspection
from cli.commands import parser as command_parser
from cli.commands import portfolio
from cli.commands import providers
from cli.commands import sessions
from cli.commands import setup_memory
from cli.commands import swarm_runtime

def serve_main(argv: list[str] | None = None) -> int:
    """Delegate server startup to api_server."""
    from api_server import serve_main as api_serve_main

    return api_serve_main(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint returning a process exit code."""
    raw_argv = list(common.sys.argv[1:] if argv is None else argv)
    parser = command_parser.build_parser()
    try:
        args = parser.parse_args(raw_argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else common.EXIT_USAGE_ERROR
    if not common.sys.stdout.isatty():
        args.no_rich = True
        if hasattr(args, "run_no_rich"):
            args.run_no_rich = True

    if args.command == "init":
        return setup_memory.cmd_init()
    if args.command == "setup":
        return execution._coerce_exit_code(
            setup_memory.cmd_setup(frontend_dir=common.Path(args.frontend_dir))
        )
    if args.command == "dev":
        return execution._coerce_exit_code(
            setup_memory.cmd_dev(
                backend_port=args.port,
                frontend_port=args.frontend_port,
                frontend_dir=common.Path(args.frontend_dir),
            )
        )
    if args.command == "serve":
        return serve_main(raw_argv[1:])
    if args.command == "office":
        from src.pixel_agents.cli import main as office_main
        office_main(args.office_args)
        return 0
    if args.command == "provider":
        if args.provider_command == "login":
            return providers.cmd_provider_login(args.provider)
        if args.provider_command == "list":
            from src.providers.registry import provider_catalog as catalog

            common.console.print_json(data=catalog())
            return common.EXIT_SUCCESS
        if args.provider_command == "doctor":
            return providers.cmd_provider_doctor()
        if args.provider_command == "custom":
            from cli.custom_providers import run as run_custom_providers
            return run_custom_providers(args)
        common.console.print("[red]provider requires a subcommand.[/red] Try: vibe-trading provider doctor")
        return common.EXIT_USAGE_ERROR
    if args.command == "channels":
        return execution._coerce_exit_code(channels._dispatch_channels(args))
    if args.command == "data":
        if args.data_command == "scan":
            from src.data_gateway.__main__ import run_scan
            return run_scan(args)
        if args.data_command == "history":
            from src.data_gateway.__main__ import run_history
            try:
                run_history(args)
                return 0
            except SystemExit as exc:
                return int(exc.code) if isinstance(exc.code, int) else common.EXIT_USAGE_ERROR
        return execution._coerce_exit_code(data._dispatch_data(args))
    if args.command == "run":
        return execution._handle_prompt_command(
            args.run_prompt,
            args.run_prompt_file,
            max_iter=args.run_max_iter,
            json_mode=args.run_json,
            no_rich=args.run_no_rich,
        )
    if args.command == "list":
        return execution._coerce_exit_code(inspection.cmd_list(args.list_limit))
    if args.command == "show":
        return execution._coerce_exit_code(inspection.cmd_show(args.run_id))
    if args.command == "chat":
        from cli.main import _interactive_loop

        return execution._coerce_exit_code(_interactive_loop(args.chat_max_iter))
    if args.command == "update":
        from cli.commands.update import cmd_update

        return execution._coerce_exit_code(cmd_update())
    if args.command == "alpha":
        from src.factors.cli_handlers import dispatch as _alpha_dispatch
        return execution._coerce_exit_code(_alpha_dispatch(args))
    if args.command == "hypothesis":
        from src.hypotheses.cli_handlers import dispatch as _hyp_dispatch
        return execution._coerce_exit_code(_hyp_dispatch(args))
    if args.command == "research-artifact":
        from src.research_artifacts.cli_handlers import dispatch as _research_artifact_dispatch
        return execution._coerce_exit_code(_research_artifact_dispatch(args))
    if args.command == "research-lab":
        from src.research_lab.cli import dispatch as _research_lab_dispatch
        return execution._coerce_exit_code(_research_lab_dispatch(args))
    if args.command == "playbook":
        from cli.commands.research_playbook import dispatch as _playbook_dispatch
        return execution._coerce_exit_code(_playbook_dispatch(args))
    if args.command == "strategy-evidence":
        from cli.commands.strategy_evidence import dispatch as _strategy_evidence_dispatch
        return execution._coerce_exit_code(_strategy_evidence_dispatch(args))
    if args.command == "paper":
        from cli.commands.paper_trade import dispatch as dispatch_paper
        return dispatch_paper(args)
    if args.command == "portfolio":
        return execution._coerce_exit_code(portfolio._dispatch_portfolio(args))
    if args.command == "connector":
        return execution._coerce_exit_code(connectors._dispatch_connector(args))
    if args.command == "memory":
        if args.memory_command == "list":
            return execution._coerce_exit_code(setup_memory.cmd_memory_list(args.memory_type))
        if args.memory_command == "show":
            return execution._coerce_exit_code(setup_memory.cmd_memory_show(args.name))
        if args.memory_command == "search":
            return execution._coerce_exit_code(setup_memory.cmd_memory_search(args.query, args.memory_limit))
        if args.memory_command == "forget":
            return execution._coerce_exit_code(setup_memory.cmd_memory_forget(args.name, yes=args.yes))
        common.console.print("[red]memory requires a subcommand.[/red] Try: vibe-trading memory list")
        return common.EXIT_USAGE_ERROR

    if args.list:
        return execution._coerce_exit_code(inspection.cmd_list())
    if args.show:
        return execution._coerce_exit_code(inspection.cmd_show(args.show))
    if args.code:
        return execution._coerce_exit_code(inspection.cmd_code(args.code))
    if args.pine:
        return execution._coerce_exit_code(inspection.cmd_pine(args.pine))
    if args.trace:
        return execution._coerce_exit_code(inspection.cmd_trace(args.trace))
    if args.skills:
        return execution._coerce_exit_code(inspection.cmd_skills())

    if args.swarm_presets:
        return execution._coerce_exit_code(swarm_runtime.cmd_swarm_presets())
    if args.swarm_inspect:
        return execution._coerce_exit_code(swarm_runtime.cmd_swarm_inspect(args.swarm_inspect))
    if args.swarm_run:
        parsed_swarm_run = swarm_runtime._parse_swarm_run_args(args.swarm_run)
        if parsed_swarm_run is None:
            return common.EXIT_USAGE_ERROR
        preset_name, vars_json = parsed_swarm_run
        return execution._coerce_exit_code(swarm_runtime.cmd_swarm_run_live(preset_name, vars_json))
    if args.swarm_list:
        return execution._coerce_exit_code(swarm_runtime.cmd_swarm_list())
    if args.swarm_show:
        return execution._coerce_exit_code(swarm_runtime.cmd_swarm_show(args.swarm_show))
    if args.swarm_cancel:
        return execution._coerce_exit_code(swarm_runtime.cmd_swarm_cancel(args.swarm_cancel))
    if args.swarm_retry:
        return execution._coerce_exit_code(swarm_runtime.cmd_swarm_retry_live(args.swarm_retry, resume=args.swarm_resume))
    if args.swarm_resume:
        common.console.print("[red]--swarm-resume requires --swarm-retry RUN_ID[/red]")
        return common.EXIT_USAGE_ERROR

    if args.sessions:
        return execution._coerce_exit_code(sessions.cmd_sessions())
    if args.command == "sessions" and args.sessions_command == "migrate":
        return execution._coerce_exit_code(sessions.cmd_migrate_sessions())
    if args.session_chat:
        return execution._coerce_exit_code(sessions.cmd_session_chat(args.session_chat, args.max_iter))
    if args.upload:
        return execution._coerce_exit_code(sessions.cmd_upload(args.upload))
    if args.chat:
        from cli.main import _interactive_loop

        return execution._coerce_exit_code(_interactive_loop(args.max_iter))
    if args.cont:
        return execution._coerce_exit_code(execution.cmd_continue(args.cont[0], args.cont[1], args.max_iter, json_mode=args.json, no_rich=args.no_rich))

    # No flags and no subcommand: check for a prompt, otherwise enter interactive mode.
    if args.prompt or args.prompt_file or not common.sys.stdin.isatty():
        return execution._handle_prompt_command(
            args.prompt,
            args.prompt_file,
            max_iter=args.max_iter,
            json_mode=args.json,
            no_rich=args.no_rich,
        )

    # Default: interactive mode
    from cli.main import _interactive_loop

    return execution._coerce_exit_code(_interactive_loop(args.max_iter))
