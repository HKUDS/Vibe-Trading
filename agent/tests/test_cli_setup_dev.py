"""Unit tests for the cross-platform `vibe-trading setup` and
`vibe-trading dev` commands.

These tests cover the entrypoint and platform-aware build-command
selection. They do not actually invoke ``npm`` (we mock ``shutil.which``
and ``subprocess.run``), so they run in any environment.
"""

from __future__ import annotations

import cli.commands.common as _cmd_common
import cli.commands.setup_memory as _cmd_setup_memory

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestIsWindows:
    def test_true_on_win32(self) -> None:
        with patch.object(_cmd_common.sys, "platform", "win32"):
            assert _cmd_setup_memory._is_windows() is True

    def test_false_on_linux(self) -> None:
        with patch.object(_cmd_common.sys, "platform", "linux"):
            assert _cmd_setup_memory._is_windows() is False

    def test_false_on_darwin(self) -> None:
        with patch.object(_cmd_common.sys, "platform", "darwin"):
            assert _cmd_setup_memory._is_windows() is False


class TestBuildFrontendCmd:
    """The Windows sequence must use ``npm exec --package=...`` to avoid
    npx pulling the abandoned ``tsc@2.0.4`` package from the registry."""

    def test_windows_pins_typescript_and_vite_packages(self) -> None:
        with patch.object(_cmd_common.sys, "platform", "win32"):
            steps = _cmd_setup_memory._build_frontend_cmd(Path("frontend"))
        # First step is always `npm install`.
        assert steps[0][:1] == ["npm"]
        assert steps[0][1] == "install"
        # Subsequent steps must pin --package= so npx/npm exec cannot
        # accidentally fetch the abandoned `tsc` package.
        assert any(
            "--package=typescript" in step and "tsc" in step for step in steps[1:]
        ), f"expected an explicit typescript pin, got: {steps[1:]}"
        assert any(
            "--package=vite" in step and "vite" in step and "build" in step
            for step in steps[1:]
        ), f"expected an explicit vite build pin, got: {steps[1:]}"

    def test_posix_uses_npm_run_build(self) -> None:
        with patch.object(_cmd_common.sys, "platform", "linux"):
            steps = _cmd_setup_memory._build_frontend_cmd(Path("frontend"))
        assert steps[-1] == ["npm", "run", "build"]

    def test_posix_does_not_pin_packages(self) -> None:
        """On POSIX, npm's local PATH magic makes ``npm run build`` work
        without explicit package pinning. Keep it that way."""
        with patch.object(_cmd_common.sys, "platform", "linux"):
            steps = _cmd_setup_memory._build_frontend_cmd(Path("frontend"))
        for step in steps:
            assert "--package=" not in step, f"unexpected pin on POSIX: {step}"


class TestCmdSetupNodeMissing:
    """When node or npm is not on PATH we should fail fast with a clear
    message and the USAGE exit code, instead of letting the user see a
    raw ENOENT from npm."""

    def test_fails_when_node_missing(self, tmp_path: Path, capsys) -> None:
        # Build a fake frontend dir so the directory check passes.
        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()

        with patch.object(_cmd_setup_memory, "_resolve_node_and_npm", return_value=(None, "/usr/bin/npm")):
            rc = _cmd_setup_memory.cmd_setup(frontend_dir=frontend_dir)
        assert rc == _cmd_common.EXIT_USAGE_ERROR
        out = capsys.readouterr().out
        assert "node" in out

    def test_fails_when_npm_missing(self, tmp_path: Path, capsys) -> None:
        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()

        with patch.object(_cmd_setup_memory, "_resolve_node_and_npm", return_value=("/usr/bin/node", None)):
            rc = _cmd_setup_memory.cmd_setup(frontend_dir=frontend_dir)
        assert rc == _cmd_common.EXIT_USAGE_ERROR
        out = capsys.readouterr().out
        assert "npm" in out

    def test_fails_when_frontend_dir_missing(self, tmp_path: Path, capsys) -> None:
        missing = tmp_path / "no-such-frontend"
        with patch.object(_cmd_setup_memory, "_resolve_node_and_npm", return_value=("/usr/bin/node", "/usr/bin/npm")):
            rc = _cmd_setup_memory.cmd_setup(frontend_dir=missing)
        assert rc == _cmd_common.EXIT_USAGE_ERROR
        out = capsys.readouterr().out
        assert "not found" in out.lower() or "not on PATH" in out


