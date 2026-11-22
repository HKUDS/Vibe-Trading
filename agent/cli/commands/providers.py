"""CLI providers commands and their helpers."""
from __future__ import annotations

from cli.commands import common
from cli.commands import execution
from cli.commands import inspection

def _provider_key_env(provider: str | None) -> str | None:
    """Return the credential environment variable for a provider."""
    return {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "nvidia-nim": "NVIDIA_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "novita": "NOVITA_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "zhipu": "ZHIPU_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "mimo": "MIMO_API_KEY",
        "spark": "SPARK_API_KEY",
        "iflytek": "SPARK_API_KEY",
        "zai": "ZAI_API_KEY",
        "modelscope": "MODELSCOPE_API_KEY",
    }.get((provider or "").lower())


def _provider_base_env(provider: str | None) -> str | None:
    """Return the base URL environment variable for a provider."""
    return {
        "openrouter": "OPENROUTER_BASE_URL",
        "openai": "OPENAI_BASE_URL",
        "openai-codex": "OPENAI_CODEX_BASE_URL",
        "deepseek": "DEEPSEEK_BASE_URL",
        "nvidia": "NVIDIA_BASE_URL",
        "nvidia-nim": "NVIDIA_BASE_URL",
        "gemini": "GEMINI_BASE_URL",
        "groq": "GROQ_BASE_URL",
        "novita": "NOVITA_BASE_URL",
        "dashscope": "DASHSCOPE_BASE_URL",
        "qwen": "DASHSCOPE_BASE_URL",
        "zhipu": "ZHIPU_BASE_URL",
        "moonshot": "MOONSHOT_BASE_URL",
        "minimax": "MINIMAX_BASE_URL",
        "mimo": "MIMO_BASE_URL",
        "spark": "SPARK_BASE_URL",
        "iflytek": "SPARK_BASE_URL",
        "zai": "ZAI_BASE_URL",
        "modelscope": "MODELSCOPE_BASE_URL",
        "ollama": "OLLAMA_BASE_URL",
    }.get((provider or "").lower())


def _show_settings() -> None:
    """Show current runtime settings."""
    execution._ensure_cli_env()
    term_width = inspection._terminal_width()
    compact = term_width < 104
    value_limit = max(18, min(56, term_width - 28))
    _cfg = common.get_env_config()
    provider = _cfg.llm.langchain_provider or "(not set)"
    model = _cfg.llm.langchain_model_name or "(not set)"
    provider_key_env = _provider_key_env(provider)
    provider_base_env = _provider_base_env(provider)
    provider_key = common.os.getenv(provider_key_env or "")  # noqa: env-gate — dynamic provider key display
    provider_base_url = common.os.getenv(provider_base_env or "") or common.os.getenv("OPENAI_BASE_URL") or common.os.getenv("OPENAI_API_BASE") or "(not set)"  # noqa: env-gate — dynamic provider URL display

    provider_table = common.Table.grid(expand=True)
    provider_table.add_column(width=12, style="dim")
    provider_table.add_column(ratio=1)
    provider_table.add_row("Provider", f"[bold]{provider}[/bold]")
    provider_table.add_row("Model", inspection._clip_inline(model, value_limit))
    provider_table.add_row("Base URL", inspection._clip_inline(provider_base_url, value_limit))

    runtime_table = common.Table.grid(expand=True)
    runtime_table.add_column(width=13, style="dim")
    runtime_table.add_column(ratio=1)
    from src.config.gildata_features import selected_features

    runtime_table.add_row("Gildata opt-ins", ", ".join(selected_features()) or "(none)")
    runtime_table.add_row("Temperature", str(_cfg.llm.langchain_temperature))
    runtime_table.add_row("Timeout", str(_cfg.llm.timeout_seconds) + "s")
    runtime_table.add_row("Retries", str(_cfg.llm.max_retries))

    credential_table = common.Table.grid(expand=True)
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
    credential_table.add_row("TUSHARE_TOKEN", "***" if _cfg.data.tushare_token else "(optional)")

    panels = [
        common.Panel(provider_table, title=f"Provider {inspection._state_badge(provider if provider != '(not set)' else None)}", border_style="cyan", padding=(0, 1)),
        common.Panel(runtime_table, title="Runtime", border_style="dim", padding=(0, 1)),
        common.Panel(credential_table, title=f"Credentials {inspection._state_badge('ok' if credential_ready else None)}", border_style="green" if credential_ready else "yellow", padding=(0, 1)),
    ]
    if compact:
        for panel in panels:
            common.console.print(panel)
    else:
        common.console.print(common.Columns(panels, expand=True, equal=True))
    common.console.print("[dim]Edit configuration in ~/.vibe-trading/.env, or run vibe-trading init.[/dim]")


