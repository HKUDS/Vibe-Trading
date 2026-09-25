"""Regression tests for generated backtest subprocess environment handling."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.core import runner as runner_mod
from src.core.runner import (
    Runner,
    _rlimit_bootstrap_argv,
    _prepare_sandbox_home,
    _resolve_sandbox_credentials,
)


def test_backtest_runtime_env_keeps_market_data_configuration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    allowed_values = {
        "TUSHARE_TOKEN": "tushare-token",
        "FINNHUB_API_KEY": "finnhub-key",
        "ALPHAVANTAGE_API_KEY": "alpha-key",
        "TIINGO_API_KEY": "tiingo-key",
        "FMP_API_KEY": "fmp-key",
        "FRED_API_KEY": "fred-key",
        "VIBE_TRADING_IWENCAI_KEY": "iwencai-key",
        "VIBE_TRADING_SEC_UA": "Research Bot bot@example.com",
        "VIBE_TRADING_DATA_CACHE": "1",
        "VIBE_TRADING_ALLOWED_RUN_ROOTS": str(tmp_path),
        "VIBE_TRADING_FMP_MIN_INTERVAL": "0.5",
        "CCXT_EXCHANGE": "okx",
        "CCXT_TIMEOUT_MS": "12000",
        "OKX_TIMEOUT_S": "20",
        "OKX_FETCH_BUDGET_S": "90",
        "RSSHUB_BASE_URL": "https://rss.example.test",
        "RSSHUB_TIMEOUT_S": "12",
        "RSSHUB_FETCH_BUDGET_S": "45",
        "FUTU_HOST": "127.0.0.1",
        "FUTU_PORT": "11111",
        "HTTPS_PROXY": "http://proxy.example.test:8080",
        "REQUESTS_CA_BUNDLE": "/tmp/ca.pem",
        "LC_ALL": "C.UTF-8",
    }
    for key, value in allowed_values.items():
        monkeypatch.setenv(key, value)

    env = Runner(timeout=1)._build_runtime_env(tmp_path)

    for key, value in allowed_values.items():
        assert env[key] == value
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


def test_backtest_runtime_env_scrubs_service_and_broker_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sensitive_keys = [
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "LANGCHAIN_PROVIDER",
        "LANGCHAIN_MODEL_NAME",
        "API_AUTH_KEY",
        "VIBE_TRADING_API_KEY",
        "VIBE_TRADING_ENABLE_SHELL_TOOLS",
        "VIBE_TRADING_ENABLE_ADVISORY",
        "INVINOVERITAS_API_KEY",
        "FUTU_TRADE_PWD_MD5",
        "BINANCE_API_SECRET",
        "ALPACA_API_KEY",
        "LONGPORT_APP_SECRET",
        "SHOONYA_PASSWORD",
    ]
    for key in sensitive_keys:
        monkeypatch.setenv(key, f"{key.lower()}-secret")

    env = Runner(timeout=1)._build_runtime_env(tmp_path)

    for key in sensitive_keys:
        assert key not in env


def test_backtest_runtime_env_prepends_runtime_pythonpath(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "existing-path")
    pythonpath_extra = tmp_path / "agent"

    env = Runner(timeout=1)._build_runtime_env(tmp_path, pythonpath_extra=pythonpath_extra)

    assert env["PYTHONPATH"] == f"{pythonpath_extra}{os.pathsep}existing-path"


def test_backtest_runtime_env_adds_exact_current_run_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configured_root = tmp_path / "configured-runs"
    run_dir = tmp_path / "state-root" / "runs" / "run-1"
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(configured_root))

    env = Runner(timeout=1)._build_runtime_env(run_dir)

    assert env["VIBE_TRADING_ALLOWED_RUN_ROOTS"].split(",") == [
        str(configured_root),
        str(run_dir.resolve()),
    ]


@pytest.mark.parametrize("run_bucket", ("runs", "shadow_runs"))
def test_execute_keeps_runtime_run_valid_after_home_is_sandboxed(
    monkeypatch,
    tmp_path: Path,
    run_bucket: str,
) -> None:
    real_home = tmp_path / "real-home"
    run_dir = real_home / ".vibe-trading" / run_bucket / "run-1"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.delenv("VIBE_TRADING_HOME", raising=False)
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)

    entry = _probe_entry(
        tmp_path,
        "import sys\n"
        "from src.tools.path_utils import safe_run_dir\n"
        "print(safe_run_dir(sys.argv[1]))\n",
    )
    agent_root = Path(runner_mod.__file__).resolve().parents[2]

    result = Runner(timeout=60).execute(
        entry,
        run_dir,
        cwd=agent_root,
        cli_args=[str(run_dir)],
    )

    assert result.success, result.stderr
    assert str(run_dir.resolve()) in result.stdout


# --------------------------------------------------------------------------- #
# VT-001 runtime defense-in-depth: ephemeral HOME, UID-drop fallback, rlimits.
# --------------------------------------------------------------------------- #


def test_sandbox_credentials_absent_in_this_environment() -> None:
    # No vibe-sandbox account here, so the UID-drop pre-check returns None and
    # execute() must run WITHOUT a user= kwarg (the graceful fallback path).
    assert _resolve_sandbox_credentials() is None


def test_prepare_sandbox_home_reexposes_only_loader_paths(tmp_path: Path) -> None:
    real_home = tmp_path / "home"
    vt = real_home / ".vibe-trading"
    (vt / "cache").mkdir(parents=True)
    (vt / "memory").mkdir(parents=True)
    (vt / ".env").write_text("SECRET=1", encoding="utf-8")
    (vt / "qveris.json").write_text("{}", encoding="utf-8")

    sandbox = _prepare_sandbox_home(real_home)
    try:
        dst_vt = sandbox / ".vibe-trading"
        # Loader-owned paths re-exposed (symlinked)...
        assert (dst_vt / "cache").exists()
        assert (dst_vt / "qveris.json").exists()
        # ...persistent secrets/state are NOT.
        assert not (dst_vt / "memory").exists()
        assert not (dst_vt / ".env").exists()
        assert sandbox != real_home
    finally:
        import shutil

        shutil.rmtree(sandbox, ignore_errors=True)
    # Cleanup removes the ephemeral home; symlink targets (real cache) survive.
    assert not sandbox.exists()
    assert (vt / "cache").exists()


def test_prepare_sandbox_home_reexposes_mt5_config_without_credentials(tmp_path: Path) -> None:
    """The backtest sandbox must reach the already-running MT5 terminal without
    ever shipping broker credentials to strategy code (#1589).

    The full mt5.json carries login/password/server, so it can never join the
    generic re-expose list; the sandbox gets a secret-free subset
    (terminal_path, timeout) instead.
    """
    real_home = tmp_path / "home"
    vt = real_home / ".vibe-trading"
    vt.mkdir(parents=True)
    (vt / "mt5.json").write_text(
        json.dumps(
            {
                "terminal_path": "C:/MT5/terminal64.exe",
                "timeout": 60,
                "login": 12345678,
                "password": "broker-secret",
                "server": "Exness-Demo",
            }
        ),
        encoding="utf-8",
    )

    sandbox = _prepare_sandbox_home(real_home)
    try:
        sandbox_cfg = sandbox / ".vibe-trading" / "mt5.json"
        assert sandbox_cfg.exists()
        subset = json.loads(sandbox_cfg.read_text(encoding="utf-8"))
        assert subset == {"terminal_path": "C:/MT5/terminal64.exe", "timeout": 60}
        for secret in ("login", "password", "server"):
            assert secret not in subset
    finally:
        import shutil

        shutil.rmtree(sandbox, ignore_errors=True)


def test_prepare_sandbox_home_copy_fallback_when_symlink_privileges_missing(
    monkeypatch, tmp_path: Path
) -> None:
    """Windows cannot always create symlinks; the copy fallback must still work.

    On Windows, ``symlink_to`` can raise OSError 1314 (privilege not held) even
    in an otherwise healthy environment. ``_prepare_sandbox_home`` must then copy
    the loader-owned paths so the subprocess still sees them, and must still keep
    persistent secrets/state out of the ephemeral home.
    """
    real_home = tmp_path / "home"
    vt = real_home / ".vibe-trading"
    (vt / "cache").mkdir(parents=True)
    (vt / "data-bridge").mkdir(parents=True)
    (vt / "qveris.json").write_text("{}", encoding="utf-8")

    def _deny_symlink(*args, **kwargs):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(Path, "symlink_to", _deny_symlink)

    sandbox = _prepare_sandbox_home(real_home)
    try:
        dst_vt = sandbox / ".vibe-trading"
        # Symlinks were impossible, yet the loader paths are still present...
        assert (dst_vt / "cache").is_dir()
        assert (dst_vt / "data-bridge").is_dir()
        assert (dst_vt / "qveris.json").is_file()
        # ...and the persistent secrets/state are still NOT re-exposed.
        assert not (dst_vt / ".env").exists()
        assert not (dst_vt / "memory").exists()
    finally:
        import shutil

        shutil.rmtree(sandbox, ignore_errors=True)
    assert not sandbox.exists()


def test_prepare_sandbox_home_preseeds_mootdx_config(tmp_path: Path) -> None:
    sandbox = _prepare_sandbox_home(tmp_path)
    try:
        cfg = sandbox / ".mootdx" / "config.json"
        # mootdx's setup() runs `finally: load_config()`, re-reading the file
        # even after bestip(sync=False) fails to write it — the sandbox HOME
        # must ship a valid config or mootdx raises an uncaught FileNotFoundError.
        assert cfg.exists()
        import json

        assert isinstance(json.loads(cfg.read_text(encoding="utf-8")), dict)
    finally:
        import shutil

        shutil.rmtree(sandbox, ignore_errors=True)


def test_rlimit_bootstrap_argv_shape_on_posix() -> None:
    # Structural check only; test_execute_applies_address_space_rlimit below
    # proves the ceiling really lands, end-to-end through a real exec.
    argv = _rlimit_bootstrap_argv()
    if runner_mod.resource is None:
        assert argv is None
        return
    assert argv[0] == "-c"
    assert argv[1] == runner_mod._SANDBOX_RLIMIT_BOOTSTRAP
    # The two ceilings are resolved in the parent and passed as literal argv,
    # so the child never re-parses the env.
    assert int(argv[2]) == runner_mod._rlimit_as_bytes()
    assert int(argv[3]) == runner_mod._SANDBOX_RLIMIT_NOFILE


def test_rlimit_bootstrap_is_valid_python() -> None:
    import ast

    ast.parse(runner_mod._SANDBOX_RLIMIT_BOOTSTRAP)


def test_execute_never_passes_preexec_fn(monkeypatch, tmp_path: Path) -> None:
    """#1355: preexec_fn runs Python bytecode in the forked child of a
    multi-threaded parent (``vibe-trading serve``), which POSIX leaves
    undefined and which SIGSEGVs on aarch64/glibc 2.34. The rlimit ceiling must
    reach the child through the exec'd bootstrap instead, never through a fork
    callback."""
    seen: list[dict] = []
    real_run = runner_mod.subprocess.run

    def _spy_run(cmd, **kwargs):
        seen.append({"cmd": list(cmd), "kwargs": dict(kwargs)})
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(runner_mod.subprocess, "run", _spy_run)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry = _probe_entry(tmp_path, "print('no-preexec')\n")

    result = Runner(timeout=60).execute(entry, run_dir, cwd=tmp_path)

    assert result.success, result.stderr
    assert "no-preexec" in result.stdout
    assert seen, "subprocess.run was never called"
    assert all("preexec_fn" not in call["kwargs"] for call in seen)
    if runner_mod.resource is not None:
        # ...and the ceiling is genuinely still requested, so a future patch
        # cannot satisfy this test by simply dropping the sandbox limits.
        launch = seen[-1]["cmd"]
        assert "-c" in launch
        assert launch[launch.index("-c") + 1] == runner_mod._SANDBOX_RLIMIT_BOOTSTRAP


def test_execute_bootstrap_preserves_argv_and_script_dir(tmp_path: Path) -> None:
    # The -c wrapper must be transparent to the entry script: argv[0] is the
    # script, argv[1:] are the caller's cli_args, __name__ is "__main__", and
    # the script's own directory is importable exactly as with `python x.py`.
    # The script lives in its OWN directory, NOT in cwd — otherwise the `-c`
    # interpreter already has cwd on sys.path and the sibling import would
    # succeed even if the bootstrap never added the script dir at all.
    script_dir = tmp_path / "strategy"
    script_dir.mkdir()
    (script_dir / "sibling_mod.py").write_text(
        "VALUE = 'imported-from-script-dir'\n", encoding="utf-8"
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry = _probe_entry(
        script_dir,
        "import sys\n"
        "import sibling_mod\n"
        "print('name=' + __name__)\n"
        "print('argv0=' + sys.argv[0])\n"
        "print('rest=' + ','.join(sys.argv[1:]))\n"
        "print('sibling=' + sibling_mod.VALUE)\n",
    )

    result = Runner(timeout=60).execute(
        entry, run_dir, cwd=tmp_path, cli_args=["--alpha", "7"]
    )

    assert result.success, result.stderr
    out = result.stdout
    assert "name=__main__" in out
    assert f"argv0={entry}" in out
    assert "rest=--alpha,7" in out
    assert "sibling=imported-from-script-dir" in out


def test_execute_bootstrap_propagates_nonzero_exit(tmp_path: Path) -> None:
    # A failing strategy must still surface its own exit code and traceback,
    # not be swallowed or remapped by the bootstrap.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry = _probe_entry(tmp_path, "import sys\nsys.exit(3)\n")

    result = Runner(timeout=60).execute(entry, run_dir, cwd=tmp_path)

    assert not result.success
    assert result.exit_code == 3


def test_rlimit_as_bytes_respects_env_override(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_SANDBOX_RLIMIT_AS_MB", "256")
    assert runner_mod._rlimit_as_bytes() == 256 * 1024 * 1024


def test_rlimit_as_bytes_falls_back_on_invalid_env(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_SANDBOX_RLIMIT_AS_MB", "not-a-number")
    assert runner_mod._rlimit_as_bytes() == runner_mod._DEFAULT_RLIMIT_AS_MB * 1024 * 1024


def _probe_entry(tmp_path: Path, body: str) -> Path:
    entry = tmp_path / "probe.py"
    entry.write_text(body, encoding="utf-8")
    return entry


def test_execute_uses_ephemeral_home_and_cleans_up(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry = _probe_entry(
        tmp_path,
        "import os, sys\nsys.stdout.write(os.environ.get('HOME', '') + '\\n')\n",
    )

    result = Runner(timeout=60).execute(entry, run_dir, cwd=tmp_path)

    assert result.success, result.stderr
    home_line = result.stdout.strip()
    # The subprocess saw an ephemeral HOME, not the real one...
    assert "vibe-sandbox-home-" in home_line
    # ...and it was cleaned up after the process exited.
    assert not Path(home_line).exists()


def test_execute_falls_back_without_uid_drop_and_succeeds(tmp_path: Path) -> None:
    # With no vibe-sandbox user, execute() must NOT pass user=/group= and must
    # complete normally — this is the path that fires in CI / dev / non-Docker.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry = _probe_entry(tmp_path, "print('ran-without-uid-drop')\n")

    result = Runner(timeout=60).execute(entry, run_dir, cwd=tmp_path)

    assert result.success, result.stderr
    assert "ran-without-uid-drop" in result.stdout


def test_execute_retries_without_uid_drop_when_drop_fails(
    monkeypatch, tmp_path: Path
) -> None:
    # Simulate a host where vibe-sandbox exists but the drop is not permitted:
    # execute() must catch the failure, warn, and re-run without user=/group=.
    monkeypatch.setattr(
        runner_mod,
        "_resolve_sandbox_credentials",
        lambda: ("vibe-sandbox", "vibe-sandbox"),
    )
    real_run = runner_mod.subprocess.run
    attempts: list[bool] = []

    def _fake_run(cmd, **kwargs):
        used_user = "user" in kwargs
        attempts.append(used_user)
        if used_user:
            raise PermissionError("Operation not permitted")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(runner_mod.subprocess, "run", _fake_run)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry = _probe_entry(tmp_path, "print('after-fallback')\n")

    result = Runner(timeout=60).execute(entry, run_dir, cwd=tmp_path)

    # The interpreter-readiness probe also calls subprocess.run (never with a
    # UID drop); what matters is the execute() call itself: drop attempted, then
    # retried without it.
    assert attempts[-2:] == [True, False]
    assert attempts.count(True) == 1
    assert result.success, result.stderr
    assert "after-fallback" in result.stdout


@pytest.mark.skipif(runner_mod.resource is None, reason="POSIX resource module required")
def test_execute_applies_address_space_rlimit(monkeypatch, tmp_path: Path) -> None:
    # Prove the exec'd bootstrap actually applied the limits by reading back
    # RLIMIT_NOFILE (RLIMIT_AS is a no-op on macOS but NOFILE is portable).
    import resource as _resource

    _soft, hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
    expected = 512 if hard == _resource.RLIM_INFINITY else min(512, hard)

    monkeypatch.setenv("VIBE_TRADING_SANDBOX_RLIMIT_AS_MB", "4096")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry = _probe_entry(
        tmp_path,
        "import resource\n"
        "print(resource.getrlimit(resource.RLIMIT_NOFILE)[0])\n",
    )

    result = Runner(timeout=60).execute(entry, run_dir, cwd=tmp_path)

    assert result.success, result.stderr
    assert result.stdout.strip().splitlines()[-1] == str(expected)
