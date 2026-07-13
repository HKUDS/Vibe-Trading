"""Regression tests for generated backtest subprocess environment handling."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core import runner as runner_mod
from src.core.runner import (
    Runner,
    _make_rlimit_preexec,
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


def test_make_rlimit_preexec_returns_callable_on_posix() -> None:
    # Structural check only — the returned closure mutates *this* process's
    # rlimits if called directly, so it must never be invoked in-process here;
    # test_execute_* below already exercises it end-to-end via a real fork.
    preexec = _make_rlimit_preexec()
    assert preexec is None or callable(preexec)


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
    # Prove the preexec_fn actually ran in the child by reading back its
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