def cmd_provider_login(provider: str) -> int:
    """Authenticate OAuth-backed LLM providers."""
    normalized = provider.strip().lower().replace("_", "-")
    if normalized in {"copilot", "github-copilot"}:
        return _login_copilot()
    if normalized == "claude-cli":
        return _login_claude_cli()
    if normalized != "openai-codex":
        common.console.print(
            "[red]Unknown OAuth provider.[/red] Supported: openai-codex, copilot, claude-cli"
        )
        return common.EXIT_USAGE_ERROR
    try:
        from src.providers.openai_codex import login_openai_codex

        common.console.print("[cyan]Starting OpenAI Codex OAuth login...[/cyan]\n")
        token = login_openai_codex(
            print_fn=lambda text: common.console.print(text),
            prompt_fn=lambda text: common.Prompt.ask(text),
        )
        account = getattr(token, "account_id", None) or "ChatGPT"
        common.console.print(f"[green]Authenticated with OpenAI Codex[/green]  [dim]{account}[/dim]")
        return common.EXIT_SUCCESS
    except EOFError:
        # ``docker exec`` does not allocate stdin/TTY unless explicitly asked
        # to do so. oauth-cli-kit prompts for the browser callback URL after
        # printing the authorization link, so an unattended stdin otherwise
        # fails with the opaque ``EOF when reading a line`` error.
        common.console.print(
            "[red]Authentication error:[/red] OpenAI Codex OAuth needs an "
            "interactive terminal to paste the callback URL."
        )
        common.console.print(
            "[yellow]Docker:[/yellow] run `docker compose exec vibe-trading "
            "vibe-trading provider login openai-codex` or add `-it` to "
            "`docker exec`."
        )
        return common.EXIT_RUN_FAILED
    except Exception as exc:
        common.console.print(f"[red]Authentication error:[/red] {exc}")
        return common.EXIT_RUN_FAILED


def _login_copilot() -> int:
    """Report supported GitHub Copilot SDK authentication options."""
    from src.providers.copilot_auth import get_copilot_auth_status

    authenticated, status = get_copilot_auth_status()
    if authenticated:
        common.console.print(
            f"[green]Already authenticated with GitHub Copilot[/green]  [dim]{status}[/dim]"
        )
        return common.EXIT_SUCCESS

    common.console.print(
        "[yellow]No GitHub credential found.[/yellow]\n"
        "Run [bold]copilot[/bold] and sign in, run [bold]gh auth login[/bold], "
        "or set [bold]COPILOT_GITHUB_TOKEN[/bold]."
    )
    return common.EXIT_RUN_FAILED


def _login_claude_cli() -> int:
    """Report the local Claude Code CLI login used by the claude-cli provider."""
    from src.providers.claude_cli import get_claude_cli_auth_status

    logged_in, method = get_claude_cli_auth_status()
    if logged_in:
        common.console.print(f"[green]Claude Code CLI is logged in[/green]  [dim]{method}[/dim]")
        return common.EXIT_SUCCESS

    common.console.print(
        f"[yellow]Claude Code CLI is not logged in[/yellow] ({method}).\n"
        "Run [bold]claude auth login[/bold], or set [bold]CLAUDE_CLI_PATH[/bold] "
        "to the claude executable."
    )
    return common.EXIT_RUN_FAILED


def cmd_provider_doctor() -> int:
    """Print redacted provider diagnostics."""
    from src.providers.diagnostics import provider_diagnostics

    common.console.print_json(data=provider_diagnostics())
    return common.EXIT_SUCCESS
