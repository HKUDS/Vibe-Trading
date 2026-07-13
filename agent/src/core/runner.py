"""Runner module for executing generated backtest code and collecting artifacts."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rich.console import Console

try:  # POSIX-only; absent on Windows
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

try:  # POSIX-only; absent on Windows
    import pwd
except ImportError:  # pragma: no cover - Windows
    pwd = None  # type: ignore[assignment]


console = Console(stderr=True)
logger = logging.getLogger(__name__)

# --- Sandbox subprocess hardening (VT-001 defense-in-depth) ---------------
# These layers only bite inside the hardened Docker deployment; everywhere else
# (bare pip install, local dev, CI, non-Linux) they detect the missing
# precondition and degrade to the previous behaviour with a WARNING. The
# always-on control for VT-001 is the AST scrubber in backtest/runner.py, not
# any of this.
_SANDBOX_USER = "vibe-sandbox"
# The only paths under ~/.vibe-trading re-exposed into the ephemeral sandbox
# HOME. Data loaders that run in the same subprocess resolve these via
# Path.home(); everything else in the real home (.env, sessions.db, memory/,
# live/ mandate+audit ledger, shadow_*, dotfiles) stays unreadable to generated
# strategy code — that broad read access was the VT-001 exposure.
_SANDBOX_HOME_REEXPOSE = ("cache", "data-bridge", "qveris.json")
# RLIMIT_AS caps *virtual* address space (mmap included). numpy/BLAS reserve
# multi-GB virtual regions that are never resident, so a 2 GB cap spuriously
# OOMs legitimate backtests; 4 GB keeps a DoS ceiling without false failures.
# Operator-tunable for large minute-level runs.
_DEFAULT_RLIMIT_AS_MB = 4096
_SANDBOX_RLIMIT_AS_MB_ENV = "VIBE_TRADING_SANDBOX_RLIMIT_AS_MB"
_SANDBOX_RLIMIT_NOFILE = 512


def _resolve_sandbox_credentials() -> tuple[str, str] | None:
    """Return ``(user, group)`` for the privilege-dropped subprocess, else None.

    None (run without a UID drop) is returned whenever the ``vibe-sandbox``
    account is absent or the platform has no ``pwd`` module — i.e. every
    environment except the hardened Docker image that pre-creates the account and
    is granted CAP_SETUID/CAP_SETGID. A user that exists but cannot actually be
    dropped to (no capability) is handled at the ``subprocess.run`` call site.
    """
    if pwd is None:
        return None
    try:
        pwd.getpwnam(_SANDBOX_USER)
    except (KeyError, OSError):
        return None
    return (_SANDBOX_USER, _SANDBOX_USER)


def _rlimit_as_bytes() -> int:
    """Return the configured RLIMIT_AS ceiling in bytes."""
    raw = os.environ.get(_SANDBOX_RLIMIT_AS_MB_ENV, "")  # noqa: env-gate — sandbox rlimit tuning, not app config
    try:
        mb = int(raw) if raw.strip() else _DEFAULT_RLIMIT_AS_MB
    except ValueError:
        mb = _DEFAULT_RLIMIT_AS_MB
    if mb <= 0:
        mb = _DEFAULT_RLIMIT_AS_MB
    return mb * 1024 * 1024


def _make_rlimit_preexec() -> Callable[[], None] | None:
    """Build a POSIX ``preexec_fn`` that caps subprocess address space + fds.

    Returns None on Windows (no ``resource`` module). The closure runs in the
    forked child after any UID drop; lowering rlimits is always permitted for an
    unprivileged process, and each limit is applied best-effort so a hardened
    parent limit already below the target is never raised.
    """
    if resource is None:
        return None

    as_bytes = _rlimit_as_bytes()

    def _apply_limits() -> None:  # pragma: no cover - runs in forked child
        for res, target in (
            (resource.RLIMIT_AS, as_bytes),
            (resource.RLIMIT_NOFILE, _SANDBOX_RLIMIT_NOFILE),
        ):
            try:
                _soft, hard = resource.getrlimit(res)
                new_hard = target if hard == resource.RLIM_INFINITY else min(target, hard)
                resource.setrlimit(res, (min(target, new_hard), new_hard))
            except (ValueError, OSError):
                pass

    return _apply_limits


def _prepare_sandbox_home(real_home: Path | None) -> Path:
    """Create an ephemeral HOME and symlink in only the loader-owned paths.

    The generated strategy runs in the same subprocess as the data loaders, so
    the ephemeral home re-exposes the narrow set of ``~/.vibe-trading`` paths the
    loaders need (opt-in cache, local data-bridge config, qveris config) and
    nothing else. Symlinks are used so the opt-in loader cache still persists
    across runs; ``shutil.rmtree`` later removes the links, never their targets.
    """
    sandbox = Path(tempfile.mkdtemp(prefix="vibe-sandbox-home-"))
    if real_home is not None:
        src_root = real_home / ".vibe-trading"
        if src_root.is_dir():
            dst_root = sandbox / ".vibe-trading"
            dst_root.mkdir(parents=True, exist_ok=True)
            for rel in _SANDBOX_HOME_REEXPOSE:
                src = src_root / rel
                if not src.exists():
                    continue
                try:
                    (dst_root / rel).symlink_to(src, target_is_directory=src.is_dir())
                except OSError:
                    # Best-effort: a loader that can't find its config just falls
                    # back to a live fetch / disabled cache — never a hard break.
                    pass
            try:
                os.chmod(dst_root, 0o755)
            except OSError:
                pass
    # mkdtemp is 0700; widen so a dropped UID can still traverse the home.
    try:
        os.chmod(sandbox, 0o755)
    except OSError:
        pass
    return sandbox


_PROXY_ENV_KEYS = frozenset(
    {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    }
)

_RUNTIME_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "USERNAME",
        "USERPROFILE",
        "SHELL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "LANG",
        "TZ",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONNOUSERSITE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "CURL_CA_BUNDLE",
        "TUSHARE_TOKEN",
        "FINNHUB_API_KEY",
        "ALPHAVANTAGE_API_KEY",
        "TIINGO_API_KEY",
        "FMP_API_KEY",
        "FRED_API_KEY",
        "VIBE_TRADING_IWENCAI_KEY",
        "VIBE_TRADING_SEC_UA",
        "VIBE_TRADING_DATA_CACHE",
        "VIBE_TRADING_ALLOWED_RUN_ROOTS",
        "CCXT_EXCHANGE",
        "CCXT_TIMEOUT_MS",
        "CCXT_FETCH_BUDGET_S",
        "OKX_TIMEOUT_S",
        "OKX_FETCH_BUDGET_S",
        "RSSHUB_BASE_URL",
        "RSSHUB_TIMEOUT_S",
        "RSSHUB_FETCH_BUDGET_S",
        "FUTU_HOST",
        "FUTU_PORT",
        "VIBE_TRADING_EASTMONEY_MIN_INTERVAL",
        "VIBE_TRADING_SINA_MIN_INTERVAL",
        "VIBE_TRADING_STOOQ_MIN_INTERVAL",
        "VIBE_TRADING_YAHOO_MIN_INTERVAL",
        "VIBE_TRADING_SEC_MIN_INTERVAL",
        "VIBE_TRADING_FINNHUB_MIN_INTERVAL",
        "VIBE_TRADING_ALPHAVANTAGE_MIN_INTERVAL",
        "VIBE_TRADING_TIINGO_MIN_INTERVAL",
        "VIBE_TRADING_FMP_MIN_INTERVAL",
        "VIBE_TRADING_FRED_MIN_INTERVAL",
        "VIBE_TRADING_IWENCAI_MIN_INTERVAL",
        "VIBE_TRADING_THS_MIN_INTERVAL",
    }
    | _PROXY_ENV_KEYS
)

_RUNTIME_ENV_PREFIXES = ("LC_",)


def _is_runtime_env_key_allowed(key: str) -> bool:
    """Return whether an environment key is safe for generated backtest code."""

    return key in _RUNTIME_ENV_KEYS or key.startswith(_RUNTIME_ENV_PREFIXES)


def _copy_runtime_env() -> dict[str, str]:
    """Copy the narrow environment needed by the backtest subprocess.

    Generated strategy code is executed in this subprocess, so avoid inheriting
    LLM, API server, broker, live-trading, or advisory credentials by default.
    The allowlist keeps OS/Python basics, proxy/cert settings, and read-only
    market-data configuration needed by the built-in loaders.
    """

    return {key: value for key, value in os.environ.items() if _is_runtime_env_key_allowed(key)}


@dataclass
class RunResult:
    """Container for runner execution outputs.

    Attributes:
        success: Whether subprocess exited with code 0.
        exit_code: Subprocess return code.
        stdout: Captured stdout text.
        stderr: Captured stderr text.
        artifacts: Existing artifact file paths keyed by artifact name.
    """

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    artifacts: dict[str, Path]


_ARTIFACTS_SPEC = {
    "defaults": {"required": ["equity", "metrics", "trades"]},
    "schemas": {
        "equity_csv": {
            "columns": [
                {"name": "timestamp", "type": "string"},
                {"name": "ret", "type": "float"},
                {"name": "equity", "type": "float"},
                {"name": "drawdown", "type": "float"},
            ],
        },
        "metrics_csv": {
            "columns": [
                {"name": "final_value", "type": "float"},
                {"name": "total_return", "type": "float"},
                {"name": "annual_return", "type": "float"},
                {"name": "max_drawdown", "type": "float"},
                {"name": "sharpe", "type": "float"},
                {"name": "win_rate", "type": "float"},
                {"name": "trade_count", "type": "integer"},
            ],
        },
        "trade_log": {
            "columns": [
                {"name": "timestamp", "type": "string"},
                {"name": "code", "type": "string"},
                {"name": "side", "type": "string"},
                {"name": "price", "type": "float"},
                {"name": "qty", "type": "float"},
                {"name": "reason", "type": "string"},
            ],
        },
    },
    "artifacts": {
        "equity": {"schema": "equity_csv", "path": "artifacts/equity.csv"},
        "metrics": {"schema": "metrics_csv", "path": "artifacts/metrics.csv"},
        "trades": {"schema": "trade_log", "path": "artifacts/trades.csv"},
        "positions": {"schema": "positions_csv", "path": "artifacts/positions.csv"},
        "run_card_json": {"schema": "json", "path": "run_card.json"},
        "run_card_md": {"schema": "markdown", "path": "run_card.md"},
    },
}


def _expand_artifacts_spec(spec: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    """Expand artifacts_spec into a name -> metadata dict.

    Args:
        spec: Raw artifact spec.

    Returns:
        Expanded artifact metadata mapping.
    """
    if not isinstance(spec, dict):
        return {}
    schemas = spec.get("schemas") or {}
    artifacts = spec.get("artifacts") or {}
    defaults = spec.get("defaults") or {}
    required = set(defaults.get("required") or [])
    expanded: Dict[str, Dict[str, Any]] = {}
    for name, meta in artifacts.items():
        if not isinstance(meta, dict):
            continue
        schema_name = meta.get("schema")
        schema = schemas.get(schema_name, {}) if isinstance(schemas, dict) else {}
        expanded[name] = {
            "path": meta.get("path"),
            "required": bool(meta.get("required", name in required)),
            "columns": meta.get("columns") or schema.get("columns"),
        }
    return expanded


class Runner:
    """Execute entry scripts inside a run directory and collect outputs."""

    def __init__(self, timeout: int = 300, artifacts_spec: Optional[Dict[str, Any]] = None) -> None:
        """Initialize runner.

        Args:
            timeout: Max subprocess runtime in seconds.
            artifacts_spec: Artifact spec from config.
        """

        self.timeout = timeout
        self.artifacts_spec = artifacts_spec or _ARTIFACTS_SPEC
        self.artifact_entries = _expand_artifacts_spec(self.artifacts_spec)

    def _python_ready(self, python_cmd: str) -> bool:
        """Check whether a Python interpreter can import runtime dependencies.

        Args:
            python_cmd: Interpreter executable path.

        Returns:
            True if required imports succeed, otherwise False.
        """

        try:
            probe = subprocess.run(
                [python_cmd, "-c", "import pandas,numpy; print('ok')"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
            return probe.returncode == 0
        except Exception:
            return False

    def _pick_python_interpreter(self) -> str:
        """Pick the first usable interpreter for backtest execution.

        Returns:
            Interpreter command path.
        """

        project_root = Path(__file__).resolve().parents[2]
        candidates = [
            project_root / ".venv" / "Scripts" / "python.exe",
            project_root / ".venv" / "bin" / "python",
            Path(sys.executable),
        ]
        for path in candidates:
            if not path.exists():
                continue
            cmd = str(path)
            if self._python_ready(cmd):
                return cmd
        return sys.executable

    def _build_runtime_env(self, run_dir: Path, *, pythonpath_extra: Path | None = None) -> dict[str, str]:
        """Build subprocess env and enforce no-proxy execution.

        Args:
            run_dir: Current run directory.
            pythonpath_extra: Additional path to prepend to PYTHONPATH.

        Returns:
            Environment mapping for subprocess.
        """

        env = _copy_runtime_env()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )

        if pythonpath_extra:
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(pythonpath_extra) + (os.pathsep + existing if existing else "")

        # Preserve system proxy settings; data sources (OKX/yfinance) need network access.
        # HOME/USERPROFILE are overridden per-execution in ``execute()`` (ephemeral
        # sandbox home, VT-001); the inherited value from the allowlist is only a
        # fallback if that temp-dir creation fails.

        return env

    def _run_sandboxed(self, cmd: list[str], run_kwargs: dict[str, Any]) -> "subprocess.CompletedProcess[str]":
        """Run the subprocess, dropping to ``vibe-sandbox`` when the host allows it.

        When the UID drop is unavailable — no such user (the common case outside
        the hardened container) or the caller lacks CAP_SETUID — a clear WARNING
        is logged and the process runs without the drop. The AST static defense in
        backtest/runner.py stays active regardless, so this fallback is safe.
        """
        creds = _resolve_sandbox_credentials()
        if creds is not None:
            user, group = creds
            try:
                return subprocess.run(cmd, user=user, group=group, **run_kwargs)
            except (PermissionError, LookupError, OSError) as exc:
                logger.warning(
                    "Sandbox UID drop to %r failed (%s); running the generated-code "
                    "subprocess WITHOUT the privilege-drop layer. The AST static "
                    "defense (backtest/runner.py) remains active.",
                    user,
                    exc,
                )
        return subprocess.run(cmd, **run_kwargs)

    def execute(
        self,
        entry_script: Path,
        run_dir: Path,
        *,
        cwd: Path | None = None,
        cli_args: list[str] | None = None,
    ) -> RunResult:
        """Run entry script and collect logs and artifacts.

        Args:
            entry_script: Entry script path.
            run_dir: Current run directory.
            cwd: Working directory for subprocess (default: entry_script.parent).
            cli_args: Additional CLI arguments appended to subprocess command.

        Returns:
            RunResult object with process output and discovered artifacts.
        """

        console.print(f"[blue]Runner: executing {entry_script}[/blue]")
        stdout_path = run_dir / "logs" / "runner_stdout.txt"
        stderr_path = run_dir / "logs" / "runner_stderr.txt"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.time()
        console.print("[dim]Runner: starting backtest subprocess...[/dim]")

        effective_cwd = cwd or entry_script.parent
        pythonpath_extra = cwd if cwd else None
        env = self._build_runtime_env(run_dir, pythonpath_extra=pythonpath_extra)
        python_cmd = self._pick_python_interpreter()
        console.print(f"[dim]Runner: using Python: {python_cmd}[/dim]")

        cmd = [python_cmd, str(entry_script)]
        if cli_args:
            cmd.extend(cli_args)

        # VT-001 defense-in-depth: give the generated-code subprocess an ephemeral
        # HOME (so it can't read the persistent ~/.vibe-trading secrets/state),
        # drop to an unprivileged UID where the hardened container supports it,
        # and cap its address space / fd count on top of the wall-clock timeout.
        real_home = None
        home_value = env.get("HOME") or env.get("USERPROFILE")
        if home_value:
            real_home = Path(home_value)
        elif pwd is not None:
            try:
                real_home = Path.home()
            except (RuntimeError, OSError):
                real_home = None

        sandbox_home: Path | None = None
        try:
            sandbox_home = _prepare_sandbox_home(real_home)
        except OSError as exc:
            logger.warning(
                "Could not create ephemeral sandbox HOME (%s); subprocess inherits HOME.",
                exc,
            )
        if sandbox_home is not None:
            env["HOME"] = str(sandbox_home)
            env["USERPROFILE"] = str(sandbox_home)
            # Keep well-behaved (platformdirs) library caches persistent so the
            # ephemeral HOME does not force a full re-download every run.
            if real_home is not None:
                env["XDG_CACHE_HOME"] = str(real_home / ".cache")

        run_kwargs: dict[str, Any] = dict(
            cwd=str(effective_cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.timeout,
            env=env,
            encoding="utf-8",
            errors="ignore",
        )
        preexec = _make_rlimit_preexec()
        if preexec is not None:
            run_kwargs["preexec_fn"] = preexec

        try:
            process = self._run_sandboxed(cmd, run_kwargs)
        finally:
            if sandbox_home is not None:
                shutil.rmtree(sandbox_home, ignore_errors=True)

        elapsed = time.time() - start_time
        console.print(f"[blue]Runner: subprocess finished in {elapsed:.2f}s[/blue]")

        stdout_path.write_text(process.stdout, encoding="utf-8")
        stderr_path.write_text(process.stderr, encoding="utf-8")

        if process.stdout:
            console.print(f"[dim]Runner stdout:[/dim]\n{process.stdout}")
        if process.stderr:
            console.print(f"[red]Runner stderr:[/red]\n{process.stderr}")

        artifacts: dict[str, Path] = {}
        for name, info in self.artifact_entries.items():
            rel_path = info.get("path")
            if not isinstance(rel_path, str) or not rel_path.strip():
                continue
            target = run_dir / Path(rel_path)
            if target.exists():
                artifacts[name] = target

        success = process.returncode == 0
        return RunResult(
            success=success,
            exit_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            artifacts=artifacts,
        )
