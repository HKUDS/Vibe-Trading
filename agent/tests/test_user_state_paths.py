"""User-level state directory resolution (issue #904).

Session/run/upload history must live under the runtime root
(``~/.vibe-trading`` by default), never relative to the installed code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.paths import get_runtime_root


def test_runtime_root_defaults_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_HOME", raising=False)

    assert get_runtime_root() == Path.home() / ".vibe-trading"


def test_runtime_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "custom-root"))

    assert get_runtime_root() == tmp_path / "custom-root"


def test_runtime_root_expands_user_in_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_HOME", "~/elsewhere")

    assert get_runtime_root() == Path.home() / "elsewhere"


def test_explicit_config_path_beats_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "custom-root"))
    config_path = tmp_path / "explicit" / "agent.json"

    assert get_runtime_root(config_path) == config_path.parent


def test_state_dir_helpers_live_under_runtime_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.config.paths import (
        get_runs_dir,
        get_sessions_dir,
        get_swarm_runs_dir,
        get_uploads_dir,
    )

    root = tmp_path / "state-root"
    monkeypatch.setenv("VIBE_TRADING_HOME", str(root))

    assert get_sessions_dir() == root / "sessions"
    assert get_runs_dir() == root / "runs"
    assert get_swarm_runs_dir() == root / "swarm" / "runs"
    assert get_uploads_dir() == root / "uploads"


def test_legacy_cli_constants_derive_from_runtime_root() -> None:
    from cli import _legacy
    from src.config import paths

    assert _legacy.SESSIONS_DIR == paths.get_sessions_dir()
    assert _legacy.RUNS_DIR == paths.get_runs_dir()
    assert _legacy.SWARM_DIR == paths.get_swarm_runs_dir()
    assert _legacy.UPLOADS_DIR == paths.get_uploads_dir()


def test_agent_loop_constants_derive_from_runtime_root() -> None:
    from src.agent import loop
    from src.config import paths

    assert loop.RUNS_DIR == paths.get_runs_dir()
    assert loop.SESSIONS_DIR == paths.get_sessions_dir()


def test_api_constants_derive_from_runtime_root() -> None:
    from src.api import helpers, uploads_routes
    from src.config import paths

    assert helpers.RUNS_DIR == paths.get_runs_dir()
    assert helpers.SESSIONS_DIR == paths.get_sessions_dir()
    assert helpers.UPLOADS_DIR == paths.get_uploads_dir()
    assert uploads_routes.UPLOADS_DIR == paths.get_uploads_dir()


def test_swarm_runs_root_derives_from_runtime_root() -> None:
    from src.config import paths
    from src.swarm.store import swarm_runs_root

    assert swarm_runs_root() == paths.get_swarm_runs_dir()


def test_trace_lookup_searches_runtime_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.agent.trace import TraceWriter

    root = tmp_path / "state-root"
    monkeypatch.setenv("VIBE_TRADING_HOME", str(root))
    trace_dir = root / "sessions" / "sess-1"
    trace_dir.mkdir(parents=True)
    (trace_dir / "trace.jsonl").write_text("", encoding="utf-8")

    assert TraceWriter.find_trace_dir("sess-1") == trace_dir


def test_upload_handle_resolves_to_runtime_uploads_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.tools.path_utils import _import_candidate

    root = tmp_path / "state-root"
    monkeypatch.setenv("VIBE_TRADING_HOME", str(root))

    assert _import_candidate("uploads/report.pdf") == root / "uploads" / "report.pdf"
    assert (
        _import_candidate("agent/uploads/report.pdf")
        == root / "uploads" / "report.pdf"
    )


def test_sandbox_roots_follow_home_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.tools.path_utils import allowed_file_roots, allowed_write_roots

    root = tmp_path / "state-root"
    monkeypatch.setenv("VIBE_TRADING_HOME", str(root))

    file_roots = allowed_file_roots()
    write_roots = allowed_write_roots()

    assert (root / "uploads").resolve() in file_roots
    assert (root / "runs").resolve() in file_roots
    assert (root / "uploads").resolve() in write_roots
    assert (root / "runs").resolve() in write_roots


def test_welcome_panel_reports_runtime_root_as_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rich.console import Console

    from cli import _legacy

    monkeypatch.setattr(_legacy, "get_runtime_root", lambda: Path("/RTROOT"))

    console = Console(width=200, record=True)
    console.print(_legacy._build_welcome_panel(term_width=120))

    assert "/RTROOT" in console.export_text()


def test_state_dir_helpers_do_not_create_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.config.paths import get_runs_dir, get_sessions_dir

    root = tmp_path / "state-root"
    monkeypatch.setenv("VIBE_TRADING_HOME", str(root))

    get_sessions_dir()
    get_runs_dir()

    assert not root.exists()