class TestCmdSetupRunsSteps:
    """When Node and the frontend dir are present, cmd_setup should
    invoke the right number of steps in order and return success."""

    def test_runs_all_steps(self, tmp_path: Path) -> None:
        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()
        (frontend_dir / "dist").mkdir()  # simulate a build output

        with patch.object(_cmd_setup_memory, "_resolve_node_and_npm", return_value=("/usr/bin/node", "/usr/bin/npm")):
            with patch.object(_cmd_setup_memory, "_is_windows", return_value=False):
                with patch('cli.commands.common.subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                    rc = _cmd_setup_memory.cmd_setup(frontend_dir=frontend_dir)

        assert rc == _cmd_common.EXIT_SUCCESS
        # On POSIX: exactly 2 steps (install + run build).
        assert mock_run.call_count == 2
        # The last invocation should be `npm run build`.
        last_cmd = mock_run.call_args_list[-1].args[0]
        assert last_cmd[:3] == ["npm", "run", "build"]

    def test_returns_run_failed_when_step_fails(self, tmp_path: Path) -> None:
        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()

        with patch.object(_cmd_setup_memory, "_resolve_node_and_npm", return_value=("/usr/bin/node", "/usr/bin/npm")):
            with patch.object(_cmd_setup_memory, "_is_windows", return_value=False):
                with patch('cli.commands.common.subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=1, stdout="", stderr="boom: failed"
                    )
                    rc = _cmd_setup_memory.cmd_setup(frontend_dir=frontend_dir)

        assert rc == _cmd_common.EXIT_RUN_FAILED
        # Should bail out on the first failing step, not run them all.
        assert mock_run.call_count == 1


class TestCmdDev:
    """`vibe-trading dev` should use vite.config.ts's port (5899), not
    5173, and launch the backend from AGENT_DIR so the in-repo `cli`
    package is importable."""

    def test_default_frontend_port_is_5899(self, tmp_path: Path) -> None:
        """Hardcoded wrong-port regression: this is the value users see
        in the banner. Vite config sets 5899; we must not print 5173."""
        # We don't actually run the command (it never returns), just
        # inspect the documented default by calling the function with
        # patched subprocess that raises immediately.
        # We must fabricate node_modules/.bin/vite so the pre-check in
        # cmd_dev does not bail out with USAGE_ERROR before Popen runs.
        frontend_dir = _make_frontend_with_vite(tmp_path)
        with patch('cli.commands.setup_memory._resolve_node_and_npm', return_value=("/usr/bin/node", "/usr/bin/npm")):
            with patch('cli.commands.common.subprocess.Popen') as mock_popen:
                # Both children "exit" immediately so the wait loop ends.
                proc = MagicMock()
                proc.poll.return_value = 0
                mock_popen.return_value = proc
                with patch.object(_cmd_common.time, "sleep", side_effect=KeyboardInterrupt):
                    rc = _cmd_setup_memory.cmd_dev(frontend_dir=frontend_dir)

        # First Popen call: backend. Second: frontend.
        backend_call = mock_popen.call_args_list[0]
        frontend_call = mock_popen.call_args_list[1]
        backend_cmd = backend_call.args[0]
        frontend_cmd = frontend_call.args[0]
        # Backend must run from AGENT_DIR, not the repo root.
        assert backend_call.kwargs.get("cwd") == str(_cmd_common.AGENT_DIR)
        # Backend invocation must be `python -m cli serve`.
        assert backend_cmd[:4] == [sys.executable, "-m", "cli", "serve"]
        # Frontend invocation must pass the configured vite port (5899 by
        # default; --port 5173 would be a bug).
        assert "--port" in frontend_cmd
        port_idx = frontend_cmd.index("--port") + 1
        assert frontend_cmd[port_idx] == "5899", (
            f"dev printed wrong frontend port; got {frontend_cmd[port_idx]!r}, expected '5899'"
        )
        # Process should have returned cleanly.
        assert rc == _cmd_common.EXIT_SUCCESS

    def test_custom_frontend_port_propagates(self, tmp_path: Path) -> None:
        frontend_dir = _make_frontend_with_vite(tmp_path)
        with patch('cli.commands.setup_memory._resolve_node_and_npm', return_value=("/usr/bin/node", "/usr/bin/npm")):
            with patch('cli.commands.common.subprocess.Popen') as mock_popen:
                proc = MagicMock()
                proc.poll.return_value = 0
                mock_popen.return_value = proc
                with patch.object(_cmd_common.time, "sleep", side_effect=KeyboardInterrupt):
                    _cmd_setup_memory.cmd_dev(frontend_port=6000, frontend_dir=frontend_dir)

        frontend_call = mock_popen.call_args_list[1]
        frontend_cmd = frontend_call.args[0]
        port_idx = frontend_cmd.index("--port") + 1
        assert frontend_cmd[port_idx] == "6000"

    @pytest.mark.parametrize(
        ("backend_code", "frontend_code", "expected"),
        [(7, None, 7), (None, 9, 9)],
    )
    def test_returns_first_child_failure_and_stops_sibling(
        self,
        tmp_path: Path,
        backend_code: int | None,
        frontend_code: int | None,
        expected: int,
    ) -> None:
        frontend_dir = _make_frontend_with_vite(tmp_path)
        backend = MagicMock()
        backend.poll.return_value = backend_code
        frontend = MagicMock()
        frontend.poll.return_value = frontend_code

        with patch(
            'cli.commands.setup_memory._resolve_node_and_npm',
            return_value=("/usr/bin/node", "/usr/bin/npm"),
        ):
            with patch('cli.commands.common.subprocess.Popen', side_effect=[backend, frontend]):
                with patch.object(_cmd_common.time, "sleep", return_value=None):
                    rc = _cmd_setup_memory.cmd_dev(frontend_dir=frontend_dir)

        assert rc == expected
        running_sibling = frontend if backend_code is not None else backend
        running_sibling.terminate.assert_called_once()

    def test_second_spawn_failure_cleans_up_backend(self, tmp_path: Path) -> None:
        frontend_dir = _make_frontend_with_vite(tmp_path)
        backend = MagicMock()
        backend.poll.return_value = None

        with patch(
            'cli.commands.setup_memory._resolve_node_and_npm',
            return_value=("/usr/bin/node", "/usr/bin/npm"),
        ):
            with patch(
                'cli.commands.common.subprocess.Popen',
                side_effect=[backend, OSError("frontend failed to start")],
            ):
                rc = _cmd_setup_memory.cmd_dev(frontend_dir=frontend_dir)

        assert rc == _cmd_common.EXIT_RUN_FAILED
        backend.terminate.assert_called_once()
        backend.wait.assert_called_once()

    def test_interrupt_cleans_up_both_children(self, tmp_path: Path) -> None:
        frontend_dir = _make_frontend_with_vite(tmp_path)
        backend = MagicMock()
        backend.poll.return_value = None
        frontend = MagicMock()
        frontend.poll.return_value = None

        with patch(
            'cli.commands.setup_memory._resolve_node_and_npm',
            return_value=("/usr/bin/node", "/usr/bin/npm"),
        ):
            with patch('cli.commands.common.subprocess.Popen', side_effect=[backend, frontend]):
                with patch.object(
                    _cmd_common.time, "sleep", side_effect=KeyboardInterrupt
                ):
                    rc = _cmd_setup_memory.cmd_dev(frontend_dir=frontend_dir)

        assert rc == _cmd_common.EXIT_SUCCESS
        backend.terminate.assert_called_once()
        frontend.terminate.assert_called_once()
        backend.wait.assert_called_once()
        frontend.wait.assert_called_once()


def _make_frontend_with_vite(tmp_path: Path) -> Path:
    """Create a fake frontend directory with a placeholder Vite binary so
    that ``cmd_dev``'s pre-flight check (``node_modules/.bin/vite``) passes
    during unit tests. We don't actually invoke the binary."""
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    is_windows = sys.platform == "win32"
    bin_dir = frontend_dir / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    vite_name = "vite.cmd" if is_windows else "vite"
    (bin_dir / vite_name).write_text("")  # touch
    return frontend_dir
