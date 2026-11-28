from __future__ import annotations

import cli.commands.common as _cmd_common
import cli.commands.providers as _cmd_providers

from unittest.mock import patch



def test_provider_login_explains_docker_tty_requirement(capsys) -> None:
    """An EOF from the OAuth prompt should point Docker users to a TTY command."""

    with patch(
        "src.providers.openai_codex.login_openai_codex",
        side_effect=EOFError("EOF when reading a line"),
    ):
        result = _cmd_providers.cmd_provider_login("openai-codex")

    assert result == _cmd_common.EXIT_RUN_FAILED
    output = capsys.readouterr().out
    assert "interactive terminal" in output
    assert "docker compose exec vibe-trading" in output
    assert "-it" in output
